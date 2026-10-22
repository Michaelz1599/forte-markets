"""Prices (Yahoo Finance via yfinance) and the Leading Indices / factor analytics."""
from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pandas as pd

from .common import PRICES_CSV, ROOT, cutoff_date, iso, today_utc

UNIVERSE = ROOT / "config" / "universe.json"
BACKFILL_START = "2013-01-01"


def load_universe() -> dict:
    return json.loads(UNIVERSE.read_text(encoding="utf-8"))


def all_symbols(u: dict) -> list[str]:
    seen, out = set(), []
    for g in u["groups"]:
        for it in g["items"]:
            if it["sym"] not in seen:
                seen.add(it["sym"]); out.append(it["sym"])
    for it in u.get("hidden", []):
        if it["sym"] not in seen:
            seen.add(it["sym"]); out.append(it["sym"])
    return out


# --------------------------------------------------------------------------- price store
def read_prices() -> pd.DataFrame:
    if not PRICES_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(PRICES_CSV, index_col=0)
    df.index = df.index.astype(str)
    return df.sort_index()


def write_prices(df: pd.DataFrame) -> None:
    PRICES_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = df.sort_index()
    df.index.name = "date"
    df.to_csv(PRICES_CSV, float_format="%.6g")


def _yf_field(raw: pd.DataFrame, field: str, symbols: list[str]) -> pd.DataFrame:
    f = raw[field] if isinstance(raw.columns, pd.MultiIndex) else raw[[field]].rename(columns={field: symbols[0]})
    idx = pd.to_datetime(f.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    f = f.copy()
    f.index = idx.strftime("%Y-%m-%d")
    f = f.apply(pd.to_numeric, errors="coerce")
    f = f.where(f > 0)
    return f[f.index <= cutoff_date()]


def yf_ohlc(symbols: list[str], start: str) -> dict[str, pd.DataFrame]:
    """Daily close, high and low (split-adjusted, not dividend-adjusted), date-string-indexed."""
    import yfinance as yf
    if not symbols:
        return {}
    raw = yf.download(symbols, start=start, auto_adjust=False, actions=False, progress=False,
                      threads=True, group_by="column", multi_level_index=True, timeout=30)
    if raw is None or raw.empty:
        return {}
    close = _yf_field(raw, "Close", symbols).dropna(how="all")
    out = {"close": close}
    for k, f in (("high", "High"), ("low", "Low"), ("volume", "Volume")):
        try:
            out[k] = _yf_field(raw, f, symbols).reindex(index=close.index, columns=close.columns)
        except KeyError:
            out[k] = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    return out


def cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 20) -> pd.Series:
    """Chaikin Money Flow: the n-day sum of money-flow volume over the n-day sum of volume, -1..+1.
    Money-flow multiplier = ((C - L) - (H - C)) / (H - L): +1 closing at the high, -1 at the low."""
    j = pd.concat([high, low, close, volume], axis=1, keys=["h", "l", "c", "v"]).dropna()
    j = j[(j["v"] > 0) & (j["h"] >= j["l"])]
    rng = (j["h"] - j["l"]).replace(0, np.nan)
    mfm = (((j["c"] - j["l"]) - (j["h"] - j["c"])) / rng).fillna(0.0)
    mfv = mfm * j["v"]
    out = mfv.rolling(n, min_periods=n).sum() / j["v"].rolling(n, min_periods=n).sum()
    return out.dropna()


def yf_close(symbols: list[str], start: str) -> pd.DataFrame:
    """Daily closes (split-adjusted, not dividend-adjusted) as a date-string-indexed frame."""
    return yf_ohlc(symbols, start).get("close", pd.DataFrame())


def etf_ohlc(u: dict, days: int = 150) -> dict[str, pd.DataFrame]:
    """Recent daily bars (with volume) of every instrument in the universe: RS for the ETFs, money flow for all."""
    syms = all_symbols(u)
    return yf_ohlc(syms, (today_utc() - dt.timedelta(days=days)).isoformat())


