"""'גרפים - ישראל' (in the analysis tab, next to the technical analyses): a TradingView-style daily chart for every share
listed on the TASE, with the indicators of the house template: Darvas box, SMA 50 and 200, volume, RSI 14 (with its
14-day average) and Chaikin Money Flow 20.

The universe is config/tase_all.json (every share on the TASE, built by tools/ilcharts/build_universe.py). Daily
open/high/low/close/volume come from Yahoo (TASE symbol + ".TA", prices in agorot, as on TradingView) and are kept in
data/prices/tase_*.csv with the TASE symbol as the column. A stock seen for the first time gets its history from
HIST_FROM once; after that every run adds the last few weeks (newest wins), so a live bar from the 11:00 or 16:30 run is
replaced by the final one after the close. Symbols Yahoo does not know are retried once a week (state in DERIVED).

The site gets data/ilc/<symbol>.json (the bars) and data/ilc/index.json (one line per stock: name, sector, flags and
the current indicator values, for the grid's sorting and filters). The page draws the indicators from the bars with the
same formulas as here (sma, rsi, cmf, darvas below); tests/test_ilcharts.py checks that both give the same numbers.

The formulas follow TradingView's, checked on Mizrahi Tefahot against a TradingView screenshot of 27.11.2026 (intraday
bar 20,750): SMA 50 22,464, SMA 21 21,506, RSI 14 40.46 with its average 38.75, CMF 20 -0.06, Darvas box 21,890 / 20,310.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re

import numpy as np
import pandas as pd

from .common import ROOT, today_utc
from .israel import drop_spikes, fix_units
from .markets import _merge_frame, clean_ohl, yf_ohlc

CONFIG = ROOT / "config" / "tase_all.json"
FIELDS = ("open", "high", "low", "close", "volume")
CSV = {f: ROOT / "data" / "prices" / f"tase_{f}.csv" for f in FIELDS}
DERIVED = ROOT / "data" / "derived" / "ilcharts.json"
HIST_FROM = "2022-01-01"     # SMA 200 needs ~10 months before the first bar it is drawn on
RECENT_DAYS = 30             # each run re-downloads this many calendar days (live bars become final, late fixes)
SEND_YEARS = 3.6             # bars per stock file for the site
CHUNK = 80                   # Yahoo symbols per download
RETRY_MISSING_DAYS = 7
# Darvas box: the top is a high not exceeded for TOP_BARS bars; the bottom, the lowest low since the top, holds once the
# next bar does not undercut it (BOTTOM_BARS). A box lasts until a high above its top (up) or a low below its bottom
# (down); the next top is looked for from that bar. Same boxes as TradingView's Darvas Box on the screenshot checked.
TOP_BARS, BOTTOM_BARS = 3, 1


def load() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def file_name(sym: str) -> str:
    """data/ilc/<this>.json; the page builds the same name."""
    return re.sub(r"[^A-Za-z0-9]", "_", sym) + ".json"


# ---------------------------------------------------------------- indicators (the page has the same in JavaScript)

def sma(x: np.ndarray, n: int) -> np.ndarray:
    """Simple average of the last n values; empty while any of them is missing (as ta.sma)."""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        bad = np.isnan(x)
        cs = np.cumsum(np.insert(np.where(bad, 0.0, x), 0, 0.0))
        cb = np.cumsum(np.insert(bad.astype(int), 0, 0))
        out[n - 1:] = np.where(cb[n:] - cb[:-n] == 0, (cs[n:] - cs[:-n]) / n, np.nan)
    return out


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder's average as TradingView's ta.rma: seeded with the simple average of the first n values."""
    out = np.full(len(x), np.nan)
    s, k = None, 0
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        k += 1
        if s is None:
            if k == n:
                s = float(np.mean(x[i - n + 1:i + 1]))
                out[i] = s
        else:
            s = (s * (n - 1) + v) / n
            out[i] = s
    return out


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=np.nan)
    up, dn = rma(np.where(np.isnan(d), np.nan, np.maximum(d, 0)), n), rma(np.where(np.isnan(d), np.nan, np.maximum(-d, 0)), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, 100 - 100 / (1 + up / dn)))
    return np.where(np.isnan(up) | np.isnan(dn), np.nan, r)


