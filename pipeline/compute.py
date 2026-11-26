"""AI compute pricing: what renting an Nvidia GPU costs per hour, where its momentum is turning, and what Polymarket
prices for the coming months. Shown in the Macro tab (section "compute") and in the marketing tab's macro block.

Sources (free, no key):
  Ornn Compute Price Index (OCPI)  data.ornn.com/api/public-index/gpu/<name>/index-history: the trailing 3 months of
                                   daily settles per GPU, USD per GPU-hour, stamped at midnight New York time. The stored
                                   series data/series/gpu_*.csv keep everything ever fetched, so the history grows from
                                   the first run (the free tier only shows 3 months).
  Polymarket                       gamma-api.polymarket.com/events?slug=<pm>-average-rental-price-in-<month>-<year>: for
                                   each month a ladder of "will the average Ornn price be above $X" markets. The Yes
                                   prices are the market's probabilities; px = the price the market implies (the median:
                                   50% above, 50% below), lo / hi = its 10th and 90th percentiles. The median and not the
                                   mean, because the far months' ladders run to $10-30 with thin tails that drag a mean
                                   up (it stays close to the PIRP Polymarket shows; the mean is kept as "mean").

Momentum per GPU (thresholds in config/compute.json):
  trend  the 7-day average vs the 28-day average. It turns up when the gap rises above +band and down when it falls
         below -band, and stays until it crosses the other side; band grows with the GPU's day-to-day noise, so the
         jumpy H100 index needs a bigger gap than the smooth B200 index before it counts as a turn.
  surge  a sharp week: the 7-day average vs the week before, beyond max(10%, 3 x noise).
  pm     Polymarket's implied price for the nearest month moved 5% or more in a week.
Signals go to data/derived/compute.json under "alerts", each with the time it was first seen ("seen"). The daily email
task reads that file and mails the alerts seen since its last run; a signal that is already a few days old in the data
when first seen (first run, a late backfill, a revision) gets "old": true and is not mailed.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd

from .common import ROOT, dump_json, get, merge_series, read_series, save_probe

CFG = ROOT / "config" / "compute.json"
OUT = ROOT / "data" / "derived" / "compute.json"
ORNN = "https://data.ornn.com/api/public-index/gpu/{}/index-history"
GAMMA = "https://gamma-api.polymarket.com/events"
NY = ZoneInfo("America/New_York")
EN_MON = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
HE_MON = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
PM_MIN_VOL = 20000   # a thinner month is shown but does not raise a pm alert
KEEP_ALERTS = 80


def load() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8"))


def _read(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _r(x, nd=4):
    return None if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else round(float(x), nd)


# ------------------------------------------------------------------ Ornn
def ornn_history(name: str) -> dict[str, float]:
    """{New York date: USD per GPU-hour} for the trailing 3 months of daily settles."""
    j = get(ORNN.format(quote(name)), expect_json=True, timeout=30)
    rows = j.get("data") if isinstance(j, dict) else None
    if not rows or (isinstance(j, dict) and j.get("success") is False):
        save_probe("ornn_" + re.sub(r"\W+", "_", name), json.dumps(j)[:3000])
        raise ValueError(f"Ornn {name}: no rows")
    out = {}
    for r in rows:
        try:
            d = dt.datetime.fromisoformat(str(r["timestamp"]).replace("Z", "+00:00")).astimezone(NY).date().isoformat()
            v = float(r["index_value"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0.05 < v < 200:   # USD per GPU-hour; anything outside is a broken row
            out[d] = round(v, 4)
    if not out:
        raise ValueError(f"Ornn {name}: no valid rows")
    return out


# ------------------------------------------------------------------ Polymarket
def implied(ladder: list[tuple[float, float]]) -> dict | None:
    """ladder = [(threshold $, P(average > threshold))]. Returns the implied mean (Polymarket's PIRP: the probability
    between two thresholds sits at their midpoint, the tails half a step outside the ladder), the median and the 10th /
    90th percentiles (None when outside the ladder)."""
    lad = sorted((float(k), float(p)) for k, p in ladder if k is not None and p is not None and 0 <= p <= 1)
    if len(lad) < 3:
        return None
    ks, ps, m = [k for k, _ in lad], [], 1.0
    for _, p in lad:   # P(X > k) cannot rise with k: smooth out a crossed quote
        m = min(m, p)
        ps.append(m)

    def at(level):   # the price where P(X > price) = level
        if ps[0] <= level:
            return None
        for i in range(1, len(ks)):
            if ps[i] <= level:
                a, b = ps[i - 1], ps[i]
                return ks[i - 1] + (ks[i] - ks[i - 1]) * ((a - level) / (a - b) if a > b else 0.5)
        return None

    steps = sorted(ks[i + 1] - ks[i] for i in range(len(ks) - 1))
    step = steps[len(steps) // 2]
    mass = [(ks[0] - step / 2, 1 - ps[0])] + [((ks[i] + ks[i + 1]) / 2, ps[i] - ps[i + 1]) for i in range(len(ks) - 1)] + [(ks[-1] + step / 2, ps[-1])]
    tot = sum(w for _, w in mass)
    mean = sum(x * w for x, w in mass) / tot if tot > 0 else None
    return {"mean": _r(mean, 3), "med": _r(at(0.5), 3), "lo": _r(at(0.9), 3), "hi": _r(at(0.1), 3), "kmin": ks[0], "kmax": ks[-1]}


def _months(n: int) -> list[tuple[int, int]]:
    """The current month (New York) and the next n, then the Decembers of the next two years."""
    t = dt.datetime.now(NY).date()
    out = [((t.year * 12 + t.month - 1 + i) // 12, (t.month - 1 + i) % 12 + 1) for i in range(n + 1)]
    for y in (t.year + 1, t.year + 2):
        if (y, 12) not in out:
            out.append((y, 12))
    return out


def pm_month(prefix: str, y: int, m: int) -> dict | None:
    slug = f"{prefix}-average-rental-price-in-{EN_MON[m - 1]}-{y}"
    try:
        j = get(GAMMA, params={"slug": slug}, expect_json=True, timeout=20, tries=2)
    except Exception:
        return None
    evs = j if isinstance(j, list) else [j] if isinstance(j, dict) else []
    for ev in evs:
        if not isinstance(ev, dict) or ev.get("slug") != slug or ev.get("closed"):
            continue
        ladder, vol = [], 0.0
        for mk in ev.get("markets") or []:
            if mk.get("closed"):
                continue
            txt = f"{mk.get('groupItemTitle') or ''} {mk.get('question') or ''}"
            k = re.search(r"\$\s*([\d.]+)", txt)
            prices, outs = mk.get("outcomePrices"), mk.get("outcomes")
            try:
                prices = json.loads(prices) if isinstance(prices, str) else prices
                outs = json.loads(outs) if isinstance(outs, str) else outs
                p = float(prices[[str(o).lower() for o in outs].index("yes")] if outs else prices[0])
            except Exception:
                continue
            if not k:
                continue
            if re.search(r"\bbelow\b|\bunder\b", txt, re.I):
                p = 1 - p
            ladder.append((float(k.group(1)), p))
            try:
                vol += float(mk.get("volume") or 0)
            except ValueError:
                pass
        imp = implied(ladder)
        if not imp:
            return None
        return {"slug": slug, "month": f"{y}-{m:02d}", "n": len(ladder), "vol": round(vol), "end": ev.get("endDate"),
                "url": f"https://polymarket.com/event/{slug}", "px": imp["med"] if imp["med"] is not None else imp["mean"], **imp}
    return None


# ------------------------------------------------------------------ momentum
def momentum(pts: dict[str, float], p: dict) -> tuple[dict, list[dict]]:
    """The GPU's current reading and trend, and every signal in its history: [{kind, date, ...}]."""
    s = pd.Series(pts, dtype=float).sort_index()
    s.index = pd.to_datetime(s.index)
    s = s.asfreq("D").ffill(limit=3).dropna()   # Ornn settles every day; a missed day or two is carried
    if s.empty:
        return {}, []
    last, t_last = float(s.iloc[-1]), s.index[-1]

    def ago(days):
        b = s[s.index <= t_last - pd.Timedelta(days=days)]
        return float(b.iloc[-1]) if len(b) else None
    w30 = s[s.index > t_last - pd.Timedelta(days=30)]
    cur = {"last": _r(last, 3), "date": t_last.strftime("%Y-%m-%d"), "first": s.index[0].strftime("%Y-%m-%d"), "n": int(len(s)),
           "d1": _r(last / float(s.iloc[-2]) - 1) if len(s) > 1 else None,
           "w1": _r(last / ago(7) - 1) if ago(7) else None, "m1": _r(last / ago(30) - 1) if ago(30) else None,
           "lo30": _r(float(w30.min()), 3), "hi30": _r(float(w30.max()), 3),
           "spark": [round(float(v), 3) for v in s.iloc[-90:]]}
    f, w = int(p["fast"]), int(p["slow"])
    if len(s) < w + 2:
        cur["state"] = "short"
        return cur, []
    maf, mas = s.rolling(f).mean(), s.rolling(w).mean()
    r = maf / mas - 1
    noise = s.pct_change().rolling(56, min_periods=21).std() / math.sqrt(2)   # day-to-day noise of the index level
    band = (p["band_k"] * noise * math.sqrt(1 / f - 1 / w)).clip(lower=p["band_min"]).fillna(p["band_min"])
    wow = maf / maf.shift(f) - 1
    sthr = (p["surge_k"] * noise * math.sqrt(2 / f)).clip(lower=p["surge"]).fillna(p["surge"])
    ev, reg, since, arm_up, arm_dn = [], None, None, True, True
    for t in s.index:
        rt, bt = r[t], band[t]
        if pd.notna(rt):
            new = "up" if rt > bt else "down" if rt < -bt else reg
            if new != reg:
                if reg is not None:
                    ev.append({"kind": "turn_" + new, "date": t.strftime("%Y-%m-%d"), "v": _r(float(s[t]), 3),
                               "maf": _r(float(maf[t]), 3), "mas": _r(float(mas[t]), 3), "gap": _r(float(rt)), "band": _r(float(bt))})
                reg, since = new, t
        x, th = wow[t], sthr[t]
        if pd.notna(x):
            if x >= th and arm_up:
                ev.append({"kind": "surge", "date": t.strftime("%Y-%m-%d"), "v": _r(float(s[t]), 3), "wow": _r(float(x)), "thr": _r(float(th))})
                arm_up = False
            if x <= -th and arm_dn:
                ev.append({"kind": "plunge", "date": t.strftime("%Y-%m-%d"), "v": _r(float(s[t]), 3), "wow": _r(float(x)), "thr": _r(float(th))})
                arm_dn = False
            arm_up = arm_up or x < th / 2
            arm_dn = arm_dn or x > -th / 2
    gap, bnd = float(r.iloc[-1]), float(band.iloc[-1])
    state = ("up" if gap > bnd else "up_fading") if reg == "up" else ("down" if gap < -bnd else "down_fading") if reg == "down" else "flat"
    cur.update({"maf": _r(float(maf.iloc[-1]), 3), "mas": _r(float(mas.iloc[-1]), 3), "gap": _r(gap), "band": _r(bnd),
                "wow": _r(float(wow.iloc[-1])) if pd.notna(wow.iloc[-1]) else None, "surgeThr": _r(float(sthr.iloc[-1])),
                "reg": reg, "since": since.strftime("%Y-%m-%d") if since is not None else None, "state": state,
                "noise": _r(float(noise.iloc[-1])) if pd.notna(noise.iloc[-1]) else None})
    return cur, ev


