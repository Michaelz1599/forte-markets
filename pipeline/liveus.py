"""Today's values of the US sentiment indicators during the session (the live layer of the site).

The stored series hold closing values only (cutoff_date: a US day counts after 21:00 UTC), so during the session
the board would otherwise show yesterday's close. This takes today's value of every indicator that has one intraday:
  - CNN Fear & Greed and its five daily components (CNN recomputes them through the day)
  - VIX, VIX3M (for the term structure), VVIX, SKEW, MOVE and the S&P 500 (Yahoo, today's bar so far)
  - the ratio series RSP/SPY, SPHB/SPLV, XLY/XLP and copper/gold (Yahoo, today's bar so far)
and writes data/derived/live_us.json: {"asof", "date" (US date), "v": {id: value}, "at": {id: time of the value}}.
The page adds these as today's point, in memory only and marked live, while the stored series end before that date;
the night run's closing values then replace them. Weekly and manual series (AAII, NAAIM, NFCI, the TradingView
put/call ratios) and the FRED ones have no intraday value and are not here.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

from . import sources
from .common import ROOT, dump_json, get

OUT = ROOT / "data" / "derived" / "live_us.json"
ET = ZoneInfo("America/New_York")
DIRECT = {"vix": ("^VIX", 2), "vvix": ("^VVIX", 2), "skew": ("^SKEW", 2), "move": ("^MOVE", 2), "spx": ("^GSPC", 2)}
RATIOS = {"rsp_spy": ("RSP", "SPY"), "sphb_splv": ("SPHB", "SPLV"), "xly_xlp": ("XLY", "XLP"), "cu_au": ("HG=F", "GC=F"),
          "vix_ts": ("^VIX", "^VIX3M")}
RANGES = {"vix": (5, 150), "vvix": (40, 300), "skew": (90, 200), "move": (30, 300), "vix_ts": (0.4, 2)}


def _yahoo(today: str) -> dict[str, float]:
    """Last price of today's daily bar (it exists only once the symbol has traded today)."""
    import yfinance as yf
    syms = sorted({s for s, _ in DIRECT.values()} | {s for ab in RATIOS.values() for s in ab})
    raw = yf.download(syms, period="5d", interval="1d", auto_adjust=False, actions=False, progress=False, threads=True)
    if raw is None or raw.empty:
        return {}
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": syms[0]})
    out = {}
    for sym in syms:
        if sym not in close.columns:
            continue
        s = close[sym].dropna()
        if s.empty:
            continue
        d = pd.Timestamp(s.index[-1]).date().isoformat()
        if d == today and float(s.iloc[-1]) > 0:
            out[sym] = float(s.iloc[-1])
    return out


def _cnn(today: str) -> dict[str, tuple[float, str]]:
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=7)).isoformat()
    js = get(sources.CNN_URL.format(start=since), headers=sources.CNN_HEADERS, expect_json=True, tries=2)
    out = {}
    for sid, (key, nd, lo, hi) in sources.CNN_MAP.items():
        pts = (js.get(key) or {}).get("data") or []
        if not pts:
            continue
        p = max(pts, key=lambda q: q["x"])
        t = dt.datetime.fromtimestamp(p["x"] / 1000, dt.timezone.utc)
        if t.astimezone(ET).date().isoformat() != today:
            continue
        v = round(float(p["y"]), nd)
        if lo <= v <= hi:
            out[sid] = (v, t.isoformat(timespec="minutes"))
    fg = js.get("fear_and_greed") or {}
    try:
        t = dt.datetime.fromisoformat(str(fg.get("timestamp")).replace("Z", "+00:00"))
        if fg.get("score") is not None and t.astimezone(ET).date().isoformat() == today:
            out["fg"] = (round(float(fg["score"]), 2), t.astimezone(dt.timezone.utc).isoformat(timespec="minutes"))
    except (TypeError, ValueError):
        pass
    return out


def run() -> tuple[dict, str]:
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ET).date()
    asof = now.isoformat(timespec="minutes")
    payload = {"asof": asof, "date": today.isoformat(), "v": {}, "at": {}, "src": {}}
    errs = []
    if today.weekday() < 5:
        try:
            for sid, (v, t) in _cnn(today.isoformat()).items():
                payload["v"][sid], payload["at"][sid], payload["src"][sid] = v, t, "CNN"
        except Exception as e:
            errs.append(f"CNN: {type(e).__name__} {str(e)[:80]}")
        try:
            px = _yahoo(today.isoformat())
            for sid, (sym, nd) in DIRECT.items():
                if sym in px:
                    payload["v"][sid] = round(px[sym], nd)
            for sid, (a, b) in RATIOS.items():
                if a in px and b in px:
                    payload["v"][sid] = round(px[a] / px[b], 4 if sid == "vix_ts" else 5)
            for sid in list(DIRECT) + list(RATIOS):
                if sid in payload["v"]:
                    lo, hi = RANGES.get(sid, (-1e12, 1e12))
                    if not lo <= payload["v"][sid] <= hi:
                        del payload["v"][sid]
                        continue
                    payload["at"][sid], payload["src"][sid] = asof, "Yahoo"
        except Exception as e:
            errs.append(f"Yahoo: {type(e).__name__} {str(e)[:80]}")
    dump_json(OUT, payload)
    hm = now.astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%H:%M")
    if today.weekday() >= 5:
        msg = "סוף שבוע: אין מסחר בארה\"ב"
    elif not payload["v"]:
        msg = "אין עדיין ערכים של היום (לפני פתיחת המסחר בארה\"ב)"
    else:
        msg = f"{len(payload['v'])} מדדים עם ערך של היום · נכון ל-{hm} שעון ישראל"
    if errs:
        msg += " · " + "; ".join(errs)
        if not payload["v"]:
            raise RuntimeError(msg)
    return payload, msg