def cmf(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray, n: int = 20) -> np.ndarray:
    """TradingView's CMF: sum of ((2C - L - H) / (H - L)) * V over n bars / sum of V (0 for a bar with H = L)."""
    rng = h - l
    with np.errstate(divide="ignore", invalid="ignore"):
        mfm = np.where(rng > 0, (2 * c - l - h) / rng, 0.0)
    vv = np.nan_to_num(v, nan=0.0)
    mfv = mfm * vv
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        a, b = np.cumsum(np.insert(mfv, 0, 0.0)), np.cumsum(np.insert(vv, 0, 0.0))
        num, den = a[n:] - a[:-n], b[n:] - b[:-n]
        with np.errstate(divide="ignore", invalid="ignore"):
            out[n - 1:] = np.where(den > 0, num / den, np.nan)
    return out


def darvas(h: np.ndarray, l: np.ndarray, c: np.ndarray, top_bars: int = TOP_BARS, bottom_bars: int = BOTTOM_BARS) -> list[dict]:
    """Darvas boxes: [{start, end, top, bot, formed, dir}], bar indices; dir 1 = left upwards, -1 = downwards, 0 = still
    open (the last box). start = the bar of the top, end = the last bar inside the box, formed = the bar it was confirmed."""
    n = len(c)
    boxes: list[dict] = []
    if n == 0:
        return boxes
    state, ti, top, bi, bot, box = "top", 0, h[0], 0, l[0], None
    for i in range(1, n):
        if state == "box":
            up, dn = h[i] > box["top"], l[i] < box["bot"]
            if up or dn:
                d = (1 if c[i] >= (box["top"] + box["bot"]) / 2 else -1) if up and dn else (1 if up else -1)
                boxes.append({**box, "end": i - 1, "dir": d})
                box, state, ti, top = None, "top", i, h[i]
            continue
        if state == "top":
            if h[i] > top:
                ti, top = i, h[i]
            elif i - ti >= top_bars:
                seg = l[ti:i + 1]
                bi = ti + int(np.argmin(seg))
                bot = l[bi]
                state = "bot"
                if i - bi >= bottom_bars:
                    box, state = {"start": ti, "top": top, "bot": bot, "formed": i}, "box"
            continue
        # state == "bot": the top holds; find the bottom
        if h[i] > top:
            state, ti, top = "top", i, h[i]
        elif l[i] < bot:
            bi, bot = i, l[i]
        elif i - bi >= bottom_bars:
            box, state = {"start": ti, "top": top, "bot": bot, "formed": i}, "box"
    if box:
        boxes.append({**box, "end": n - 1, "dir": 0})
    return boxes


def bars_frame(ohl: dict[str, pd.DataFrame], sym: str) -> pd.DataFrame:
    """One stock's bars; a day without a usable open/high/low is drawn from the close (as the other charts)."""
    c = ohl["close"][sym].dropna()
    df = pd.DataFrame({"c": c})
    for f, k in (("open", "o"), ("high", "h"), ("low", "l"), ("volume", "v")):
        df[k] = ohl[f][sym].reindex(c.index) if sym in ohl[f].columns else np.nan
    ok = df[["o", "h", "l"]].notna().all(axis=1)
    for k in ("o", "h", "l"):
        df.loc[~ok, k] = df.loc[~ok, "c"]
    return df


