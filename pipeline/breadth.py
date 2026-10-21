"""Market breadth computed from the daily closes of the current S&P 500 members."""
from __future__ import annotations

import datetime as dt
import io

import numpy as np
import pandas as pd

from .common import get, read_series, today_utc
from .markets import yf_ohlc

CONSTITUENTS = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def members() -> tuple[list[str], str, dict]:
    """Current S&P 500 members as Yahoo symbols, the source name, and {symbol: (name, sector)}."""
    try:
        df = pd.read_csv(io.StringIO(get(CONSTITUENTS).text))
        src = "datasets/s-and-p-500-companies"
    except Exception:
        df = pd.read_html(io.StringIO(get(WIKI).text))[0]
        src = "Wikipedia"
    name_col = next((c for c in ("Security", "Name") if c in df.columns), None)
    sec_col = next((c for c in ("GICS Sector", "Sector") if c in df.columns), None)
    info = {}
    for _, r in df.iterrows():
        sym = str(r["Symbol"]).strip().replace(".", "-")
        if sym and sym != "nan":
            info[sym] = (str(r[name_col]) if name_col else sym, str(r[sec_col]) if sec_col else "")
    syms = sorted(info)
    if not 480 <= len(syms) <= 520:
        raise ValueError(f"S&P 500 member list has {len(syms)} names")
    return syms, src, info


SECTOR_HE = {
    "Information Technology": "טכנולוגיה", "Communication Services": "תקשורת", "Consumer Discretionary": "צריכה מחזורית",
    "Consumer Staples": "צריכה בסיסית", "Financials": "פיננסים", "Health Care": "בריאות", "Industrials": "תעשייה",
    "Energy": "אנרגיה", "Materials": "חומרים", "Utilities": "תשתיות", "Real Estate": "נדל\"ן",
}