def cmf_payload(bars: dict[str, pd.DataFrame], n: int = 20) -> dict:
    """Current Chaikin Money Flow of each instrument with real volume, and its value a week earlier."""
    out = {}
    if not bars or "volume" not in bars:
        return out
    for sym in bars["close"].columns:
        v = bars["volume"][sym]
        if v.dropna().gt(0).sum() < n + 5:
            continue          # indices and FX pairs without volume
        s = cmf(bars["high"][sym], bars["low"][sym], bars["close"][sym], v, n)
        if len(s) < 6:
            continue
        out[sym] = {"cmf": _r(s.iloc[-1], 3), "cmf5": _r(s.iloc[-6], 3), "date": s.index[-1]}
    return out


def spy_cmf(cur: dict, sym: str = "SPY") -> dict:
    """Daily Chaikin Money Flow (20) of the S&P 500 (SPY) for the sentiment board, with history."""
    start = "2005-01-01" if len(cur) < 1000 else (dt.date.fromisoformat(max(cur)) - dt.timedelta(days=60)).isoformat()
    b = yf_ohlc([sym], start)
    if not b:
        return {}
    s = cmf(b["high"][sym], b["low"][sym], b["close"][sym], b["volume"][sym])
    return {d: round(float(v), 4) for d, v in s.items()}


def update_prices(u: dict) -> tuple[pd.DataFrame, dict]:
    syms = all_symbols(u)
    cur = read_prices()
    have = [s for s in syms if s in cur.columns and cur[s].notna().sum() > 200]
    new = [s for s in syms if s not in have]
    report = {"incremental": len(have), "backfilled": new, "missing": []}
    frames = []
    if have:
        last = cur[have].dropna(how="all").index.max()
        start = (dt.date.fromisoformat(last) - dt.timedelta(days=12)).isoformat()
        frames.append(yf_close(have, start))
    if new:
        frames.append(yf_close(new, BACKFILL_START))
    out = cur.copy()
    for f in frames:
        if f.empty:
            continue
        out = out.reindex(out.index.union(f.index))
        for c in f.columns:
            if c not in out.columns:
                out[c] = np.nan
            vals = f[c].dropna()
            out.loc[vals.index, c] = vals.values
    # Yahoo quotes the 10-year yield in percent; guard against the old x10 convention.
    if "^TNX" in out.columns and out["^TNX"].dropna().median() > 20:
        out["^TNX"] = out["^TNX"] / 10
    out = out[[c for c in syms if c in out.columns]]
    today = iso(today_utc())
    out = out[out.index <= cutoff_date()]
    for s in syms:
        if s not in out.columns or out[s].dropna().empty:
            report["missing"].append(s)
        else:
            last_s = out[s].dropna().index.max()
            if (dt.date.fromisoformat(today) - dt.date.fromisoformat(last_s)).days > 6:
                report["missing"].append(f"{s} (עד {last_s})")
    write_prices(out)
    return out, report


def spx_long(cur: dict) -> dict:
    """S&P 500 closes back to 1990 for the forward-return studies."""
    start = "1990-01-01" if not cur or min(cur) > "1990-02-01" else (dt.date.fromisoformat(max(cur)) - dt.timedelta(days=12)).isoformat()
    f = yf_close(["^GSPC"], start)
    if f.empty:
        return {}
    s = f.iloc[:, 0].dropna()
    return {d: round(float(v), 2) for d, v in s.items()}


# --------------------------------------------------------------------------- analytics
def _rsi(s: pd.Series, n: int = 14) -> float:
    d = s.diff().dropna()
    if len(d) < n + 1:
        return float("nan")
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up.iloc[-1] / dn.iloc[-1] if dn.iloc[-1] > 0 else float("inf")
    return 100 - 100 / (1 + rs)


def _ret(s: pd.Series, n: int) -> float:
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else float("nan")


