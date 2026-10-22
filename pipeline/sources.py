"""Fetchers for the sentiment sources. Each returns {series_id: {date: value}} or raises.

Every fetcher validates what it parsed (plausible ranges, dates) and never writes on doubt.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re

from bs4 import BeautifulSoup

from .common import cutoff_date, get, iso, read_series, save_probe, today_utc

# --------------------------------------------------------------------------- CNN
CNN_MAP = {  # our id: (CNN key, decimals, plausible min, plausible max)
    "fg": ("fear_and_greed_historical", 2, 0, 100),
    "pc5": ("put_call_options", 4, 0.2, 3),
    "mcsi": ("stock_price_breadth", 1, -5000, 5000),
    "nhnl": ("stock_price_strength", 3, -100, 100),
    "junk": ("junk_bond_demand", 3, 0, 20),
    "safe": ("safe_haven_demand", 3, -60, 60),
}
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start}"
CNN_MIRROR = "https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/json/cnn_output.json"
CNN_HEADERS = {"Accept": "application/json, text/plain, */*", "Referer": "https://www.cnn.com/",
               "Origin": "https://www.cnn.com"}


def _cnn_parse(js: dict, since: str) -> dict:
    out = {}
    today = cutoff_date()
    for sid, (key, nd, lo, hi) in CNN_MAP.items():
        pts = {}
        for p in js[key]["data"]:
            d = dt.datetime.fromtimestamp(p["x"] / 1000, dt.timezone.utc).date()
            ds = d.isoformat()
            if ds < since or ds > today or d.weekday() >= 5:
                continue
            v = round(float(p["y"]), nd)
            if not (lo <= v <= hi):
                raise ValueError(f"CNN {key} {ds} value {v} outside [{lo},{hi}]")
            pts[ds] = v
        if not pts:
            raise ValueError(f"CNN {key}: no points since {since}")
        out[sid] = pts
    return out


def cnn(days: int = 30) -> tuple[dict, str]:
    since = iso(today_utc() - dt.timedelta(days=days))
    try:
        js = get(CNN_URL.format(start=since), headers=CNN_HEADERS, expect_json=True, tries=2)
        return _cnn_parse(js, since), "CNN"
    except Exception as e:
        first = str(e)
    js = get(CNN_MIRROR, expect_json=True)
    return _cnn_parse(js, since), f"מראה GitHub (CNN ישירות נכשל: {first[:80]})"


# --------------------------------------------------------------------------- Cboe index history
CBOE_CSV = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv"
CBOE_RANGES = {"VIX": (5, 150), "VIX3M": (5, 120), "VVIX": (40, 300), "SKEW": (90, 200)}


def _parse_date(s: str) -> str | None:
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def cboe_history(sym: str) -> dict:
    r = get(CBOE_CSV.format(sym=sym))
    rows = list(csv.reader(io.StringIO(r.text)))
    head = [h.strip().upper() for h in rows[0]]
    col = head.index("CLOSE") if "CLOSE" in head else len(head) - 1
    lo, hi = CBOE_RANGES[sym]
    out, bad = {}, 0
    for row in rows[1:]:
        if len(row) <= col:
            continue
        d = _parse_date(row[0])
        try:
            v = float(row[col])
        except ValueError:
            continue
        if d and lo <= v <= hi:
            out[d] = round(v, 2)
        else:
            bad += 1
    if len(out) < 500:
        save_probe(f"cboe_{sym}", r.text[:3000])
        raise ValueError(f"Cboe {sym}: only {len(out)} valid rows ({bad} rejected)")
    return out


# --------------------------------------------------------------------------- CFTC
SOCRATA = "https://publicreporting.cftc.gov/resource/{ds}.json"


def cftc() -> dict:
    out = {}
    tff = get(SOCRATA.format(ds="gpe5-46if"), expect_json=True, params={
        "$select": "report_date_as_yyyy_mm_dd,cftc_contract_market_code,asset_mgr_positions_long,"
                   "asset_mgr_positions_short,lev_money_positions_long,lev_money_positions_short",
        "$where": "cftc_contract_market_code in('13874A','209742')",
        "$order": "report_date_as_yyyy_mm_dd", "$limit": "10000"})
    es_am, es_lev, nq_am = {}, {}, {}
    for r in tff:
        d = r["report_date_as_yyyy_mm_dd"][:10]
        try:
            am = int(float(r["asset_mgr_positions_long"])) - int(float(r["asset_mgr_positions_short"]))
            lev = int(float(r["lev_money_positions_long"])) - int(float(r["lev_money_positions_short"]))
        except (KeyError, TypeError, ValueError):
            continue
        if r["cftc_contract_market_code"] == "13874A":
            es_am[d], es_lev[d] = am, lev
        else:
            nq_am[d] = am
    leg = get(SOCRATA.format(ds="6dca-aqww"), expect_json=True, params={
        "$select": "report_date_as_yyyy_mm_dd,noncomm_positions_long_all,noncomm_positions_short_all",
        "$where": "cftc_contract_market_code='1170E1'",
        "$order": "report_date_as_yyyy_mm_dd", "$limit": "10000"})
    vix_nc = {}
    for r in leg:
        try:
            vix_nc[r["report_date_as_yyyy_mm_dd"][:10]] = (int(float(r["noncomm_positions_long_all"]))
                                                          - int(float(r["noncomm_positions_short_all"])))
        except (KeyError, TypeError, ValueError):
            continue
    for sid, s in (("cot_es_am", es_am), ("cot_es_lev", es_lev), ("cot_vix_nc", vix_nc), ("cot_nq_am", nq_am)):
        if len(s) < 100:
            raise ValueError(f"CFTC {sid}: only {len(s)} reports")
        out[sid] = s
    # cross-check against what we already hold: history must not silently change
    for sid in ("cot_es_am", "cot_es_lev", "cot_vix_nc"):
        old = read_series(sid)
        diff = [d for d in old if d in out[sid] and abs(old[d] - out[sid][d]) > 0.5]
        if len(diff) > 3:
            raise ValueError(f"CFTC {sid}: {len(diff)} stored weeks differ from the source (e.g. {diff[:3]})")
    return out


# --------------------------------------------------------------------------- AAII
AAII_URL = "https://www.aaii.com/sentimentsurvey/sent_results"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def aaii() -> dict:
    r = get(AAII_URL, headers={"Accept": "text/html,application/xhtml+xml"})
    soup = BeautifulSoup(r.text, "lxml")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 4:
            continue
        m = re.match(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})$", cells[0])
        pcts = [re.match(r"^(\d{1,3}(?:\.\d)?)\s*%$", c) for c in cells[1:4]]
        if m and all(pcts) and m.group(1).lower() in MONTHS:
            rows.append((MONTHS[m.group(1).lower()], int(m.group(2)), *[float(p.group(1)) for p in pcts]))
    if len(rows) < 4:
        save_probe("aaii", r.text)
        raise ValueError(f"AAII: parsed only {len(rows)} rows")
    today = today_utc()
    year = today.year if (rows[0][0], rows[0][1]) <= (today.month, today.day) else today.year - 1
    prev_month = rows[0][0]
    bull, bear, spread = {}, {}, {}
    for mo, day, b, n, br in rows:
        if mo > prev_month:  # walked back across a new year
            year -= 1
        prev_month = mo
        if abs(b + n + br - 100) > 0.35:
            raise ValueError(f"AAII {mo}/{day}: {b}+{n}+{br} != 100")
        d = dt.date(year, mo, day).isoformat()
        bull[d], bear[d], spread[d] = b, br, round(b - br, 1)
    old = read_series("aaii_bull")
    clash = [d for d in bull if d in old and abs(old[d] - bull[d]) > 0.15]
    if clash:
        raise ValueError(f"AAII: parsed values differ from stored ones on {clash[:3]}")
    return {"aaii_bull": bull, "aaii_bear": bear, "aaii_spread": spread}


# --------------------------------------------------------------------------- FRED
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SERIES = {"hy_oas": ("BAMLH0A0HYM2", 0.5, 30), "t10y2y": ("T10Y2Y", -5, 5), "nfci": ("NFCI", -3, 10)}


def _fred_csv(code: str):
    """FRED does not always answer cloud runners; try a few request shapes, each with a short timeout."""
    tries = [
        (FRED_CSV, {"id": code}, {"User-Agent": "curl/8.5.0", "Accept": "*/*"}),
        (f"https://fred.stlouisfed.org/series/{code}/downloaddata/{code}.csv", None, {"User-Agent": "curl/8.5.0", "Accept": "*/*"}),
        (FRED_CSV, {"id": code, "cosd": "2000-01-01"}, None),
    ]
    errs = []
    for url, params, headers in tries:
        try:
            r = get(url, params=params, headers=headers, timeout=35, tries=1)
            if r.text.lstrip().lower().startswith(("observation_date", "date")):
                return r
            errs.append(f"{url[:60]}: not csv")
        except Exception as e:
            errs.append(str(e)[-90:])
    raise RuntimeError(" | ".join(errs))


def fred() -> dict:
    out = {}
    for sid, (code, lo, hi) in FRED_SERIES.items():
        r = _fred_csv(code)  # a failure on the first series fails fast for all three
        rows = list(csv.reader(io.StringIO(r.text)))
        pts = {}
        for row in rows[1:]:
            if len(row) < 2 or row[1] in (".", ""):
                continue
            try:
                v = float(row[1])
            except ValueError:
                continue
            d = _parse_date(row[0])
            if d and lo <= v <= hi:
                pts[d] = v
        if len(pts) < 200:
            save_probe(f"fred_{code}", r.text[:3000])
            raise ValueError(f"FRED {code}: only {len(pts)} rows")
        out[sid] = pts
    return out


# --------------------------------------------------------------------------- Cboe daily put/call
CBOE_PC_URL = "https://www.cboe.com/us/options/market_statistics/daily/"
PC_LABELS = {"total": r"TOTAL\s+PUT/CALL\s+RATIO", "index": r"(?<!\+ )INDEX\s+PUT/CALL\s+RATIO",
             "equity": r"EQUITY\s+PUT/CALL\s+RATIO", "spx": r"SPX\s*\+\s*SPXW\s+PUT/CALL\s+RATIO"}


def _pc_page(day: dt.date) -> dict | None:
    r = get(CBOE_PC_URL, params={"dt": day.isoformat()}, tries=2)
    text = BeautifulSoup(r.text, "lxml").get_text(" ", strip=True)
    # The page must name the requested date, or we cannot be sure which day the numbers belong to.
    forms = {day.isoformat(), day.strftime("%m/%d/%Y"), day.strftime("%B %d, %Y").replace(" 0", " "),
             day.strftime("%b %d, %Y").replace(" 0", " "), day.strftime("%B %-d, %Y"), day.strftime("%b %-d, %Y")}
    if not any(f in r.text or f in text for f in forms):
        return {"_nodate": True, "_sample": text[:1500]}
    if "SPX" in text and not getattr(_pc_page, "_probed", False):
        _pc_page._probed = True
        i = text.find("SPX")
        urls = sorted(set(re.findall(r"https://cdn\.cboe\.com/[^\"' )]+", r.text)))[:20]
        save_probe("cboe_pc_text", text[max(0, i - 400):i + 800] + "\n\nURLS:\n" + "\n".join(urls))
    vals = {}
    for k, pat in PC_LABELS.items():
        m = re.search(pat + r"\s*:?\s*(\d+\.\d+)", text, re.I)
        if m:
            vals[k] = float(m.group(1))
    return vals or {"_novals": True, "_sample": text[:1500]}


def cboe_putcall(max_days: int = 12) -> dict:
    """Daily P/C ratios since the last stored day. Starts earlier when the SPX series is behind, and falls
    back to the normal start if Cboe will not serve that older day."""
    pcc, spx = read_series("pcc"), read_series("pcspx")
    if pcc and spx and max(spx) < max(pcc):
        early = [d for d in pcc if d <= max(spx)]
        if early:
            try:
                return _cboe_putcall(max_days, start=max(early))
            except ValueError:
                pass
    return _cboe_putcall(max_days)


def _cboe_putcall(max_days: int = 12, start: str | None = None) -> dict:
    """Fetch Cboe's daily P/C ratios for each business day since the last stored value.

    The first fetched day is one we already hold (from TradingView's USI:PCC export) and must match
    within 0.01, which proves the parser reads the right number for the right day."""
    pcc = read_series("pcc")
    spx = read_series("pcspx")
    last = start or (max(pcc) if pcc else iso(today_utc() - dt.timedelta(days=7)))
    d = dt.date.fromisoformat(last)
    days = []
    while d <= today_utc() and len(days) < max_days:
        if d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    got = {}
    for day in days:
        res = _pc_page(day)
        if res is None or "_nodate" in res or "_novals" in res:
            if day == days[0]:
                save_probe("cboe_pc", (res or {}).get("_sample", ""))
                raise ValueError("Cboe P/C: page did not confirm the date or values for the check day")
            continue
        got[day.isoformat()] = res
    check = got.get(days[0].isoformat())
    if pcc and check and abs(check.get("total", -9) - pcc.get(days[0].isoformat(), -99)) > 0.011:
        raise ValueError(f"Cboe P/C check failed on {days[0]}: total {check.get('total')} vs stored {pcc.get(days[0].isoformat())}")
    out = {"pcc": {}, "pce": {}, "pcspx": {}}
    spx_ok = not spx or not check or "spx" not in check or days[0].isoformat() not in spx or abs(check["spx"] - spx[days[0].isoformat()]) <= 0.03
    if not spx_ok or not any("spx" in v for v in got.values()):
        save_probe("cboe_pc_spx", json.dumps({"check_day": days[0].isoformat(), "cboe": (check or {}).get("spx"),
                                              "stored": spx.get(days[0].isoformat()), "days": {d: v.get("spx") for d, v in got.items()}}))
    for ds, v in got.items():
        if spx_ok and "spx" in v and 0.3 < v["spx"] < 5:
            out["pcspx"][ds] = v["spx"]
        if "total" in v and 0.3 < v["total"] < 3:
            out["pcc"][ds] = v["total"]
        if "equity" in v and 0.2 < v["equity"] < 3:
            out["pce"][ds] = v["equity"]
    return out
