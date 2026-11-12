"""Market value of stocks relative to GDP (the "Buffett Indicator"), US and Israel.

Monthly points (the last trading day of each month) plus today's reading, in %. The whole series is recomputed on
every run and replaces the stored file: the current month's point moves with the market, and history is restated
when GDP is revised or a new year-end market value is published.

US
  Wilshire 5000 Full Cap (Yahoo ^W5000) / nominal GDP (FRED GDP, annual rate, $bn) x 100. One index point is about
  $1bn of market value, the convention GuruFocus and others use. Each month is divided by the GDP of its own quarter,
  or by the last published quarter while the month's quarter is not out yet.
  Before 1989 (no Wilshire history on Yahoo): the Federal Reserve's market value of nonfinancial corporate equities
  (Z.1, FRED NCBEILQ027S) / GDP, rescaled to the Wilshire level over 1989-1993 and interpolated between quarter ends.

Israel
  Market value of the domestic companies listed in Tel Aviv at each year end (World Bank / WFE, CM.MKT.LCAP.CD,
  in dollars, converted at the Bank of Israel year-end representative rate). Between two year ends the value moves
  with the TA-125 index, and the gap between the index and the published year-end values is spread evenly over
  the months; after the last published year end it moves with the TA-125 alone (IPOs and delistings are caught
  only when the next year end is published). WFE counts domestic companies only, so dual-listed foreign companies
  (Palo Alto Networks, listed in Tel Aviv since 23.2.2026 and worth about NIS 1 trillion) are outside the anchors;
  they reach the series only through their capped weight in the TA-125 (Palo Alto since 8.2026).
  GDP: the last four quarters of nominal GDP (Bank of Israel, CBS data, CHAINED_GDP_Q_N, NIS millions).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math

import pandas as pd

from .common import ROOT, dump_json, get, read_series, today_utc

CACHE = ROOT / "data" / "derived" / "buffett_src.json"
US_FROM = "1970-01"      # first month of the US series (Z.1 splice before 1989)
SPLICE = ("1989-01-01", "1993-10-01")   # quarters (FRED dates) over which Z.1 is rescaled to Wilshire
IL_FROM_YEAR = 1993      # first year-end anchor for Israel (TA-125 history starts 10.1992)
REFRESH_H = 20           # refetch each source at most about once a day (the pipeline runs several times a day)
BOI = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS"
US_RANGE, IL_RANGE = (30, 400), (10, 300)   # plausible ranges of the latest reading, %


# --------------------------------------------------------------------------- fetch (with a cache)
def _fred(code: str) -> dict[str, float]:
    from .sources import _fred_csv
    out = {}
    for row in list(csv.reader(io.StringIO(_fred_csv(code).text)))[1:]:
        try:
            out[row[0][:10]] = float(row[1])
        except (IndexError, ValueError):
            continue
    if len(out) < 100:
        raise ValueError(f"FRED {code}: {len(out)} rows")
    return out


def _boi(flow: str, key: str, start: str) -> dict[str, float]:
    r = get(f"{BOI}/{flow}/1.0/{key}", params={"startperiod": start, "format": "csv"}, timeout=60, tries=2)
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        d, v = str(row.get("TIME_PERIOD") or ""), row.get("OBS_VALUE")
        if len(d) == 7 and d[4:6] == "-Q":        # 2026-Q2 -> 2026-04-01 (FRED's convention: the quarter's first day)
            d = f"{d[:4]}-{(int(d[6]) - 1) * 3 + 1:02d}-01"
        try:
            out[d[:10]] = float(v)
        except (TypeError, ValueError):
            continue
    if len(out) < 40:
        raise ValueError(f"BOI {flow}/{key}: {len(out)} rows")
    return out


def _year_ends(daily: dict[str, float]) -> dict[str, float]:
    s = pd.Series(daily).sort_index()
    s.index = pd.to_datetime(s.index)
    ye = s.groupby(s.index.year).last()
    last = s.index[-1]
    return {str(y): float(v) for y, v in ye.items() if y < last.year or (last.month == 12 and last.day >= 28)}


def _wb_cap() -> dict[str, float]:
    js = get("https://api.worldbank.org/v2/country/ISR/indicator/CM.MKT.LCAP.CD", params={"format": "json", "per_page": 200},
             timeout=60, tries=4, expect_json=True)
    rows = js[1] if isinstance(js, list) and len(js) > 1 and js[1] else []
    out = {str(x["date"]): float(x["value"]) for x in rows if x.get("value") is not None}
    if len(out) < 20:
        raise ValueError(f"World Bank: {len(out)} years")
    return out


def _yf_monthly(sym: str, start: str) -> dict[str, float]:
    import yfinance as yf
    raw = yf.download(sym, start=start, interval="1mo", auto_adjust=False, actions=False, progress=False, threads=False)
    c = raw["Close"].dropna()
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    out = {d.strftime("%Y-%m-01"): round(float(v), 4) for d, v in c.items()}
    if len(out) < 100:
        raise ValueError(f"Yahoo {sym} monthly: {len(out)} months")
    return out


SOURCES = {   # cache key: (fetch, label)
    "us_gdp": (lambda: _fred("GDP"), "FRED GDP"),
    "us_z1": (lambda: _fred("NCBEILQ027S"), "FRED NCBEILQ027S"),
    "w5000_m": (lambda: _yf_monthly("^W5000", "1985-01-01"), "Yahoo ^W5000"),
    "ta125_m": (lambda: _yf_monthly("^TA125.TA", "1992-01-01"), "Yahoo ^TA125.TA"),
    "il_gdp": (lambda: _boi("NA", "CHAINED_GDP_Q_N", "1990-01-01"), "בנק ישראל CHAINED_GDP_Q_N"),
    "il_fx_ye": (lambda: _year_ends(_boi("EXR", "RER_USD_ILS", "1990-01-01")), "בנק ישראל RER_USD_ILS"),
    "il_cap": (_wb_cap, "World Bank CM.MKT.LCAP.CD"),
}


def load_inputs(offline: bool = False) -> tuple[dict, list[str]]:
    """Cached inputs, refreshed from the network when older than REFRESH_H hours. Returns (inputs, problems)."""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    data, fetched = cache.get("data", {}), cache.get("fetched", {})
    now = dt.datetime.now(dt.timezone.utc)
    problems, changed = [], False
    for key, (fn, label) in SOURCES.items():
        age = (now - dt.datetime.fromisoformat(fetched[key])).total_seconds() / 3600 if key in fetched else 1e9
        if offline or age < REFRESH_H:
            continue
        try:
            got = fn()
            data[key], fetched[key], changed = got, now.isoformat(timespec="seconds"), True
        except Exception as e:
            problems.append(f"{label}: {type(e).__name__} {str(e)[:70]}" + (" (נתונים שמורים)" if key in data else ""))
    if changed:
        dump_json(CACHE, {"_comment": "Inputs of pipeline/valuation.py (Buffett indicator), cached so a failed source keeps the last good data.",
                          "fetched": fetched, "data": data})
    return data, problems


# --------------------------------------------------------------------------- helpers
def _qstart(d: str) -> str:
    """Date -> the first day of its quarter, FRED style (2026-05-20 -> 2026-04-01)."""
    y, m = int(d[:4]), int(d[5:7])
    return f"{y}-{(m - 1) // 3 * 3 + 1:02d}-01"


def _bme(ym: str) -> str:
    """'2026-03' -> the month's last business day, '2026-03-31'."""
    return pd.offsets.BMonthEnd().rollforward(pd.Timestamp(ym + "-01")).strftime("%Y-%m-%d")