def _r(x, nd=4):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def trend_label(last, s50, s200, slope200) -> str:
    if any(v is None or not math.isfinite(v) for v in (last, s50, s200)):
        return "na"
    if last > s50 > s200 and slope200 >= 0:
        return "up"
    if last < s50 < s200 and slope200 <= 0:
        return "down"
    if s50 > s200 and last < s50:
        return "pullback"
    if s50 < s200 and last > s50:
        return "rebound"
    return "mixed"


def metrics(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) < 30:
        return {"n": len(s)}
    last = float(s.iloc[-1])
    sma50 = s.rolling(50).mean()
    sma200 = s.rolling(200).mean()
    s50 = float(sma50.iloc[-1]) if len(s) >= 50 else float("nan")
    s200 = float(sma200.iloc[-1]) if len(s) >= 200 else float("nan")
    slope200 = float(sma200.iloc[-1] / sma200.iloc[-21] - 1) if len(s) >= 221 else float("nan")
    w = s.iloc[-252:]
    hi, lo = float(w.max()), float(w.min())
    prev_year = s[s.index < f"{s.index[-1][:4]}-01-01"]
    lr = np.log(s).diff()
    dist200 = (s / sma200 - 1).dropna()
    d10 = dist200[dist200.index >= (dt.date.fromisoformat(s.index[-1]) - dt.timedelta(days=3653)).isoformat()]
    cur_d = float(dist200.iloc[-1]) if len(dist200) else float("nan")
    pct_d = float((d10 < cur_d).mean() * 100 + (d10 == cur_d).mean() * 50) if len(d10) > 250 else None
    return {
        "n": len(s), "last": _r(last, 6), "date": s.index[-1], "prev": _r(s.iloc[-2], 6),
        "d1": _r(last / float(s.iloc[-2]) - 1), "w1": _r(_ret(s, 5)), "m1": _r(_ret(s, 21)), "m3": _r(_ret(s, 63)),
        "m6": _r(_ret(s, 126)), "y1": _r(_ret(s, 252)),
        "mom121": _r(float(s.iloc[-22] / s.iloc[-253] - 1)) if len(s) > 253 else None,
        "ytd": _r(last / float(prev_year.iloc[-1]) - 1) if len(prev_year) else None,
        "ma50": _r(last / s50 - 1) if math.isfinite(s50) else None,
        "ma200": _r(last / s200 - 1) if math.isfinite(s200) else None,
        "slope200": _r(slope200),
        "rsi": _r(_rsi(s.iloc[-300:]), 1),
        "dd52": _r(last / hi - 1), "pos52": _r((last - lo) / (hi - lo) * 100 if hi > lo else None, 1),
        "hi52": _r(hi, 6), "lo52": _r(lo, 6),
        "vol20": _r(float(lr.iloc[-20:].std() * math.sqrt(252)), 4),
        "trend": trend_label(last, s50, s200, slope200 if math.isfinite(slope200) else 0),
        "pctD200": _r(pct_d, 1),
        "spark": [_r(v, 6) for v in s.iloc[-126:].tolist()],
    }


def relative(s: pd.Series, b: pd.Series) -> dict:
    """Performance of s against benchmark b, and rotation-chart coordinates."""
    j = pd.concat([s, b], axis=1, join="inner").dropna()
    if len(j) < 130:
        return {}
    a, bb = j.iloc[:, 0], j.iloc[:, 1]
    ex = {}
    for k, n in (("m1", 21), ("m3", 63), ("m6", 126), ("y1", 252)):
        if len(j) > n:
            ex[k] = _r((a.iloc[-1] / a.iloc[-1 - n]) / (bb.iloc[-1] / bb.iloc[-1 - n]) - 1)
    ratio = a / bb
    x = 100 * ratio / ratio.rolling(63).mean()
    y = 100 * x / x.shift(10)
    tail = []
    for k in range(25, -1, -5):  # weekly points over the last 5 weeks, oldest first
        i = len(x) - 1 - k
        if i >= 0 and math.isfinite(x.iloc[i]) and math.isfinite(y.iloc[i]):
            tail.append([_r(x.iloc[i], 2), _r(y.iloc[i], 2), x.index[i]])
    rs = ratio.iloc[-126:]
    vals = [v for v in (ex.get("m3"), ex.get("m6"), ex.get("y1")) if v is not None]
    rs_ma50 = ratio.rolling(50).mean()
    return {
        "ex": ex,
        "score": _r(sum(vals) / len(vals)) if vals else None,
        "rsUp": bool(ratio.iloc[-1] > rs_ma50.iloc[-1]) if math.isfinite(rs_ma50.iloc[-1]) else None,
        "rrg": tail,
        "rsSpark": [_r(v / rs.iloc[0] * 100, 3) for v in rs.tolist()],
    }