def stock_momentum(close: pd.DataFrame, info: dict) -> dict:
    """Leaders and laggards by 12-1 momentum, and where the momentum is concentrated by sector."""
    c = close.sort_index()
    if len(c) < 260:
        return {}
    last = c.iloc[-1]
    def ret(n):
        return last / c.iloc[-1 - n] - 1
    mom = c.iloc[-22] / c.iloc[-253] - 1
    hi = c.iloc[-252:].max()
    sma200 = c.iloc[-200:].mean()
    df = pd.DataFrame({"m1": ret(21), "m3": ret(63), "m6": ret(126), "y1": ret(252), "mom": mom,
                       "dd52": last / hi - 1, "ma200": last / sma200 - 1, "last": last}).dropna(subset=["mom", "last"])
    df["sector"] = [SECTOR_HE.get(info.get(s, ("", ""))[1], info.get(s, ("", ""))[1]) for s in df.index]
    df["name"] = [info.get(s, (s, ""))[0] for s in df.index]
    df = df.sort_values("mom", ascending=False)

    def rows(d):
        return [{"sym": s, "name": r["name"], "sector": r["sector"], **{k: (None if pd.isna(r[k]) else round(float(r[k]), 4))
                 for k in ("m1", "m3", "m6", "y1", "mom", "dd52", "ma200")}, "last": round(float(r["last"]), 2)} for s, r in d.iterrows()]
    n = len(df)
    top50 = df.head(50)
    sectors = []
    for sec, g in df.groupby("sector"):
        sectors.append({"sector": sec, "n": int(len(g)), "inTop50": int((top50["sector"] == sec).sum()),
                        "median": round(float(g["mom"].median()), 4), "pos": round(float((g["mom"] > 0).mean() * 100), 1)})
    sectors.sort(key=lambda x: -x["median"])
    dec = max(1, n // 10)
    return {"asof": c.index[-1], "n": n, "pctPos": round(float((df["mom"] > 0).mean() * 100), 1),
            "medianMom": round(float(df["mom"].median()), 4),
            "spread": round(float(df["mom"].head(dec).median() - df["mom"].tail(dec).median()), 4),
            "leaders": rows(df.head(30)), "laggards": rows(df.tail(15).iloc[::-1]), "sectors": sectors}


def compute(close: pd.DataFrame, min_cover: float = 0.9) -> dict[str, pd.Series]:
    close = close.sort_index()
    n_names = close.shape[1]
    ret = close.pct_change(fill_method=None)
    adv = (ret > 0).sum(axis=1).astype(float)
    dec = (ret < 0).sum(axis=1).astype(float)
    cover = ret.notna().sum(axis=1)
    ok = cover >= min_cover * n_names
    out = {}
    out["sp_adr10"] = (adv.rolling(10).sum() / dec.rolling(10).sum().replace(0, np.nan)).where(ok)
    for n, sid in ((50, "sp_pct50"), (200, "sp_pct200")):
        sma = close.rolling(n, min_periods=n).mean()
        valid = close.notna() & sma.notna()
        nvalid = valid.sum(axis=1).astype(float)
        pct = ((close > sma) & valid).sum(axis=1).astype(float) / nvalid.replace(0, np.nan) * 100
        out[sid] = pct.where(nvalid >= min_cover * n_names)
    hi = close.rolling(252, min_periods=252).max()
    lo = close.rolling(252, min_periods=252).min()
    valid = close.notna() & hi.notna()
    nvalid = valid.sum(axis=1).astype(float)
    nh = ((close >= hi) & valid).sum(axis=1).astype(float)
    nl = ((close <= lo) & valid).sum(axis=1).astype(float)
    out["sp_hl"] = ((nh - nl) / nvalid.replace(0, np.nan) * 100).where(nvalid >= min_cover * n_names)
    rana = ((adv - dec) / (adv + dec).replace(0, np.nan) * 1000).where(ok)
    out["sp_mco"] = rana.ewm(span=19, adjust=False).mean() - rana.ewm(span=39, adjust=False).mean()
    out["sp_mco"] = out["sp_mco"].where(ok)
    mom = close.shift(21) / close.shift(252) - 1
    vm = mom.notna()
    nvm = vm.sum(axis=1).astype(float)
    out["sp_mom12"] = ((mom > 0) & vm).sum(axis=1).astype(float) / nvm.replace(0, np.nan) * 100
    out["sp_mom12"] = out["sp_mom12"].where(nvm >= min_cover * n_names)
    return out


def run() -> tuple[dict, str, dict, dict]:
    """Breadth series, a status message, the 12-1 momentum payload, and the members' bars for the RS step."""
    syms, src, info = members()
    have = [read_series(sid) for sid in ("sp_pct200", "sp_mom12")]
    backfill = min(len(h) for h in have) < 500
    start = (today_utc() - dt.timedelta(days=int(365.25 * 6.5) if backfill else 440)).isoformat()
    bars = yf_ohlc(syms, start)
    close = bars.get("close", pd.DataFrame())
    if close.empty:
        raise ValueError("no prices for S&P 500 members")
    last = close.index.max()
    got = int(close.loc[last].notna().sum())
    if got < 0.9 * len(syms):
        # the newest row is often a partial day for a few names; drop it rather than skew the counts
        close = close[close.index < last]
        last = close.index.max()
        got = int(close.loc[last].notna().sum())
        if got < 0.9 * len(syms):
            raise ValueError(f"only {got}/{len(syms)} members have a close on {last}")
    series = compute(close)
    keep_from = close.index[0] if backfill else close.index[-10]
    # the McClellan EMAs need warm-up; skip the first 120 rows of any fetch
    warm = close.index[min(120, len(close.index) - 1)]
    out = {}
    nd = {"sp_adr10": 3, "sp_pct50": 1, "sp_pct200": 1, "sp_hl": 2, "sp_mco": 1, "sp_mom12": 1}
    for sid, s in series.items():
        s = s.dropna()
        s = s[s.index >= max(keep_from, warm if sid == "sp_mco" else keep_from)]
        out[sid] = {d: round(float(v), nd[sid]) for d, v in s.items()}
    recent = close.index[-40:]
    extra = {"members": info, "bars": {k: v.reindex(index=recent) for k, v in bars.items()}}
    return out, f"{got} מניות ({src}){' · השלמת היסטוריה' if backfill else ''}", stock_momentum(close.iloc[-300:], info), extra
