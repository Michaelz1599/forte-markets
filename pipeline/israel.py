"""Israel tab: breadth, trend and foreign-flow proxies for the Tel Aviv market, an Israeli sentiment index,
sector baskets, RS for the large TASE names, and Israeli macro (FRED/OECD/BIS, with CPI and the BoI rate from macro.py)."""
from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pandas as pd

from . import breadth
from .common import ROOT, merge_series, read_series, today_utc, write_series
from .markets import _r, cmf, yf_ohlc

CONFIG = ROOT / "config" / "israel.json"
DERIVED = ROOT / "data" / "derived" / "israel.json"


def load() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _pts(s: pd.Series, nd: int = 4, since: str | None = None) -> dict:
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    if since:
        s = s[s.index >= since]
    return {d: round(float(v), nd) for d, v in s.items()}


def chain(sid: str, s: pd.Series, since: str) -> dict:
    """Rescale a level series that depends on its start date so it continues the stored history."""
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    cur = read_series(sid)
    common = [d for d in s.index if d in cur and d < since] or [d for d in s.index if d in cur]
    if common and s[common[-1]]:
        s = s * (cur[common[-1]] / s[common[-1]])
    return _pts(s[s.index >= since] if cur else s, 5)


def basket(close: pd.DataFrame) -> pd.Series:
    """Equal-weight index of the given stocks (daily rebalanced), from the mean of daily returns."""
    r = close.pct_change(fill_method=None).clip(-0.5, 0.5)
    m = r.mean(axis=1, skipna=True).fillna(0.0)
    return (1 + m).cumprod() * 100


def rolling_pct(s: pd.Series, n: int = 1260, min_n: int = 250) -> pd.Series:
    """Point-in-time percentile (0-100) of each value within the trailing n observations."""
    return s.rolling(n, min_periods=min_n).rank(pct=True) * 100


def composite(series: dict[str, pd.Series], comps: list[str], pols: dict[str, int], min_parts: int = 5) -> pd.Series:
    parts = []
    for c in comps:
        s = series.get(c)
        if s is None or s.dropna().empty:
            continue
        p = rolling_pct(s.dropna())
        parts.append(p if pols.get(c, 1) > 0 else 100 - p)
    if not parts:
        return pd.Series(dtype=float)
    df = pd.concat(parts, axis=1).sort_index()
    df = df.ffill(limit=5)          # weekly gaps / holidays in one input should not drop the day
    ok = df.notna().sum(axis=1) >= min_parts
    return df.mean(axis=1)[ok]


def stock_rows(c: pd.DataFrame, h: pd.DataFrame, lo: pd.DataFrame, info: dict) -> list[dict]:
    """RS (2-week move in ATR units, percentile within these stocks) and momentum for each stock."""
    from .rs import N, rank_rs
    c = c.sort_index()
    if len(c) < 30:
        return []
    last = c.iloc[-1]
    prev = c.shift(1)
    tr = pd.concat([h - lo, (h - prev).abs(), (lo - prev).abs()]).groupby(level=0).max().reindex(c.index)
    atr = tr.iloc[-N:].mean()
    move = (last - c.iloc[-1 - N]) / atr.replace(0, np.nan)
    ok = move.notna() & c.iloc[-N - 1:].notna().all()
    rs = rank_rs(move[ok]) if ok.any() else pd.Series(dtype=int)
    out = []
    for sym in c.columns:
        s = c[sym].dropna()
        if len(s) < 30:
            continue
        def ret(n):
            return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None
        sma50 = s.rolling(50).mean().iloc[-1] if len(s) >= 50 else np.nan
        sma200 = s.rolling(200).mean().iloc[-1] if len(s) >= 200 else np.nan
        hi = s.iloc[-252:].max()
        nm, sec = info.get(sym, (sym, ""))
        out.append({"sym": sym.replace(".TA", ""), "y": sym, "name": nm, "sec": sec, "px": _r(s.iloc[-1], 2),
                    "rs": int(rs[sym]) if sym in rs.index else None, "raw": _r(move.get(sym), 2),
                    "w1": _r(ret(5)), "m1": _r(ret(21)), "m3": _r(ret(63)), "y1": _r(ret(252)),
                    "mom": _r(float(s.iloc[-22] / s.iloc[-253] - 1)) if len(s) > 253 else None,
                    "dd52": _r(float(s.iloc[-1] / hi - 1)),
                    "ma50": _r(float(s.iloc[-1] / sma50 - 1)) if math.isfinite(sma50) else None,
                    "ma200": _r(float(s.iloc[-1] / sma200 - 1)) if math.isfinite(sma200) else None,
                    "date": s.index[-1]})
    return out