def corr_matrix(px: pd.DataFrame, syms: list[str], n: int = 63) -> dict:
    cols = [s for s in syms if s in px.columns]
    r = px[cols].dropna(how="all").pct_change(fill_method=None).iloc[-n:]
    r = r.dropna(axis=1, thresh=int(n * 0.8))
    c = r.corr(min_periods=int(n * 0.6))
    return {"syms": list(c.columns), "m": [[_r(v, 2) for v in row] for row in c.values.tolist()], "n": n,
            "from": r.index[0] if len(r) else None, "to": r.index[-1] if len(r) else None}


def avg_corr_series(px: pd.DataFrame, syms: list[str], n: int = 63, step: int = 5, years: int = 8) -> dict:
    cols = [s for s in syms if s in px.columns]
    r = px[cols].dropna(how="all").pct_change(fill_method=None)
    start = (today_utc() - dt.timedelta(days=365 * years)).isoformat()
    idx = [i for i in range(n, len(r)) if r.index[i] >= start]
    idx = idx[::-1][::step][::-1]
    d, v = [], []
    for i in idx:
        w = r.iloc[i - n + 1:i + 1].dropna(axis=1, thresh=int(n * 0.8))
        if w.shape[1] < 4:
            continue
        c = w.corr().values
        k = c.shape[0]
        avg = (c.sum() - k) / (k * k - k)
        if math.isfinite(avg):
            d.append(r.index[i]); v.append(_r(avg, 3))
    return {"d": d, "v": v}


def build_markets(px: pd.DataFrame, u: dict) -> dict:
    bench = px[u["benchmark"]].dropna() if u["benchmark"] in px.columns else None
    items, groups = {}, []
    for g in u["groups"]:
        groups.append({"id": g["id"], "name": g["name"], "kind": g["kind"], "items": [it["sym"] for it in g["items"]],
                       "core": [it["sym"] for it in g["items"] if it.get("core")]})
        for it in g["items"]:
            sym = it["sym"]
            if sym in items:
                items[sym]["groups"].append(g["id"])
                continue
            rec = {"sym": sym, "name": it["name"], "groups": [g["id"]],
                   **{k: it[k] for k in ("desc", "note", "ta", "unit", "yield") if k in it}}
            if sym in px.columns:
                rec.update(metrics(px[sym]))
                if it.get("yield") and rec.get("last") is not None:
                    ys = px[sym].dropna()
                    for k, n in (("d1", 1), ("w1", 5), ("m1", 21), ("m3", 63), ("m6", 126), ("y1", 252)):
                        rec[k] = _r(float(ys.iloc[-1] - ys.iloc[-1 - n]), 3) if len(ys) > n else None
                    prev_y = ys[ys.index < f"{ys.index[-1][:4]}-01-01"]
                    rec["ytd"] = _r(float(ys.iloc[-1] - prev_y.iloc[-1]), 3) if len(prev_y) else None
                    rec["chgMode"] = "pp"
                if g["kind"] == "factor" and bench is not None:
                    rec.update(relative(px[sym], bench))
            items[sym] = rec
    def core(gid):
        its = [it for g in u["groups"] if g["id"] == gid for it in g["items"]]
        c = [it["sym"] for it in its if it.get("core")]
        return c if c else [it["sym"] for it in its]
    sec_all = [it["sym"] for g in u["groups"] if g["id"] == "sectors" for it in g["items"]]
    spdr = [s for s in sec_all if s.startswith("XL")]
    lead = [s for g in u["groups"] if g["kind"] == "index" and g["id"] in ("us", "il", "eu", "asia", "am")
            for s in [it["sym"] for it in g["items"]] if s in items and items[s].get("ma200") is not None]
    above = [s for s in lead if items[s]["ma200"] > 0]
    return {
        "asof": max((it.get("date") or "") for it in items.values()),
        "groups": groups, "items": items,
        "corr": {"factors": corr_matrix(px, core("factors") + [u["benchmark"]]), "sectors": corr_matrix(px, core("sectors")),
                 "themes": corr_matrix(px, core("themes") + [u["benchmark"]])},
        "avgCorr": avg_corr_series(px, spdr),
        "breadth": {"n": len(lead), "above200": len(above), "up": sum(1 for s in lead if items[s].get("trend") == "up"),
                    "down": sum(1 for s in lead if items[s].get("trend") == "down")},
    }