# ------------------------------------------------------------------ alerts
def _d(iso: str) -> str:
    return f"{int(iso[8:10])}.{int(iso[5:7])}"


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%".replace("+-", "-")


def alert_text(g: dict, e: dict) -> str:
    nm, k = g["name"], e["kind"]
    if k == "turn_up":
        return (f"{nm}: המומנטום התהפך למעלה. הממוצע של 7 ימים (${e['maf']:.2f}) עלה מעל הממוצע של 28 ימים (${e['mas']:.2f}) "
                f"ב-{e['gap'] * 100:.1f}%, יותר מהסף של {e['band'] * 100:.1f}% למעבד הזה. המחיר ב-{_d(e['date'])}: ${e['v']:.2f} לשעה.")
    if k == "turn_down":
        return (f"{nm}: המומנטום התהפך למטה. הממוצע של 7 ימים (${e['maf']:.2f}) ירד מתחת לממוצע של 28 ימים (${e['mas']:.2f}) "
                f"ב-{abs(e['gap']) * 100:.1f}%, יותר מהסף של {e['band'] * 100:.1f}% למעבד הזה. המחיר ב-{_d(e['date'])}: ${e['v']:.2f} לשעה.")
    if k in ("surge", "plunge"):
        return (f"{nm}: {'עלייה' if k == 'surge' else 'ירידה'} חדה. הממוצע השבועי {'עלה' if k == 'surge' else 'ירד'} ב-{abs(e['wow']) * 100:.1f}% "
                f"לעומת השבוע הקודם (הסף: {e['thr'] * 100:.0f}%). המחיר ב-{_d(e['date'])}: ${e['v']:.2f} לשעה.")
    if k in ("pm_up", "pm_down"):
        y, m = int(e["month"][:4]), int(e["month"][5:7])
        return (f"{nm}: ב-Polymarket המחיר הצפוי ל{HE_MON[m - 1]} {y} {'עלה' if k == 'pm_up' else 'ירד'} ל-${e['px']:.2f} לשעה "
                f"(לפני שבוע ${e['prev']:.2f}, {_pct(e['chg'])}).")
    return nm


