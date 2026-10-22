"""Macro tab: inflation, rates, credit spreads by rating, labour, money, fuel and power (FRED, CBS, Bank of Israel, EIA)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .common import ROOT, cutoff_date, get, merge_series, read_series, save_probe, today_utc

CONFIG = ROOT / "config" / "macro.json"
DAILY_FROM = "2000-01-01"
MONTHLY_FROM = "1989-01-01"
HEAT_RATE = 7.0   # MMBtu of gas per MWh, a typical combined-cycle plant


def load() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _parse_csv(text: str) -> dict[str, float]:
    out = {}
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        if len(row) < 2 or row[1] in (".", ""):
            continue
        try:
            out[row[0][:10]] = float(row[1])
        except ValueError:
            continue
    return out


def fred_series(code: str) -> dict[str, float]:
    from .sources import _fred_csv
    r = _fred_csv(code)
    pts = _parse_csv(r.text)
    if not pts:
        save_probe(f"fred_{code}", r.text[:2000])
        raise ValueError(f"FRED {code}: no rows")
    return pts


def _transform(pts: dict[str, float], spec: dict) -> dict[str, float]:
    s = pd.Series(pts).sort_index()
    tf = spec.get("tf")
    if tf == "yoy":
        s.index = pd.to_datetime(s.index)
        s = (s / s.shift(12, freq="MS").reindex(s.index) - 1) * 100 if spec.get("freq") == "m" else s.pct_change(252) * 100
        s.index = s.index.strftime("%Y-%m-%d")
    elif tf == "diff":
        s = s.diff()
    s = s * float(spec.get("scale", 1))
    start = DAILY_FROM if spec.get("freq") == "d" else MONTHLY_FROM
    s = s[(s.index >= start) & (s.index <= cutoff_date())].dropna()
    return {d: round(float(v), 6) for d, v in s.items()}


# --------------------------------------------------------------------------- Israel
def cbs_cpi(code: int) -> tuple[dict, dict]:
    """Israel CPI from the Central Bureau of Statistics API: (yearly % change, monthly % change)."""
    url = "https://api.cbs.gov.il/index/data/price"
    end = today_utc()
    js = get(url, params={"id": code, "format": "json", "download": "false", "startPeriod": "01-1995",
                          "endPeriod": f"{end.month:02d}-{end.year}"}, timeout=40, tries=2, expect_json=True)
    yoy, mom = {}, {}

    def walk(o):
        if isinstance(o, dict):
            if "year" in o and "month" in o:
                try:
                    d = f"{int(o['year']):04d}-{int(o['month']):02d}-01"
                except (TypeError, ValueError):
                    d = None
                if d:
                    for k, tgt in (("percentYear", yoy), ("percent", mom)):
                        v = o.get(k)
                        if isinstance(v, (int, float)):
                            tgt[d] = float(v)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(js)
    if len(yoy) < 24:
        save_probe("cbs_cpi", json.dumps(js, ensure_ascii=False)[:4000])
        raise ValueError(f"CBS {code}: {len(yoy)} months")
    return yoy, mom


def boi_rate() -> dict:
    url = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/BR/1.0/MNT_RIB_BOI_D"
    r = get(url, params={"startperiod": "2000-01-01", "format": "csv"}, timeout=40, tries=2)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    out = {}
    for row in rows:
        d, v = row.get("TIME_PERIOD"), row.get("OBS_VALUE")
        try:
            out[str(d)[:10]] = float(v)
        except (TypeError, ValueError):
            continue
    if len(out) < 100:
        save_probe("boi_rate", r.text[:3000])
        raise ValueError(f"BOI: {len(out)} rows")
    # daily series that only changes on decision days: keep the change points and the latest day
    s = pd.Series(out).sort_index()
    keep = s[(s.diff() != 0) | (s.index == s.index[-1])]
    return {d: float(v) for d, v in keep.items()}


# --------------------------------------------------------------------------- EIA wholesale power
HUB_KEYS = {"pjm": ("pjm",), "ercot": ("ercot",), "sp15": ("sp15", "sp-15", "sp 15"), "nepool": ("mass", "nepool"),
            "midc": ("mid c", "mid-c", "midc"), "np15": ("np15", "np-15"), "palo": ("palo",), "indiana": ("indiana",)}


def _eia_year(year: int, final: bool) -> pd.DataFrame:
    base = "https://www.eia.gov/electricity/wholesale/xls/"
    urls = [f"{base}archive/ice_electric-{year}final.xlsx", f"{base}ice_electric-{year}final.xlsx"] if final else [f"{base}ice_electric-{year}.xlsx"]
    last = None
    for u in urls:
        try:
            r = get(u, timeout=60, tries=2)
            return pd.read_excel(io.BytesIO(r.content))
        except Exception as e:
            last = e
    raise RuntimeError(f"EIA {year}: {last}")


def eia_power(backfill: bool) -> dict[str, dict[str, float]]:
    y = today_utc().year
    frames = [_eia_year(y, False)]
    for yy, fin in ((y - 1, True), (y - 2, True)) if backfill else ((y - 1, True),):
        try:
            frames.append(_eia_year(yy, fin))
        except Exception:
            if yy == y - 1:
                try:
                    frames.append(_eia_year(yy, False))
                except Exception:
                    pass
    df = pd.concat(frames, ignore_index=True)
    cols = {c: str(c).strip().lower() for c in df.columns}
    hub = next((c for c, l in cols.items() if "hub" in l), None)
    date = next((c for c, l in cols.items() if "trade date" in l), None) or next((c for c, l in cols.items() if "date" in l), None)
    price = next((c for c, l in cols.items() if "wtd" in l or "weighted" in l), None) or next((c for c, l in cols.items() if "avg" in l), None)
    if not (hub and date and price):
        save_probe("eia_power", df.head(20).to_csv())
        raise ValueError(f"EIA columns not found: {list(df.columns)[:12]}")
    df = df[[hub, date, price]].dropna()
    df[date] = pd.to_datetime(df[date], errors="coerce")
    df[price] = pd.to_numeric(df[price], errors="coerce")
    df = df.dropna()
    out = {}
    for key, words in HUB_KEYS.items():
        m = df[df[hub].astype(str).str.lower().map(lambda h: any(w in h for w in words))]
        if m.empty:
            continue
        s = m.groupby(m[date].dt.strftime("%Y-%m-%d"))[price].mean()
        s = s[(s > -500) & (s < 5000)]
        out[key] = {d: round(float(v), 3) for d, v in s.items() if d <= cutoff_date()}
    if not out:
        save_probe("eia_power", df.head(30).to_csv())
        raise ValueError("EIA: no known hubs")
    return out


def spark(power: dict[str, float], gas: dict[str, float]) -> dict[str, float]:
    if not power or not gas:
        return {}
    g = pd.Series(gas).sort_index()
    g.index = pd.to_datetime(g.index)
    out = {}
    for d, p in sorted(power.items()):
        t = pd.Timestamp(d)
        gg = g[(g.index <= t) & (g.index >= t - pd.Timedelta(days=4))]
        if len(gg):
            out[d] = round(p - HEAT_RATE * float(gg.iloc[-1]), 3)
    return out


# --------------------------------------------------------------------------- yield curve snapshot
def curve(cfg: dict, have: dict | None = None) -> dict:
    start = (today_utc() - dt.timedelta(days=420)).isoformat()
    have = have or {}
    todo = [c[0] for c in cfg["curve"] if not isinstance(have.get(c[0]), dict)]
    with ThreadPoolExecutor(6) as ex:
        res = {**{k: v for k, v in have.items() if isinstance(v, dict)}, **dict(zip(todo, ex.map(lambda c: _safe(fred_series, c), todo)))}
    frame = pd.DataFrame({code: pd.Series(pts) for code, pts in res.items() if isinstance(pts, dict)})
    frame = frame[(frame.index >= start) & (frame.index <= cutoff_date())].sort_index().dropna(how="all")
    if frame.empty:
        raise ValueError("no curve data")
    last = frame.dropna(thresh=max(1, len(frame.columns) - 2)).index[-1]

    def row_at(days):
        target = (dt.date.fromisoformat(last) - dt.timedelta(days=days)).isoformat()
        sub = frame[frame.index <= target]
        if sub.empty:
            return None
        d = sub.dropna(thresh=max(1, len(frame.columns) - 2)).index[-1]
        return {"date": d, "v": [round(float(frame.at[d, c[0]]), 3) if c[0] in frame.columns and pd.notna(frame.at[d, c[0]]) else None
                                 for c in cfg["curve"]]}
    return {"tenors": [c[1] for c in cfg["curve"]], "years": [c[2] for c in cfg["curve"]],
            "now": row_at(0), "m1": row_at(30), "m6": row_at(182), "y1": row_at(365)}


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return e


# --------------------------------------------------------------------------- run
def run() -> tuple[dict, dict, str]:
    """Returns ({series id: points}, curve snapshot, message). Series that fail keep their stored history."""
    cfg = load()
    specs = cfg["series"]
    codes = sorted({s["fred"] for s in specs if s.get("fred")} | {c[0] for c in cfg["curve"]})
    with ThreadPoolExecutor(6) as ex:
        raw = dict(zip(codes, ex.map(lambda c: _safe(fred_series, c), codes)))
    out, failed = {}, []
    for s in specs:
        sid = s["id"]
        try:
            if s.get("fred"):
                pts = raw[s["fred"]]
                if isinstance(pts, Exception):
                    raise pts
                out[sid] = _transform(pts, s)
            elif s.get("cbs"):
                try:
                    yoy, mom = cbs_cpi(s["cbs"])
                    out[sid] = yoy
                    out["il_cpi_mom"] = mom
                except Exception:
                    fb = fred_series(s["fred_fallback"])
                    out[sid] = _transform(fb, {**s, "tf": None})
            elif s.get("boi"):
                try:
                    out[sid] = boi_rate()
                except Exception:
                    out[sid] = _transform(fred_series(s["fred_fallback"]), {**s, "freq": "m"})
        except Exception as e:
            failed.append(f"{sid}: {str(e)[:80]}")
    # wholesale power and spark spreads
    eia_ids = {s["eia"]: s["id"] for s in specs if s.get("eia")}
    try:
        backfill = len(read_series("pw_pjm")) < 300
        hubs = eia_power(backfill)
        for key, sid in eia_ids.items():
            if hubs.get(key):
                out[sid] = hubs[key]
    except Exception as e:
        failed.append(f"EIA: {str(e)[:100]}")
    gas = {**read_series("hh_gas"), **out.get("hh_gas", {})}
    for s in specs:
        if s.get("spark"):
            pw = {**read_series(s["spark"]), **out.get(s["spark"], {})}
            sp = spark(pw, gas)
            if sp:
                out[s["id"]] = sp
    for sid in [k for k, v in out.items() if not v]:
        out.pop(sid)
        failed.append(f"{sid}: empty")
    try:
        cv = curve(cfg, raw)
    except Exception as e:
        cv = {}
        failed.append(f"curve: {str(e)[:80]}")
    got = len([s for s in specs if s["id"] in out])
    msg = f"{got}/{len(specs)} סדרות" + (f" · חסרים: {'; '.join(failed[:6])}" if failed else "")
    return out, cv, msg


def payload(cfg: dict | None = None) -> dict:
    """Stored macro series for the site, in the same compact format as series.json."""
    cfg = cfg or load()
    epoch = dt.date(1970, 1, 1)
    ser = {}
    for s in cfg["series"]:
        pts = read_series(s["id"])
        if not pts:
            continue
        ks = sorted(pts)
        if s.get("freq") == "d" and len(ks) > 800:
            # daily history older than three years is thinned to one point a week, which keeps the file small
            cut = (dt.date.fromisoformat(ks[-1]) - dt.timedelta(days=3 * 365)).isoformat()
            old = pd.Series({k: pts[k] for k in ks if k < cut})
            if len(old):
                wk = pd.to_datetime(old.index).to_period("W")
                keep = set(old.groupby(wk).apply(lambda x: x.index[-1]))
                ks = [k for k in ks if k >= cut or k in keep]
        ser[s["id"]] = {"t": [(dt.date.fromisoformat(k) - epoch).days for k in ks], "v": [pts[k] for k in ks]}
    return ser


def indicator_defs(cfg: dict | None = None) -> list[dict]:
    """Macro series as indicator definitions, so the site's detail view, charts and search work for them."""
    cfg = cfg or load()
    src_name = lambda s: ("FRED · " + s["fred"]) if s.get("fred") else ("הלמ\"ס" if s.get("cbs") or s.get("cbs_mom") else
                                                                         "בנק ישראל" if s.get("boi") else "EIA (ICE)" if s.get("eia") else
                                                                         "EIA ו-FRED, חישוב" if s.get("spark") else "")
    src_url = lambda s: (f"https://fred.stlouisfed.org/series/{s['fred']}" if s.get("fred") else
                         "https://www.cbs.gov.il/he/subjects/Pages/מדד-המחירים-לצרכן.aspx" if s.get("cbs") or s.get("cbs_mom") else
                         "https://www.boi.org.il/" if s.get("boi") else "https://www.eia.gov/electricity/wholesale/")
    out = []
    for i, s in enumerate(cfg["series"]):
        out.append({"id": s["id"], "order": 900 + i, "group": "m_" + s["sec"], "tab": "macro", "name": s["name"], "short": s.get("short", ""),
                    "freq": s.get("freq", "d"), "pol": 0, "dec": s.get("dec", 2), "unit": "%" if s.get("unit") == "%" else "",
                    "munit": s.get("unit", ""), "pin": False, "comp": False, "auto": True, "src": src_name(s), "srcUrl": src_url(s),
                    "desc": s.get("desc", ""), **({"rating": s["rating"]} if "rating" in s else {}), **({"key": True} if s.get("key") else {})})
    return out


def site_meta(cfg: dict | None = None) -> dict:
    cfg = cfg or load()
    secs = []
    for sec in cfg["sections"]:
        ids = [s["id"] for s in cfg["series"] if s["sec"] == sec["id"]] + cfg.get("reuse", {}).get(sec["id"], [])
        secs.append({**sec, "ids": ids})
    return {"sections": secs}