def sector_rows(c: pd.DataFrame, info: dict, sec_names: dict, idx: pd.Series | None) -> list[dict]:
    out = []
    for key, name in sec_names.items():
        cols = [s for s in c.columns if info.get(s, ("", ""))[1] == key]
        if not cols:
            continue
        b = basket(c[cols]).dropna()
        if len(b) < 30:
            continue
        def ret(n, s=b):
            return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None
        prev_y = b[b.index < f"{b.index[-1][:4]}-01-01"]
        rel = None
        if idx is not None:
            j = pd.concat([b, idx], axis=1, join="inner").dropna()
            if len(j) > 63:
                rel = float((j.iloc[-1, 0] / j.iloc[-64, 0]) / (j.iloc[-1, 1] / j.iloc[-64, 1]) - 1)
        out.append({"key": key, "name": name, "n": len(cols), "w1": _r(ret(5)), "m1": _r(ret(21)), "m3": _r(ret(63)),
                    "y1": _r(ret(252)), "ytd": _r(float(b.iloc[-1] / prev_y.iloc[-1] - 1)) if len(prev_y) else None,
                    "rel3": _r(rel), "spark": [_r(v, 3) for v in (b.iloc[-126:] / b.iloc[-126] * 100).tolist()] if len(b) > 126 else []})
    return out


def _monthly_mean(pts: dict) -> pd.Series:
    s = pd.Series(pts, dtype=float)
    if s.empty:
        return s
    s.index = pd.to_datetime(s.index)
    m = s.resample("MS").mean()
    m.index = m.index.strftime("%Y-%m-%d")
    return m