def summary(df: pd.DataFrame) -> dict:
    """The current values shown on a stock's card and used by the grid's filters and sorting."""
    c, h, l, v = (df[k].to_numpy(dtype=float) for k in ("c", "h", "l", "v"))
    n = len(c)
    r = lambda x, nd=2: None if x is None or not np.isfinite(x) else round(float(x), nd)
    pct = lambda a, b: None if b is None or not np.isfinite(b) or b == 0 or not np.isfinite(a) else (a / b - 1) * 100
    last = c[-1]
    m50, m200 = sma(c, 50)[-1], sma(c, 200)[-1]
    rs = rsi(c)
    rs_ma = sma(rs, 14)[-1]
    cm = cmf(h, l, c, v)
    boxes = darvas(h, l, c)
    dates = list(df.index)
    year = dates[-1][:4]
    prev_year = [i for i, d in enumerate(dates) if d[:4] < year]
    out = {"d": dates[-1], "c": r(last, 4), "ch": r(pct(last, c[-2]) if n > 1 else None),
           "m1": r(pct(last, c[-22]) if n > 21 else None), "y1": r(pct(last, c[-253]) if n > 252 else None),
           "ytd": r(pct(last, c[prev_year[-1]]) if prev_year else None),
           "a50": r(pct(last, m50)), "a200": r(pct(last, m200)), "rsi": r(rs[-1], 1), "rsiMa": r(rs_ma, 1),
           "cmf": r(cm[-1], 3), "hi52": r(pct(last, float(np.nanmax(h[-252:])))), "bars": n}
    vol = np.nan_to_num(v[-20:], nan=0.0)
    to = float(np.mean(vol * c[-20:] / 100)) if n >= 5 else None      # agorot -> shekels
    out["to"] = r(to / 1e6, 3) if to is not None else None
    if boxes:
        b = boxes[-1]
        brk = next((x for x in reversed(boxes) if x["dir"] != 0), None)
        out["dv"] = {"top": r(b["top"], 4), "bot": r(b["bot"], 4), "open": b["dir"] == 0,
                     # the last time price left a box: direction, the bar, and how many bars ago
                     **({"dir": brk["dir"], "brk": dates[brk["end"] + 1], "ago": n - 2 - brk["end"]} if brk else {})}
    return out


# ---------------------------------------------------------------- storage

def read_ohlc() -> dict[str, pd.DataFrame]:
    out = {}
    for f, p in CSV.items():
        df = pd.read_csv(p, index_col=0) if p.exists() else pd.DataFrame()
        df.index = df.index.astype(str)
        out[f] = df.sort_index()
    return out


def _download(alts: dict[str, list[str]], start: str) -> dict[str, pd.DataFrame]:
    """Bars for {TASE symbol: [Yahoo symbols to try]}, renamed to the TASE symbol (first alternative with data wins)."""
    out = {f: pd.DataFrame() for f in FIELDS}
    todo = dict(alts)
    for k in range(max((len(a) for a in alts.values()), default=0)):
        ask = {a[k]: s for s, a in todo.items() if len(a) > k}
        if not ask:
            break
        ys = list(ask)
        for j in range(0, len(ys), CHUNK):
            part = ys[j:j + CHUNK]
            try:
                bars = yf_ohlc(part, start)
            except Exception as e:        # one bad chunk must not stop the rest
                print(f"ilcharts: download failed for {len(part)} symbols: {e}", flush=True)
                continue
            if not bars or bars["close"].empty:
                continue
            got = [y for y in part if y in bars["close"].columns and bars["close"][y].notna().sum() > 0]
            for f in FIELDS:
                fr = bars.get(f)
                if fr is None:
                    continue
                fr = fr.reindex(columns=got).rename(columns=ask)
                out[f] = _merge_frame(out[f], fr)
            for y in got:
                todo.pop(ask[y], None)
    return out


