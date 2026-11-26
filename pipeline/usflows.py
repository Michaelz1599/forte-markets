"""Where money flows in the US (the Momentum tab), in two layers, like "where money flows in Tel Aviv" in the Israel tab:

1. Actual: the money that went into and out of State Street's ETFs (SPY, the 11 Select Sector SPDRs, growth and value,
   and industry SPDRs). Each fund publishes its whole daily history of NAV and shares outstanding
   (https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/navhist-us-en-<ticker>.xlsx);
   a day's flow = the change in shares outstanding x NAV, i.e. the creations (+) and redemptions (-) of that day.
2. Estimate: buying and selling pressure in every S&P 500 member, from price and dollar volume, by the method of the
   Israel tab (israel.money_flows with dollars). Computed in the breadth step from the members' bars.

The fund list is in config/usflows.json. The actual layer is kept in data/derived/us_etf_flows.json; a run where SSGA
fails keeps the last good file.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import re

import pandas as pd

from .common import ROOT, UA, get

CFG = ROOT / "config" / "usflows.json"
OUT = ROOT / "data" / "derived" / "us_etf_flows.json"
NAVHIST = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/navhist-us-en-{t}.xlsx"
WINDOWS = (1, 5, 20, 60, 250)     # sessions
KEEP = 400                        # sessions of history used (a year and 13 whole months)
SRC_PAGE = "https://www.ssga.com/us/en/intermediary/etfs"


def load() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8"))


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _date(v) -> str | None:
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    s = str(v or "").strip()
    for fmt, rx in (("%d-%b-%Y", r"^\d{1,2}-[A-Za-z]{3}-\d{4}$"), ("%m/%d/%Y", r"^\d{1,2}/\d{1,2}/\d{4}$"), ("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}")):
        if re.match(rx, s):
            try:
                return dt.datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                return None
    return None


def parse_navhist(raw: bytes, keep: int | None = None) -> pd.DataFrame:
    """SSGA's NAV history workbook: the fund name and ticker, a header row 'Date | NAV | Shares Outstanding |
    Total Net Assets', one row per day (newest first, '24-Nov-2026'), then disclaimer text.
    Returns a date-indexed frame (oldest first) with nav, so (shares outstanding) and tna (dollars).
    keep: stop after that many days when the rows run newest first (the whole history is ~6,000 rows)."""
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    cols = None
    for r in rows:
        if r and str(r[0] or "").strip().lower() == "date":
            cols = [str(x or "").strip().lower() for x in r]
            break
    if cols is None:
        raise ValueError("SSGA NAV history: no header row")

    def col(name):
        i = next((i for i, c in enumerate(cols) if c.startswith(name)), None)
        if i is None:
            raise ValueError(f"SSGA NAV history: no '{name}' column")
        return i
    i_nav, i_so, i_tna = col("nav"), col("shares outstanding"), col("total net assets")
    recs = {}
    for r in rows:
        if not r or len(r) <= max(i_nav, i_so, i_tna):
            continue
        d = _date(r[0])
        if d:
            if keep and len(recs) >= keep and d < min(recs):    # newest first and far enough back
                break
            recs[d] = (_num(r[i_nav]), _num(r[i_so]), _num(r[i_tna]))
    if len(recs) < 30:
        raise ValueError(f"SSGA NAV history: only {len(recs)} days")
    df = pd.DataFrame.from_dict(recs, orient="index", columns=["nav", "so", "tna"]).sort_index()
    return df


def daily_flows(df: pd.DataFrame) -> pd.Series:
    """Dollars created (+) or redeemed (-) each day: (shares_t - k x shares_t-1) x NAV_t. k is the split ratio on the
    day of a share split (the NAV halves and the share count doubles: 5.12.2025 in XLK, XLE, XLU, XLY and XLB), 1 on
    any other day. A NAV move of more than 30% in a day is taken as a split; no fund here has had one otherwise."""
    df = df.dropna(subset=["nav", "so"])
    df = df[(df["nav"] > 0) & (df["so"] > 0)]
    r = df["nav"] / df["nav"].shift(1)
    k = pd.Series(1.0, index=df.index)
    for d in r.index[(r < 0.7) | (r > 1.4)]:
        x = 1 / r[d]
        k[d] = float(round(x)) if x >= 1 else 1 / round(1 / x)
    return ((df["so"] - k * df["so"].shift(1)) * df["nav"]).iloc[1:]


def _r(x, nd=1):
    return None if x is None or not math.isfinite(float(x)) else round(float(x), nd)


def payload(frames: dict[str, pd.DataFrame], cfg: dict) -> dict:
    """Per fund: net flow ($ millions) over the last 1/5/20/60/250 sessions (f), as a share of its assets at the start
    of the window (p) and those assets (b); the daily total of the sector funds and of SPY; each fund by month."""
    flows = {t: daily_flows(df) for t, df in frames.items()}
    days = sorted(set().union(*(set(f.index) for f in flows.values())))[-KEEP:]
    asof = days[-1]
    etfs = []
    for t, grp, name, sec in cfg["etfs"]:
        if t not in flows:
            continue
        f = flows[t].reindex(days)
        tna = frames[t]["tna"].reindex(days).ffill()
        last = flows[t].index[-1]
        row = {"sym": t, "grp": grp, "name": name, "sec": sec, "asof": last,
               "aum": _r(frames[t]["tna"].dropna().iloc[-1] / 1e6, 0) if frames[t]["tna"].notna().any() else None}
        for n in WINDOWS:
            x = f.iloc[-n:]
            s = float(x.sum()) if x.notna().any() else None
            base = tna.iloc[-n - 1] if len(tna) > n else None
            row[f"f{n}"] = _r(s / 1e6) if s is not None else None
            row[f"p{n}"] = _r(s / base, 4) if s is not None and base and base > 0 else None
            row[f"b{n}"] = _r(base / 1e6, 0) if base and base > 0 else None     # assets at the start ($ millions)
        etfs.append(row)
    sec_syms = [t for t, g, *_ in cfg["etfs"] if g == "sector" and t in flows]
    frame = pd.DataFrame({t: flows[t].reindex(days) for t in flows})
    hd = days[-120:]
    sec_daily = frame[sec_syms].loc[hd].sum(axis=1, min_count=max(1, len(sec_syms) - 2)) / 1e6 if sec_syms else None
    hist = {"d": hd, "sec": [_r(x) for x in sec_daily] if sec_daily is not None else [],
            "spy": [_r(x / 1e6) for x in frame["SPY"].loc[hd]] if "SPY" in frame else []}
    # by month: each fund's flow, and as a share of its assets at the end of the month before
    di = pd.to_datetime(pd.Index(days))
    per = di.to_period("M")
    months = sorted(set(per))[-13:]
    mon = {"m": [str(p) for p in months], "etf": {}}
    for t in flows:
        s = frame[t].groupby(per).sum(min_count=1).reindex(months)
        tna = frames[t]["tna"].reindex(days).ffill()
        start = tna.groupby(per).first()             # the assets on the first day of each month (close enough)
        prev = tna.groupby(per).last().shift(1).reindex(months).fillna(start.reindex(months))
        mon["etf"][t] = {"n": [_r(v / 1e6) if pd.notna(v) else None for v in s],
                         "r": [_r(v / b, 4) if pd.notna(v) and pd.notna(b) and b > 0 else None for v, b in zip(s, prev)]}
    return {"asof": asof, "unit": "מיליוני דולר", "windows": list(WINDOWS), "groups": cfg["groups"], "etfs": etfs,
            "hist": hist, "months": mon, "src": NAVHIST.format(t="<ticker>"), "page": SRC_PAGE}


def run() -> tuple[dict, str]:
    """Fetch every fund's NAV history and rebuild the actual layer. Raises (and so keeps the last good file) when SPY
    or more than three funds are missing."""
    cfg = load()
    frames, errs = {}, []
    for t, *_ in cfg["etfs"]:
        if len(errs) > 3:      # SSGA is down or blocking: stop rather than wait on every fund (the job has 45 minutes)
            break
        try:
            r = get(NAVHIST.format(t=t.lower()), headers={"User-Agent": UA}, timeout=45, tries=2)
            frames[t] = parse_navhist(r.content, keep=KEEP + 30).iloc[-KEEP - 30:]
        except Exception as e:
            errs.append(f"{t} ({type(e).__name__})")
    if "SPY" not in frames or len(errs) > 3:
        raise ValueError(f"SSGA: {len(frames)}/{len(cfg['etfs'])} funds · " + ", ".join(errs[:8]))
    out = payload(frames, cfg)
    out["missing"] = [e.split(" ")[0] for e in errs]
    out["fetched"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    lag = [x["sym"] for x in out["etfs"] if x["asof"] < out["asof"]]
    return out, f"{len(frames)}/{len(cfg['etfs'])} קרנות SSGA · עד {out['asof']}" + \
        (f" · חסרות: {', '.join(errs)}" if errs else "") + (f" · מפגרות ביום: {', '.join(lag)}" if lag else "")


def pressure(close: pd.DataFrame, bars: dict, info: dict) -> dict:
    """The estimate layer: buying and selling pressure in every S&P 500 member (dollars), by sector (GICS) and by
    stock, over 5 and 20 sessions, 3 months and a year. info: {symbol: (name, GICS sector)}."""
    from .breadth import SECTOR_HE
    from .israel import money_flows
    c = close.iloc[-340:]
    h = bars["high"].reindex(index=c.index, columns=c.columns)
    lo = bars["low"].reindex(index=c.index, columns=c.columns)
    v = bars["volume"].reindex(index=c.index, columns=c.columns)
    inf = {s: (info.get(s, (s, ""))[0], info.get(s, (s, ""))[1] or "other") for s in c.columns}
    keys = sorted({x[1] for x in inf.values()})
    names = {k: SECTOR_HE.get(k, k if k != "other" else "אחר") for k in keys}
    out = money_flows(c, h, lo, v, inf, names, px_div=1.0, unit="מיליוני דולר", min_names=int(0.8 * c.shape[1]))
    out["sectorNames"] = names
    return out