def merge_alerts(old: list[dict], new: list[dict], now: str, latest: dict[str, str], alert_days: int, first: bool) -> list[dict]:
    """Keep the first-seen time of known alerts; a new one is news only if its data date is recent."""
    by = {a["id"]: a for a in old or []}
    for a in new:
        if a["id"] in by:
            continue
        lt = latest.get(a["gpu"]) or a["date"]
        stale = first or (dt.date.fromisoformat(lt) - dt.date.fromisoformat(a["date"])).days > alert_days
        by[a["id"]] = {**a, "seen": (a["date"] + "T00:00Z") if stale else now, **({"old": True} if stale else {})}
    return sorted(by.values(), key=lambda a: (a["date"], a["seen"]), reverse=True)[:KEEP_ALERTS]


def pm_alerts(g: dict, front: dict | None, hist: dict, today: str, p: dict) -> list[dict]:
    """Polymarket's implied price for the nearest liquid month vs a week ago."""
    if not front or front.get("px") is None or (front.get("vol") or 0) < PM_MIN_VOL:
        return []
    h = hist.get(front["slug"]) or {}
    ref = [d for d in sorted(h) if d <= (dt.date.fromisoformat(today) - dt.timedelta(days=6)).isoformat()]
    if not ref:
        return []
    prev = h[ref[-1]]
    chg = front["px"] / prev - 1 if prev else 0
    if abs(chg) < p["pm_shift"]:
        return []
    kind = "pm_up" if chg > 0 else "pm_down"
    wk = dt.date.fromisoformat(today).isocalendar()
    return [{"kind": kind, "date": today, "month": front["month"], "px": front["px"], "prev": _r(prev, 3), "chg": _r(chg),
             "slug": front["slug"], "wk": f"{wk[0]}-W{wk[1]:02d}"}]