def run() -> tuple[dict, str]:
    cfg = load()
    entries = {s["sym"]: s["y"].split("|") for s in cfg["stocks"]}
    prev = json.loads(DERIVED.read_text(encoding="utf-8")) if DERIVED.exists() else {}
    missing_prev: dict = prev.get("missing", {})
    today = today_utc()
    cur = read_ohlc()
    have = {s for s in cur["close"].columns if cur["close"][s].notna().any()}
    retry_after = (today - dt.timedelta(days=RETRY_MISSING_DAYS)).isoformat()
    new = {s: a for s, a in entries.items() if s not in have and missing_prev.get(s, "") < retry_after}
    frames = []
    if new:
        full = _download(new, HIST_FROM)
        fix_units(full)
        drop_spikes(full)
        frames.append(full)
    old = {s: a for s, a in entries.items() if s in have}
    if old:
        frames.append(_download(old, (today - dt.timedelta(days=RECENT_DAYS)).isoformat()))
    merged = {}
    for f in FIELDS:
        df = cur[f]
        for fr in frames:
            df = _merge_frame(df, fr.get(f))
        merged[f] = df
    fix_units(merged)
    spikes = drop_spikes(merged)
    keep = [s for s in entries if s in merged["close"].columns]
    close = merged["close"].reindex(columns=keep)
    close = close[close.index >= HIST_FROM].dropna(how="all").sort_index()
    if close.empty:
        raise ValueError("no TASE bars")
    ohl = clean_ohl({f: merged[f] for f in ("open", "high", "low")}, close)
    for f, df in (("close", close), *ohl.items(), ("volume", merged["volume"])):
        df = df.reindex(index=close.index, columns=close.columns).dropna(how="all")
        df.index.name = "date"
        CSV[f].parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(CSV[f], float_format="%.6g")
    got = set(close.columns[close.notna().any()])
    missing = {s: (today.isoformat() if s in new else missing_prev.get(s, today.isoformat())) for s in entries if s not in got}
    last = close.apply(lambda s: s.last_valid_index())
    asof = max(x for x in last if isinstance(x, str))
    stale = sum(1 for s in got if isinstance(last[s], str) and last[s] < (dt.date.fromisoformat(asof) - dt.timedelta(days=14)).isoformat())
    state = {"asof": asof, "n": len(got), "of": len(entries), "missing": missing, "stale": stale}
    DERIVED.parent.mkdir(parents=True, exist_ok=True)
    DERIVED.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    msg = f"{len(got)} מתוך {len(entries)} מניות עד {asof}" + (f", היסטוריה ל-{len(set(new) & got)} חדשות" if new else "") + \
        (f", {len(missing)} בלי נתונים ב-Yahoo" if missing else "") + (f", {stale} בלי מסחר שבועיים" if stale else "") + \
        (f", {spikes} ימים עם ציטוט שגוי הוסרו" if spikes else "")
    return state, msg


# ---------------------------------------------------------------- site payload

def site_files() -> tuple[dict, dict]:
    """({file name: bars}, index) for data/ilc/."""
    cfg = load()
    ohl = read_ohlc()
    if ohl["close"].empty:
        return {}, {}
    state = json.loads(DERIVED.read_text(encoding="utf-8")) if DERIVED.exists() else {}
    epoch = dt.date(1970, 1, 1)
    start = (today_utc() - dt.timedelta(days=int(365.25 * SEND_YEARS))).isoformat()
    num = lambda x: None if x is None or not np.isfinite(x) else float(f"{x:.6g}")
    files, rows = {}, []
    for s in cfg["stocks"]:
        sym = s["sym"]
        row = {"s": sym, "n": s["name"], "e": s["en"], "sec": s["sec"], **{k: s[k] for k in ("t", "f") if k in s}}
        if sym in ohl["close"].columns and ohl["close"][sym].notna().sum() >= 2:
            df = bars_frame(ohl, sym)
            w = df[df.index >= start]
            if len(w) < 2:
                w = df.iloc[-2:]
            row.update(summary(w))      # on the bars the page gets, so the card and the chart show the same values
            rec = {"s": sym, "t": [(dt.date.fromisoformat(d) - epoch).days for d in w.index]}
            for k in ("o", "h", "l", "c"):
                rec[k] = [num(x) for x in w[k].to_numpy(dtype=float)]
            rec["v"] = [None if not np.isfinite(x) else int(x) for x in w["v"].to_numpy(dtype=float)]
            files[file_name(sym)] = rec
            row["file"] = file_name(sym)
        rows.append(row)
    idx = {"asof": state.get("asof") or max((r["d"] for r in rows if r.get("d")), default=None),
           "listAsof": cfg.get("asof"), "sectors": cfg.get("sectors", {}), "n": len(files), "of": len(rows),
           "params": {"darvas": {"topBars": TOP_BARS, "bottomBars": BOTTOM_BARS}, "rsi": 14, "rsiMa": 14, "cmf": 20, "ma": [50, 200]},
           "stocks": rows}
    return files, idx