def month_ends(daily: pd.Series | None, monthly: dict[str, float] | None) -> pd.Series:
    """Month-end values indexed by date: the last daily close of each month where daily data exist, Yahoo's monthly
    closes (dated the month's last business day) before that. The current month ends at the latest daily close."""
    out = {}
    first_daily = None
    if daily is not None and len(daily):
        d = daily.dropna().sort_index()
        d.index = d.index.astype(str)
        grp = pd.Series(d.values, index=d.index).groupby(d.index.str[:7])
        for ym, g in grp:
            out[g.index[-1]] = float(g.iloc[-1])
        first_daily = d.index[0][:7]
    this_month = today_utc().isoformat()[:7]
    for k, v in sorted((monthly or {}).items()):
        if (first_daily and k[:7] >= first_daily) or k[:7] >= this_month:   # Yahoo's bar for the current month is partial
            continue
        out[_bme(k[:7])] = float(v)
    return pd.Series(out, dtype=float).sort_index()


def _gdp_for(gdp: dict[str, float], d: str) -> float | None:
    """GDP of the date's own quarter, or the latest published quarter if that one is not out yet."""
    q = _qstart(d)
    if q in gdp:
        return gdp[q]
    past = [k for k in gdp if k <= q]
    return gdp[max(past)] if past else None


