"""Marketing tab ("שיווק"): what a salesperson needs before a call with an investor.

Inputs (hand-kept and written by the daily marketing task, see data/marketing/):
  config/marketing.json        mega caps, US sector ETFs, Tel Bond indices for the Israeli corporate spread
  data/marketing/holdings.json the securities the funds hold (names only, no amounts), each linked to an issuer
  data/marketing/issuers.json  one profile per issuer: what it does, sector, competitors, Yahoo symbol, news query
  data/marketing/stories.json  the day's public stories about the mega caps (daily task)
  data/marketing/news.json     a short Hebrew "what's new" per issuer with something new (daily task)
  data/marketing/weekly.json   the weekly brief for the marketing team: talking points on Israeli and US companies (weekly task)

This step adds, on every full run:
  prices   day / month-to-date / year-to-date / 12 months for the mega caps and every priced holding, and how unusual
           today's move was (in standard deviations of the last 60 daily moves) -> data/derived/mkt_px.json
  news     the latest headlines per issuer from Google News RSS, a rotating slice per run so that every issuer is
           refreshed at least daily -> data/derived/mkt_news.json
  spreads  the Israeli corporate spread over government bonds: the index-weighted "מרווח מהממשלתי" of the Tel Bond
           indices on Bizportal -> data/series/il_tb*_spread.csv (a daily series that grows from the first run)
build_payload() merges all of it (plus the calendar's reports and analysts for the held companies) into the one file
the site loads when the tab opens: site/data/marketing.json.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import html
import io
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import numpy as np
import pandas as pd

from .common import ROOT, dump_json, get, merge_series, read_series, save_probe, today_utc

CFG_FILE = ROOT / "config" / "marketing.json"
MK = ROOT / "data" / "marketing"
CAL = ROOT / "data" / "calendar"
PX_OUT = ROOT / "data" / "derived" / "mkt_px.json"
NEWS_OUT = ROOT / "data" / "derived" / "mkt_news.json"


def load_cfg() -> dict:
    return json.loads(CFG_FILE.read_text(encoding="utf-8"))


def _read(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def holdings() -> list[dict]:
    return _read(MK / "holdings.json", {}).get("holdings", [])


def issuers() -> dict:
    """Profiles of the issuers we hold. holdings.json decides: a profile no holding points to is ignored."""
    held = {h.get("i") for h in holdings()}
    return {k: v for k, v in _read(MK / "issuers.json", {}).get("issuers", {}).items() if k in held}


def symbols(cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_cfg()
    out = [m[0] for m in cfg["megacaps"]] + [s for s, _ in cfg["us_sectors"]]
    out += [v["y"] for v in issuers().values() if v.get("y")]
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------ prices
def _r(x, nd=4):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def stats(s: pd.Series) -> dict | None:
    s = s.dropna()
    s = s[s > 0]
    if len(s) < 3:
        return None
    idx = pd.to_datetime(s.index)
    last_d, last = idx[-1], float(s.iloc[-1])
    def base_before(day):
        b = s[idx < day]
        return float(b.iloc[-1]) if len(b) else None
    m0 = base_before(pd.Timestamp(last_d.year, last_d.month, 1))
    y0 = base_before(pd.Timestamp(last_d.year, 1, 1))
    y1b = s[idx <= last_d - pd.Timedelta(days=365)]
    rets = s.pct_change().dropna()
    d1 = float(rets.iloc[-1]) if len(rets) else None
    sd = float(rets.iloc[-61:-1].std()) if len(rets) > 30 else None
    hi = float(s[idx > last_d - pd.Timedelta(days=365)].max())
    w = s[idx > last_d - pd.Timedelta(days=200)]
    return {"last": _r(last, 4), "date": last_d.strftime("%Y-%m-%d"), "d1": _r(d1), "w1": _r(last / float(s.iloc[-6]) - 1) if len(s) > 6 else None,
            "mtd": _r(last / m0 - 1) if m0 else None, "ytd": _r(last / y0 - 1) if y0 else None,
            "y1": _r(last / float(y1b.iloc[-1]) - 1) if len(y1b) else None,
            "z": _r(d1 / sd, 2) if d1 is not None and sd else None, "dd52": _r(last / hi - 1) if hi else None,
            "spark": [round(float(v) / float(w.iloc[0]) * 100, 2) for v in w.iloc[::3]] if len(w) > 10 else []}


def update_prices(cfg: dict | None = None) -> tuple[dict, str]:
    from .markets import yf_close
    syms = symbols(cfg)
    start = (today_utc() - dt.timedelta(days=420)).isoformat()
    px = pd.DataFrame()
    for i in range(0, len(syms), 80):   # batches keep one bad symbol from failing the lot
        part = syms[i:i + 80]
        try:
            f = yf_close(part, start)
        except Exception as e:
            print("marketing prices batch failed:", e)
            continue
        px = f if px.empty else px.join(f, how="outer")
    old = _read(PX_OUT, {}).get("items", {})
    items, miss = {}, []
    for s in syms:
        st = stats(px[s]) if s in px.columns else None
        if st:
            items[s] = st
        elif s in old:   # keep the last good values rather than dropping the card
            items[s] = {**old[s], "stale": True}
            miss.append(s)
        else:
            miss.append(s)
    out = {"asof": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "items": items}
    dump_json(PX_OUT, out)
    if len(items) < len(syms) * 0.6:
        raise ValueError(f"only {len(items)} of {len(syms)} symbols priced")
    return out, f"{len(items) - len([m for m in miss if m in items])} מתוך {len(syms)} ניירות" + (f" · חסרים: {', '.join(miss[:10])}" if miss else "")


# ------------------------------------------------------------------ news headlines (Google News RSS)
STOP = {"בע\"מ", "אג\"ח", "קבוצת", "קבוצה", "השקעות", "החזקות", "בנק", "חברת", "מדד", "the", "inc", "corp", "group", "co", "ltd", "plc"}
PREFIX = ("וה", "של", "מה", "וב", "לה", "בה", "שה", "כש", "ול", "ומ", "ה", "ו", "ב", "ל", "מ", "ש", "כ")


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[\w\"'׳״\-.&]+", text.lower()):
        w = w.strip(".'\"-")
        out.add(w)
        for p in PREFIX:   # Hebrew prefixes: "בלאומי", "והפניקס"
            if w.startswith(p) and len(w) - len(p) >= 2:
                out.add(w[len(p):])
    return out


def _feed(q: str, lang: str) -> list[dict]:
    if lang == "he":
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:30d&hl=he&gl=IL&ceid=IL:he"
    else:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:30d&hl=en-US&gl=US&ceid=US:en"
    r = get(url, timeout=20, tries=2)
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        t = html.unescape((it.findtext("title") or "").strip())
        src = (it.findtext("source") or "").strip()
        if src and t.endswith(" - " + src):
            t = t[: -len(src) - 3].strip()
        try:
            d = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
        except Exception:
            d = None
        out.append({"t": t[:220], "src": src[:60], "u": (it.findtext("link") or "").strip(), "d": d})
    return out


def _relevant(item: dict, iss: dict) -> bool:
    """Keep a headline only if it names the issuer (Google's matching is loose for short or common names)."""
    words = _words(item["t"])
    names = [iss.get("he") or "", iss.get("en") or "", iss.get("q") or ""] + [a for a in (iss.get("cal") or []) if len(str(a)) >= 2]
    for n in names:
        toks = [x.strip(".'\"-") for x in re.split(r"[\s()\-,/]+", n.lower()) if x]
        toks = [x for x in toks if len(x) >= 2 and x not in STOP]
        if toks and toks[0] in words:
            return True
    return False


def update_news(cfg: dict | None = None) -> tuple[dict, str]:
    cfg = cfg or load_cfg()
    nc = cfg.get("news", {})
    per_run, keep, days, pause = nc.get("per_run", 120), nc.get("keep", 8), nc.get("days", 45), nc.get("sleep", 0.6)
    iss = {k: v for k, v in issuers().items() if v.get("type") == "co" and v.get("q")}
    store = _read(NEWS_OUT, {"items": {}})
    have = store.setdefault("items", {})
    order = sorted(iss, key=lambda k: (have.get(k) or {}).get("at") or "")   # oldest refresh first
    since = (today_utc() - dt.timedelta(days=days)).isoformat()
    done, fails, last_err = 0, 0, ""
    for k in order[:per_run]:
        v = iss[k]
        try:
            items = [x for x in _feed(v["q"], v.get("lang", "he")) if _relevant(x, v)]
        except Exception as e:
            fails += 1
            last_err = f"{type(e).__name__}: {e}"[:120]
            if fails >= 8 and done == 0:
                break   # the feed is blocked for this runner: stop early
            continue
        old = (have.get(k) or {}).get("items", [])
        seen, merged = set(), []
        for x in sorted(items + old, key=lambda x: x.get("d") or "", reverse=True):
            key = re.sub(r"\W+", "", x["t"])[:60]
            if key in seen or (x.get("d") and x["d"] < since):
                continue
            seen.add(key)
            merged.append(x)
        have[k] = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "items": merged[:keep]}
        done += 1
        time.sleep(pause)
    for k in list(have):
        if k not in iss:
            del have[k]
    store["asof"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    dump_json(NEWS_OUT, store)
    if done == 0:
        raise ValueError("Google News: " + (last_err or "no issuer refreshed"))
    fresh = sum(1 for k in iss if (have.get(k) or {}).get("at", "")[:10] >= (today_utc() - dt.timedelta(days=1)).isoformat())
    return store, f"{done} חברות עודכנו בריצה · {fresh}/{len(iss)} עודכנו ב-24 השעות האחרונות" + (f" · {fails} נכשלו ({last_err})" if fails else "")


# ------------------------------------------------------------------ Israeli corporate spread (Bizportal, Tel Bond)
def _num(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def tel_bond_spread(url: str) -> tuple[str, dict]:
    r = get(url, timeout=30, tries=2, headers={"Accept-Language": "he-IL,he;q=0.9"})
    text = r.text
    m = re.search(r"נכון ל[:\s]*?(\d{1,2})/(\d{1,2})/(\d{4})", text)
    tables = pd.read_html(io.StringIO(text))
    t = next((x for x in tables if any("מרווח" in str(c) for c in x.columns) and any("משקל" in str(c) for c in x.columns)), None)
    if t is None:
        save_probe("bizportal_tb", text)
        raise ValueError("no composition table with a spread column")
    cw = next(c for c in t.columns if "משקל" in str(c))
    cs = next(c for c in t.columns if "מרווח" in str(c))
    cy = next((c for c in t.columns if "תשואה" in str(c) and "ברוטו" in str(c)), None)
    cd = next((c for c in t.columns if "מח" in str(c) and "ם" in str(c)), None)
    rows = []
    for _, x in t.iterrows():
        w, s = _num(x[cw]), _num(x[cs])
        if w and s is not None and -5 < s < 30:
            rows.append((w, s, _num(x[cy]) if cy is not None else None, _num(x[cd]) if cd is not None else None))
    if len(rows) < 5:
        save_probe("bizportal_tb", text)
        raise ValueError(f"only {len(rows)} rows with a spread")
    W = sum(w for w, *_ in rows)
    spread = sum(w * s for w, s, *_ in rows) / W
    ys = [(w, y) for w, _, y, _ in rows if y is not None]
    ds = [(w, d) for w, _, _, d in rows if d is not None]
    date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else today_utc().isoformat()
    return date, {"spread": round(spread, 3), "yield": round(sum(w * y for w, y in ys) / sum(w for w, _ in ys), 3) if ys else None,
                  "dur": round(sum(w * d for w, d in ds) / sum(w for w, _ in ds), 2) if ds else None, "n": len(rows), "w": round(W, 1)}


def update_spreads(cfg: dict | None = None) -> tuple[str | None, str]:
    cfg = cfg or load_cfg()
    msgs, last = [], None
    for ix in cfg.get("il_tb", []):
        try:
            d, v = tel_bond_spread(ix["url"])
            merge_series(ix["id"], {d: v["spread"]})
            if v.get("yield") is not None:
                merge_series(ix["id"].replace("_spread", "_yield"), {d: v["yield"]})
            msgs.append(f"{ix['name']}: {v['spread']:.2f}% ({v['n']} סדרות, {v['w']:.0f}% מהמשקל)")
            last = max(last or d, d)
        except Exception as e:
            msgs.append(f"{ix['name']}: {type(e).__name__} {str(e)[:80]}")
    if last is None:
        raise ValueError("; ".join(msgs))
    return last, " · ".join(msgs)


# ------------------------------------------------------------------ the site payload
def _calendar(iss: dict) -> dict:
    """Reports of the held companies from the economic calendar: the last one (with the write-up, if any) and the next."""
    evs = []
    for p in sorted((CAL / "weeks").glob("*.json")):
        evs += _read(p, {}).get("events", [])
    evs += _read(CAL / "maya.json", {}).get("events", [])
    evs += _read(CAL / "extra.json", {}).get("events", [])
    evs += [e for e in _read(CAL / "nasdaq.json", {}).get("events", []) if e.get("id")]   # every US report >= $10B, 3 weeks ahead
    why = _read(CAL / "why.json", {}).get("items", {})
    an = _read(CAL / "analysts.json", {}).get("items", {})
    by = {}
    for e in evs:
        by.setdefault(str(e.get("ticker", "")).upper(), {})[e["id"]] = e
    today = today_utc().isoformat()
    out = {}
    for k, v in iss.items():
        al = [str(a).upper() for a in (v.get("cal") or [])]
        es = {}
        for a in al:
            es.update(by.get(a, {}))
        rec = {}
        past = sorted([e for e in es.values() if e.get("date", "") <= today], key=lambda e: e["date"])
        fut = sorted([e for e in es.values() if e.get("date", "") > today], key=lambda e: e["date"])
        if past:
            e = past[-1]
            w = why.get(e["id"]) or {}
            rec["last"] = {"date": e["date"], "period": e.get("period"), "rep": w.get("rep"), "he": w.get("he"),
                           "bl": (w.get("an") or {}).get("bl"), "pts": (w.get("an") or {}).get("pts", [])[:4],
                           "pr": (w.get("links") or {}).get("pressRelease")}
        if fut:
            e = fut[0]
            rec["next"] = {"date": e["date"], "period": e.get("period"), "session": e.get("session")}
        a = next((an[x] for x in al if x in an), None)
        if a:
            rec["an"] = {"cur": a.get("cur"), "pe": (a.get("mult") or {}).get("pe"), "fpe": (a.get("mult") or {}).get("fpe"),
                         "mcap": (a.get("mult") or {}).get("mcap"), **{x: (a.get("avg") or {}).get(x) for x in ("bull", "neutral", "bear", "ptAvg", "n")},
                         "asof": a.get("asof")}
        if rec:
            out[k] = rec
    return out


def _upcoming(iss: dict, held: set, days: int = 10) -> list[dict]:
    """The coming days for the weekly brief: reports of the companies we hold and the main macro releases (Israel, US)."""
    today = today_utc()
    end = (today + dt.timedelta(days=days)).isoformat()
    t0 = today.isoformat()
    alias = {}
    for k, v in iss.items():
        if k in held:
            for a in v.get("cal") or []:
                alias.setdefault(str(a).upper(), k)
    evs = []
    for p in sorted((CAL / "weeks").glob("*.json")):
        evs += _read(p, {}).get("events", [])
    for f in ("maya.json", "extra.json", "nasdaq.json"):
        evs += _read(CAL / f, {}).get("events", [])
    out, seen = [], set()
    for e in sorted(evs, key=lambda e: e.get("date", "")):
        d, k = e.get("date", ""), alias.get(str(e.get("ticker", "")).upper())
        if k and t0 <= d <= end and (k, d) not in seen:
            seen.add((k, d))
            out.append({"date": d, "kind": "report", "key": k, "label": f"דוח {iss[k]['he']}" + (f" ({e.get('period')})" if e.get("period") else ""),
                        "mkt": "IL" if iss[k].get("ctry") == "IL" else "US", "session": e.get("session")})
    for e in _read(CAL / "macro.json", {}).get("events", []):
        d = e.get("date", "")
        if t0 <= d <= end and (e.get("imp") or 0) >= 2 and e.get("country") in ("IL", "US"):
            out.append({"date": d, "kind": "macro", "label": e.get("he") or e.get("en") or "", "mkt": e.get("country"), "imp": e.get("imp"),
                        "period": e.get("period")})
    return sorted(out, key=lambda x: (x["date"], x["kind"] != "macro", x["mkt"] != "IL"))


def _series_tail(sid: str, days: int = 400) -> dict:
    s = read_series(sid)
    if not s:
        return {}
    since = (today_utc() - dt.timedelta(days=days)).isoformat()
    ks = [k for k in sorted(s) if k >= since]
    return {"d": ks, "v": [s[k] for k in ks]}


def build_payload() -> dict:
    cfg = load_cfg()
    iss = issuers()
    hold = holdings()
    px = _read(PX_OUT, {})
    news = _read(NEWS_OUT, {})
    return {
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "megacaps": cfg["megacaps"], "usSectors": cfg["us_sectors"], "ilTb": cfg.get("il_tb", []),
        "issuers": iss, "holdings": hold,
        "px": px.get("items", {}), "pxAsof": px.get("asof"),
        "headlines": {k: v.get("items", []) for k, v in news.get("items", {}).items() if v.get("items")}, "newsAsof": news.get("asof"),
        "stories": _read(MK / "stories.json", {}), "notes": _read(MK / "news.json", {}),
        "weekly": _read(MK / "weekly.json", {}), "upcoming": _upcoming(iss, {h["i"] for h in hold}),
        "cal": _calendar(iss),
        "spreads": {ix["id"]: _series_tail(ix["id"]) for ix in cfg.get("il_tb", [])},
    }