def run(px: pd.DataFrame) -> tuple[dict, dict, str]:
    """Returns ({series id: points}, payload for the site, status message)."""
    cfg = load()
    info = {s: (n, k) for s, n, k in cfg["stocks"]}
    syms = list(info)
    backfill = len(read_series("il_pct200")) < 500
    start = "2013-01-01" if backfill else (today_utc() - dt.timedelta(days=460)).isoformat()
    bars = yf_ohlc(syms, start)
    if not bars or bars["close"].empty:
        raise ValueError("no TASE prices")
    c = bars["close"].dropna(axis=1, how="all")
    missing = [s for s in syms if s not in c.columns or c[s].dropna().empty]
    c = c[[s for s in syms if s not in missing]]
    # a partial newest row (some names not yet updated) would skew the counts
    if len(c) > 2 and c.iloc[-1].notna().sum() < 0.8 * c.iloc[-2].notna().sum():
        c = c.iloc[:-1]
    h = bars["high"].reindex(index=c.index, columns=c.columns)
    lo = bars["low"].reindex(index=c.index, columns=c.columns)
    keep_from = c.index[0] if backfill else c.index[-15]
    out = {}
    # breadth by stock count, as for the S&P 500, but over the names that traded on each day
    b = breadth.compute(c, min_cover=0.7)
    for src, dst, nd in (("sp_pct50", "il_pct50", 1), ("sp_pct200", "il_pct200", 1), ("sp_adr10", "il_adr10", 3),
                         ("sp_hl", "il_hl", 2), ("sp_mco", "il_mco", 1)):
        s = b[src].dropna()
        warm = c.index[min(120, len(c.index) - 1)] if src == "sp_mco" else keep_from
        out[dst] = _pts(s[s.index >= max(keep_from, warm)], nd)
    # trend, risk appetite and foreign-flow proxies
    idx = px[cfg["index"]].dropna() if cfg["index"] in px.columns else None
    ta35 = px[cfg["ta35"]].dropna() if cfg["ta35"] in px.columns else None
    ew = basket(c)
    banks = basket(c[[s for s in c.columns if info[s][1] == "banks"]])
    if idx is not None:
        j = pd.concat([ew, idx], axis=1, join="inner").dropna()
        out["il_ew_rel"] = chain("il_ew_rel", j.iloc[:, 0] / j.iloc[:, 1] / (j.iloc[0, 0] / j.iloc[0, 1]), keep_from)
        j = pd.concat([banks, idx], axis=1, join="inner").dropna()
        out["il_banks_rel"] = chain("il_banks_rel", j.iloc[:, 0] / j.iloc[:, 1] / (j.iloc[0, 0] / j.iloc[0, 1]), keep_from)
    if ta35 is not None:
        out["ta35_ma200"] = _pts((ta35 / ta35.rolling(200).mean() - 1) * 100, 2)
        out["ta35_rv20"] = _pts(np.log(ta35).diff().rolling(20).std() * math.sqrt(252) * 100, 2)
    ext = yf_ohlc([cfg["eis"], cfg["eurils"]], "2013-01-01" if len(read_series("eis_cmf")) < 500 else (today_utc() - dt.timedelta(days=90)).isoformat())
    if ext and cfg["eis"] in ext["close"].columns:
        e = cfg["eis"]
        out["eis_cmf"] = _pts(cmf(ext["high"][e], ext["low"][e], ext["close"][e], ext["volume"][e]), 4)
    if ext and cfg["eurils"] in ext["close"].columns:
        out["eurils"] = _pts(ext["close"][cfg["eurils"]], 4)
    if cfg["eis"] in px.columns and cfg["spy"] in px.columns:
        j = pd.concat([px[cfg["eis"]], px[cfg["spy"]]], axis=1, join="inner").dropna()
        out["eis_rel"] = _pts(j.iloc[:, 0] / j.iloc[:, 1], 5)
    if cfg["usdils"] in px.columns:
        fx = px[cfg["usdils"]].dropna()
        out["usdils"] = _pts(fx, 4)
        out["usdils_dev"] = _pts((fx / fx.rolling(200).mean() - 1) * 100, 2)
        if ta35 is not None:
            j = pd.concat([ta35, fx], axis=1, join="inner").dropna()
            out["ta35_usd"] = _pts(j.iloc[:, 0] / j.iloc[:, 1], 2)
    # macro: FRED / OECD / BIS
    from .macro import fred_series
    errs = []
    for sid, code in cfg["fred"].items():
        try:
            pts = fred_series(code)
            s = pd.Series(pts).sort_index()
            if sid == "il_house":
                s.index = pd.to_datetime(s.index)
                s = (s / s.shift(4) - 1) * 100
                s.index = s.index.strftime("%Y-%m-%d")
                out["il_house_yoy"] = _pts(s, 2, "1995-01-01")
            else:
                out[sid] = _pts(s, 3, "1995-01-01")
        except Exception as e:
            errs.append(f"{sid}: {str(e)[:60]}")
    il10 = {**read_series("il_10y"), **out.get("il_10y", {})}
    us10 = _monthly_mean(read_series("ust10y"))
    if il10 and len(us10):
        a = pd.Series(il10)
        out["il_spread"] = _pts((a - us10.reindex(a.index)).dropna(), 3)
    boi = read_series("boi_rate")
    cpi = read_series("il_cpi_yoy")
    if boi and cpi:
        r = pd.Series(boi).sort_index()
        r.index = pd.to_datetime(r.index)
        rm = r.resample("MS").last().ffill()
        rm.index = rm.index.strftime("%Y-%m-%d")
        cp = pd.Series(cpi)
        out["il_real_rate"] = _pts((rm.reindex(cp.index) - cp).dropna(), 3)
    # payload: stocks and sectors (computed from this run's bars; RS needs the daily range)
    payload = {"asof": c.index[-1], "n": int(c.shape[1]), "missing": missing,
               "stocks": stock_rows(c.iloc[-300:], h.iloc[-300:], lo.iloc[-300:], {s: (info[s][0], info[s][1]) for s in c.columns}),
               "sectors": sector_rows(c.iloc[-300:], info, cfg["sectors"], idx[idx.index >= c.index[-300]] if idx is not None else None),
               "sectorNames": cfg["sectors"]}
    msg = f"{c.shape[1]} מניות{' · השלמת היסטוריה' if backfill else ''}" + (f" · חסרות: {', '.join(m.replace('.TA', '') for m in missing[:10])}" if missing else "") + \
          (f" · {'; '.join(errs)}" if errs else "")
    return out, payload, msg