def prices_payload(px: pd.DataFrame, years: int = 10) -> dict:
    start = (today_utc() - dt.timedelta(days=int(365.25 * years))).isoformat()
    out = {}
    for c in px.columns:
        s = px.loc[px.index >= start, c].dropna()
        if len(s) < 2:
            continue
        out[c] = {"t": [int((dt.date.fromisoformat(d) - dt.date(1970, 1, 1)).days) for d in s.index],
                  "v": [float(f"{v:.6g}") for v in s.values]}
    return out


def ratio_series(px: pd.DataFrame, a: str, b: str, nd: int = 5) -> dict:
    if a not in px.columns or b not in px.columns:
        return {}
    j = pd.concat([px[a], px[b]], axis=1, join="inner").dropna()
    return {d: round(float(x / y), nd) for d, x, y in zip(j.index, j.iloc[:, 0], j.iloc[:, 1]) if y > 0}


def column(px: pd.DataFrame, sym: str, nd: int = 4) -> dict:
    if sym not in px.columns:
        return {}
    s = px[sym].dropna()
    return {d: round(float(v), nd) for d, v in s.items()}


TICKER = ["^GSPC", "^NDX", "^DJI", "^RUT", "^VIX", "TA35.TA", "^TA125.TA", "^STOXX50E", "^GDAXI", "^FTSE", "^N225", "^HSI",
          "^TNX", "DX-Y.NYB", "ILS=X", "EURUSD=X", "GC=F", "CL=F", "HG=F", "BTC-USD"]
TICKER_NAMES = {"^VIX": "VIX", "^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^DJI": "Dow Jones", "^RUT": "Russell 2000",
                "^TNX": "אג\"ח 10 שנים", "ILS=X": "דולר/שקל", "BTC-USD": "ביטקוין"}


def ticker_payload(px: pd.DataFrame, u: dict) -> dict:
    """The scrolling quote strip under the header: last close and daily change."""
    names = {it["sym"]: it for g in u["groups"] for it in g["items"]}
    names.update({it["sym"]: it for it in u.get("hidden", []) if it["sym"] not in names})
    out = []
    for sym in TICKER:
        if sym not in px.columns:
            continue
        s = px[sym].dropna()
        if len(s) < 2:
            continue
        it = names.get(sym, {})
        is_y = bool(it.get("yield"))
        d1 = float(s.iloc[-1] - s.iloc[-2]) if is_y else float(s.iloc[-1] / s.iloc[-2] - 1)
        out.append({"sym": sym, "name": TICKER_NAMES.get(sym, it.get("name", sym)), "last": _r(s.iloc[-1], 6), "d1": _r(d1, 5),
                    "date": s.index[-1], "mode": "pp" if is_y else "pct", "unit": it.get("unit", ""),
                    "neutral": sym in ("ILS=X", "DX-Y.NYB", "EURUSD=X", "^VIX")})
    return {"items": out}