def _loglin(points: dict[str, float], months: list[str]) -> dict[str, float]:
    """Log-linear interpolation of month-end values between the given dates (both sorted, 'YYYY-MM-DD')."""
    ks = sorted(points)
    pos = {k: pd.Period(k[:7], "M").ordinal for k in ks}
    out = {}
    for d in months:
        o = pd.Period(d[:7], "M").ordinal
        lo = max((k for k in ks if pos[k] <= o), default=None)
        hi = min((k for k in ks if pos[k] >= o), default=None)
        if lo is None or hi is None:
            continue
        if lo == hi:
            out[d] = points[lo]
            continue
        f = (o - pos[lo]) / (pos[hi] - pos[lo])
        out[d] = math.exp(math.log(points[lo]) * (1 - f) + math.log(points[hi]) * f)
    return out


# --------------------------------------------------------------------------- US
def us_series(inp: dict, w_daily: pd.Series | None) -> dict[str, float]:
    gdp = inp.get("us_gdp") or {}
    if not gdp:
        raise ValueError("no US GDP")
    w = month_ends(w_daily, inp.get("w5000_m"))
    if w.empty:
        raise ValueError("no Wilshire 5000")
    out = {}
    for d, v in w.items():
        g = _gdp_for(gdp, d)
        if g:
            out[d] = v / g * 100
    # before Wilshire: Z.1 nonfinancial corporate equities, rescaled to the Wilshire level
    z1 = inp.get("us_z1") or {}
    first_w = min(w.index)
    if z1:
        qend = lambda q: _bme(f"{q[:4]}-{int(q[5:7]) + 2:02d}")      # 1989-01-01 (Q1) -> 1989-03-31
        k = [w[qend(q)] / (z1[q] / 1000) for q in z1 if SPLICE[0] <= q <= SPLICE[1] and qend(q) in w.index and z1[q] > 0]
        if len(k) >= 8:
            scale = sum(k) / len(k)
            anchors = {qend(q): z1[q] / 1000 * scale / gdp[q] * 100 for q in z1 if q in gdp and qend(q) < first_w and q >= "1969-10-01"}
            months = [_bme(str(p)) for p in pd.period_range(US_FROM, first_w[:7], freq="M")[:-1]]
            out.update({d: v for d, v in _loglin(anchors, months).items() if d < first_w})
    return {d: round(float(v), 2) for d, v in sorted(out.items())}


