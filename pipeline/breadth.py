"""Market breadth computed from the daily closes of the current S&P 500 members."""
from __future__ import annotations

import datetime as dt
import io

import numpy as np
import pandas as pd

from .common import get, read_series, today_utc
from .markets import yf_close

CONSTITUENTS = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def members() -> tuple[list[str], str]:
    try:
        df = pd.read_csv(io.StringIO(get(CONSTITUENTS).text))
        syms = df["Symbol"].astype(str).str.strip().tolist()
        src = "datasets/s-and-p-500-companies"
    except Exception:
        html = get(WIKI).text
        df = pd.read_html(io.StringIO(html))[0]
        syms = df["Symbol"].astype(str).str.strip().tolist()
        src = "Wikipedia"
    syms = sorted({s.replace(".", "-") for s in syms if s and s != "nan"})
    if not 480 <= len(syms) <= 520:
        raise ValueError(f"S&P 500 member list has {len(syms)} names")
    return syms, src


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
    return out


def run() -> tuple[dict, str]:
    syms, src = members()
    have = read_series("sp_pct200")
    backfill = len(have) < 500
    start = (today_utc() - dt.timedelta(days=int(365.25 * 6.5) if backfill else 440)).isoformat()
    close = yf_close(syms, start)
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
    nd = {"sp_adr10": 3, "sp_pct50": 1, "sp_pct200": 1, "sp_hl": 2, "sp_mco": 1}
    for sid, s in series.items():
        s = s.dropna()
        s = s[s.index >= max(keep_from, warm if sid == "sp_mco" else keep_from)]
        out[sid] = {d: round(float(v), nd[sid]) for d, v in s.items()}
    return out, f"{got} מניות ({src}){' · השלמת היסטוריה' if backfill else ''}"