def finish() -> None:
    """Summation index and the Israeli sentiment composite, recomputed from the stored series."""
    cfg = load()
    mco = read_series("il_mco")
    if mco:
        tot, s = 0.0, {}
        for d in sorted(mco):
            tot += mco[d]
            s[d] = round(tot, 1)
        write_series("il_mcsi", s)
    pols = {x["id"]: x.get("pol", 1) for x in cfg["series"]}
    ser = {}
    for cid in cfg["components"]:
        pts = read_series(cid)
        if pts:
            ser[cid] = pd.Series(pts).sort_index()
    comp = composite(ser, cfg["components"], pols)
    if len(comp):
        write_series("il_sent", {d: round(float(v), 2) for d, v in comp.items()})


def indicator_defs(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load()
    src = {"il_10y": ("FRED · OECD", "https://fred.stlouisfed.org/series/" + cfg["fred"]["il_10y"]),
           "il_unemp": ("FRED · OECD", "https://fred.stlouisfed.org/series/" + cfg["fred"]["il_unemp"]),
           "il_house_yoy": ("FRED · BIS", "https://fred.stlouisfed.org/series/" + cfg["fred"]["il_house"]),
           "il_spread": ("FRED, חישוב", "https://fred.stlouisfed.org/series/" + cfg["fred"]["il_10y"]),
           "il_real_rate": ("בנק ישראל והלמ\"ס, חישוב", "https://www.boi.org.il/"),
           "eis_cmf": ("Yahoo Finance · EIS", "https://www.ishares.com/us/products/239681/"),
           "eis_rel": ("Yahoo Finance", "https://www.ishares.com/us/products/239681/")}
    out = []
    for i, s in enumerate(cfg["series"]):
        sname, surl = src.get(s["id"], ("מחושב ממחירי מניות ת\"א ומדדי ת\"א (Yahoo Finance)", "https://market.tase.co.il/"))
        out.append({"id": s["id"], "order": 950 + i, "group": "il_" + s["sec"], "tab": "israel", "name": s["name"], "short": s.get("short", ""),
                    "freq": s.get("freq", "d"), "pol": s.get("pol", 0), "dec": s.get("dec", 2), "unit": s.get("unit", ""), "pin": False, "comp": False,
                    "auto": True, "src": sname, "srcUrl": surl, "desc": s.get("desc", ""), **({"staleDays": s["stale"]} if s.get("stale") else {}),
                    **({"chg": "pt"} if s.get("unit") == "%" else {})})
    return out


def site_payload() -> dict:
    """Stored Israeli series plus the stock and sector tables, for data/israel.json."""
    cfg = load()
    epoch = dt.date(1970, 1, 1)
    ser = {}
    for s in cfg["series"]:
        pts = read_series(s["id"])
        if not pts:
            continue
        ks = sorted(pts)
        if s.get("freq") == "d" and len(ks) > 900:
            cut = (dt.date.fromisoformat(ks[-1]) - dt.timedelta(days=3 * 365)).isoformat()
            old = pd.Series({k: pts[k] for k in ks if k < cut})
            if len(old):
                keep = set(old.groupby(pd.to_datetime(old.index).to_period("W")).apply(lambda x: x.index[-1]))
                ks = [k for k in ks if k >= cut or k in keep]
        ser[s["id"]] = {"t": [(dt.date.fromisoformat(k) - epoch).days for k in ks], "v": [pts[k] for k in ks]}
    tables = json.loads(DERIVED.read_text(encoding="utf-8")) if DERIVED.exists() else {}
    return {"series": ser, **tables, "components": cfg["components"], "reuse": cfg.get("reuse", {})}