# --------------------------------------------------------------------------- Israel
def il_series(inp: dict, ta_daily: pd.Series | None) -> dict[str, float]:
    gq, cap, fx = inp.get("il_gdp") or {}, inp.get("il_cap") or {}, inp.get("il_fx_ye") or {}
    if not (gq and cap and fx):
        raise ValueError("missing Israeli inputs")
    t = month_ends(ta_daily, inp.get("ta125_m"))
    if t.empty:
        raise ValueError("no TA-125")
    # trailing four quarters of nominal GDP, NIS millions, keyed by the last quarter's first day
    qs = sorted(gq)
    g4 = {}
    for i in range(3, len(qs)):
        win = qs[i - 3:i + 1]
        if pd.Period(win[-1], "Q").ordinal - pd.Period(win[0], "Q").ordinal == 3:
            g4[qs[i]] = sum(gq[q] for q in win)
    # year-end market values in NIS millions, where the TA-125 has a December close
    tdec = {d[:4]: v for d, v in t.items() if d[5:7] == "12"}
    anchors = {int(y): cap[y] * fx[y] / 1e6 for y in cap if y in fx and y in tdec and int(y) >= IL_FROM_YEAR}
    if len(anchors) < 5:
        raise ValueError(f"only {len(anchors)} year-end values")
    ys = sorted(anchors)
    out = {}
    for d, tv in t.items():
        y, m = int(d[:4]), int(d[5:7])
        y0 = max((a for a in ys if a < y or (a == y and m == 12)), default=None)
        if y0 is None:
            continue
        base = anchors[y0] * tv / tdec[str(y0)]
        y1 = min((a for a in ys if a > y0), default=None)
        if y1 is not None:
            resid = math.log(anchors[y1] / anchors[y0]) - math.log(tdec[str(y1)] / tdec[str(y0)])
            frac = ((y - y0) * 12 + m - 12) / ((y1 - y0) * 12)
            base *= math.exp(resid * frac)
        g = _gdp_for(g4, d)
        if g:
            out[d] = round(float(base / g * 100), 2)
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- run
def run(px: pd.DataFrame, offline: bool = False) -> tuple[dict, str, list[str]]:
    """Returns ({series id: points}, message, problems). A series whose computation fails is left out (the stored
    file is kept)."""
    inp, problems = load_inputs(offline)
    col = lambda c: px[c].dropna() if c in px.columns else None
    out, msg = {}, []
    for sid, fn, rng, need in (("buffett_us", lambda: us_series(inp, col("^W5000")), US_RANGE, ("us_gdp", "us_z1", "w5000_m")),
                               ("buffett_il", lambda: il_series(inp, col("^TA125.TA")), IL_RANGE, ("il_gdp", "il_cap", "il_fx_ye", "ta125_m"))):
        try:
            miss = [k for k in need if not inp.get(k)]
            if miss:      # never write a series cut short by a missing input
                raise ValueError(f"missing inputs: {', '.join(miss)}")
            pts = fn()
            last = max(pts)
            if not rng[0] <= pts[last] <= rng[1]:
                raise ValueError(f"latest reading {pts[last]} out of range {rng}")
            have = read_series(sid)
            if have and (len(pts) < 0.9 * len(have) or min(pts) > min(have)):
                raise ValueError(f"{len(pts)} points from {min(pts)}, stored {len(have)} from {min(have)}")
            out[sid] = pts
            label = "ארה\"ב" if sid.endswith("us") else "ישראל"
            msg.append(f"{label} {pts[last]:.0f}% ({last})")
        except Exception as e:
            problems.append(f"{sid}: {type(e).__name__} {str(e)[:90]}")
    cap = inp.get("il_cap") or {}
    if cap:
        msg.append(f"שווי שוק ת\"א מהבנק העולמי עד סוף {max(cap)}")
    return out, " · ".join(msg), problems


def notes() -> dict[str, str]:
    """A line for each indicator's detail view about how current its inputs are (from the cache)."""
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8")).get("data", {})
    except Exception:
        return {}
    q = lambda d: f"רבעון {(int(d[5:7]) - 1) // 3 + 1} של {d[:4]}"
    out = {}
    if data.get("us_gdp"):
        out["buffett_us"] = f"התמ\"ג האחרון שפורסם: {q(max(data['us_gdp']))}."
    if data.get("il_cap") and data.get("il_gdp"):
        y = max(data["il_cap"])
        out["buffett_il"] = (f"השווי השנתי האחרון של הבנק העולמי: סוף {y}. מאז הערך הוא הערכה לפי ת\"א-125, וייתכן שהוא נמוך בכמה אחוזים "
                             f"מהשווי בפועל, כי חברות שהונפקו מאז ייכנסו רק כשתתפרסם השנה הבאה. התמ\"ג האחרון שפורסם: {q(max(data['il_gdp']))}.")
    return out