# ------------------------------------------------------------------ run
def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return e


def run() -> tuple[dict, str]:
    cfg = load()
    p = cfg["momentum"]
    old = _read(OUT, {})
    first = not old.get("gpus")
    now_dt = dt.datetime.now(dt.timezone.utc)
    now, today = now_dt.strftime("%Y-%m-%dT%H:%MZ"), now_dt.date().isoformat()
    gpus = cfg["gpus"]
    with ThreadPoolExecutor(5) as ex:
        got = dict(zip([g["id"] for g in gpus], ex.map(lambda g: _safe(ornn_history, g["ornn"]), gpus)))
    failed = []
    for g in gpus:
        r = got[g["id"]]
        if isinstance(r, Exception):
            failed.append(f"{g['name']}: {str(r)[:80]}")
        else:
            merge_series(g["id"], r)
    jobs = [(g["id"], g["pm"], y, m) for g in gpus if g.get("pm") for y, m in _months(int(cfg.get("pm_months", 13)))]
    with ThreadPoolExecutor(6) as ex:
        pm_res = list(ex.map(lambda j: _safe(pm_month, j[1], j[2], j[3]), jobs))
    pm = {}
    for (gid, *_), r in zip(jobs, pm_res):
        if isinstance(r, dict):
            pm.setdefault(gid, []).append(r)
    hist = old.get("pmHist") or {}
    for rows in pm.values():
        for r in rows:
            if r.get("px") is not None:
                hist.setdefault(r["slug"], {})[today] = r["px"]
    cut = (now_dt.date() - dt.timedelta(days=60)).isoformat()   # a month's history is all the weekly comparison needs
    hist = {k: {d: v for d, v in h.items() if d >= cut} for k, h in hist.items() if any(d >= cut for d in h)}
    out_g, events, latest = [], [], {}
    for g in gpus:
        pts = read_series(g["id"])
        if not pts:
            continue
        cur, ev = momentum(pts, p)
        rows = sorted(pm.get(g["id"], []), key=lambda r: r["month"])
        live = [r for r in rows if r["month"] > now_dt.astimezone(NY).strftime("%Y-%m")]   # months still ahead
        front = next((r for r in live if (r.get("vol") or 0) >= PM_MIN_VOL), live[0] if live else None)
        for r in rows:
            r["vsSpot"] = _r(r["px"] / cur["last"] - 1) if r.get("px") and cur.get("last") else None
            h = hist.get(r["slug"]) or {}
            ref = [d for d in sorted(h) if d <= (now_dt.date() - dt.timedelta(days=6)).isoformat()]
            r["w1"] = _r(r["px"] / h[ref[-1]] - 1) if ref and r.get("px") and h[ref[-1]] else None
        ev += pm_alerts(g, front, hist, today, p)
        latest[g["id"]] = cur.get("date") or today
        for e in ev:
            key = e.get("wk") if e["kind"].startswith("pm_") else e["date"]
            events.append({"id": f"{g['id']}:{e['kind']}:{key}", "gpu": g["id"], "name": g["name"], "dir": "up" if e["kind"] in ("turn_up", "surge", "pm_up") else "down",
                           **{k: v for k, v in e.items() if k != "wk"}, "text": alert_text(g, e)})
        out_g.append({**{k: g[k] for k in ("id", "name", "he", "code", "page") if k in g}, **cur, "pm": rows, "front": front["slug"] if front else None})
    if not out_g:
        raise ValueError("no GPU series: " + "; ".join(failed))
    alerts = merge_alerts(old.get("alerts") or [], events, now, latest, int(p.get("alert_days", 3)), first)
    out = {"asof": now, "params": p, "gpus": out_g, "alerts": alerts, "pmHist": hist,
           "src": {"ornn": "https://data.ornn.com/markets", "pm": "https://polymarket.com/tech/compute"}}
    dump_json(OUT, out)
    fresh = [a for a in alerts if a["seen"] == now]
    h100 = next((x for x in out_g if x["id"] == "gpu_h100"), out_g[0])
    msg = (f"{len(out_g)}/{len(gpus)} מעבדים · {h100['name']} ${h100['last']:.2f} ({_d(h100['date'])}) · "
           f"{sum(len(v) for v in pm.values())} חודשים ב-Polymarket" + (f" · {len(fresh)} איתותים חדשים" if fresh else "")
           + (f" · חסרים: {'; '.join(failed)}" if failed else ""))
    return out, msg


def last_date(out: dict) -> str | None:
    return max((g.get("date") or "" for g in out.get("gpus", [])), default=None) or None
