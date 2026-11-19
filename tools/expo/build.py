#!/usr/bin/env python3
"""Nightly market data for the foreign-equity exposure dashboard (דשבורד חשיפות – תיק מניות חו"ל).

The dashboard is a local HTML file that Forte opens every day. On opening it reads data/expo/market.json from this repo
(raw.githubusercontent.com) and falls back to the snapshot embedded in the file when it is offline. Fund holdings are
never written here (the repo is public): they are uploaded in the dashboard and stay in the user's browser.

What is built after each US session (tools/expo/ref.json holds names, sectors, countries and theme tags):
  ETF holdings  SSGA daily files (SPY, the Select Sector SPDRs, KIE, XAR) and First Trust (CIBR); Invesco (QQQ) is
                tried; RSP = equal weight of SPY's members; VGT, VHT, FDIS and IYF by proxy. An ETF without a fresh file
                keeps its last list (else the 12.11.2026 snapshot) with the weights rolled forward by price, marked stale.
  Prices        Yahoo daily closes, 2 years: last price, 12-month price return, beta vs SPY (2 years of weekly returns).
  Fundamentals  Yahoo (quote summary + annual income statement) on a rotation: data/expo/fund.json keeps the date of
                every name and each run refreshes the oldest ones first, so no name is more than about a week old.
  Factors       for each metric, the percentile against the S&P 500 members that have it (equal weight, 0-1); a factor
                score is the mean of its metrics' percentiles (FACTORS below), as in the dashboard's method tab.

Usage: python tools/expo/build.py [--fund-budget SECONDS] [--fund-max N] [--offline]
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "expo"
REF_PATH = ROOT / "tools" / "expo" / "ref.json"
MARKET = OUT / "market.json"
FUND = OUT / "fund.json"

SECT = {"Information Technology": "T", "Financials": "F", "Health Care": "H", "Consumer Discretionary": "D",
        "Communication Services": "C", "Industrials": "I", "Consumer Staples": "S", "Energy": "E", "Utilities": "U",
        "Real Estate": "R", "Materials": "M",
        # Yahoo's sector names, for names outside the SSGA files
        "Technology": "T", "Financial Services": "F", "Healthcare": "H", "Consumer Cyclical": "D",
        "Consumer Defensive": "S", "Basic Materials": "M"}
COUNTRY = {"United States": 'ארה"ב', "Israel": "ישראל", "Taiwan": "טייוואן", "Canada": "קנדה", "China": "סין",
           "India": "הודו", "Brazil": "אמריקה הלטינית", "Argentina": "אמריקה הלטינית", "Uruguay": "אמריקה הלטינית",
           "Mexico": "אמריקה הלטינית", "Japan": "יפן", "South Korea": "קוריאה", "Australia": "אוסטרליה"}
EUROPE = {"United Kingdom", "Netherlands", "Ireland", "Switzerland", "Germany", "France", "Luxembourg", "Belgium",
          "Denmark", "Sweden", "Norway", "Finland", "Spain", "Italy", "Jersey", "Guernsey", "Bermuda"}
AUTO_THEME = {"E": ["oil_gas"], "S": ["defensive"], "U": ["defensive"]}   # new names, as the snapshot tagged them

SSGA = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{t}.xlsx"
SSGA_ETFS = ["SPY", "XLK", "XLF", "XLV", "XLY", "XLC", "XLI", "XLP", "XLE", "XLU", "XLRE", "XLB", "KIE", "XAR"]
INVESCO_API = ("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{t}/holdings/fund"
               "?idType=ticker&productType=ETF")
INVESCO_URL = ("https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0"
               "?audienceType=Investor&action=download&ticker={t}")
FTP_URL = "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker={t}"
PROXY = {"VGT": "XLK", "VHT": "XLV", "FDIS": "XLY", "IYF": "XLF"}
# iShares (SOXX) refuses scripted downloads and Invesco's file (QQQ) answers 406 from GitHub's runners (checked
# 19.11.2026): QQQ is still tried every run; both are otherwise rolled forward by price from their last list.
OPTIONAL = {"QQQ"}
# a company with two listed share classes counts as one (as the dashboard always did): the issuers list both
CLASS_MERGE = {"GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA", "BRK-A": "BRK-B"}
# names that are not in ref.json take their GICS sector from the sector SPDR that holds them, and the theme of a
# thematic ETF that holds them (KIE's insurers, XAR's defense names, ...)
ETF_SECTOR = {"XLK": "T", "XLF": "F", "XLV": "H", "XLY": "D", "XLC": "C", "XLI": "I", "XLP": "S", "XLE": "E", "XLU": "U",
              "XLRE": "R", "XLB": "M", "KIE": "F", "XAR": "I", "SOXX": "T"}
ETF_THEME = {"KIE": "insurance", "XAR": "defense", "CIBR": "cyber", "SOXX": "ai_chips", "GDX": "gold"}

# factor -> metrics (key, higher is better?); quality skips debt/equity for financials
FACTORS = {"fq": [("roe", 1), ("roa", 1), ("nm", 1), ("de", -1)],
           "fg": [("s3", 1), ("s1", 1), ("e3", 1)],
           "fv": [("ey", 1), ("dy", 1)],
           "flv": [("beta", -1)],
           "fm": [("r1", 1)]}
MIN_METRICS = {"fq": 2, "fg": 2, "fv": 1, "flv": 1, "fm": 1}


# Bloomberg-style exchange suffixes in the issuers' files -> Yahoo suffixes (Atos ATO-FP -> ATO.PA)
YSUF = {"FP": ".PA", "CN": ".TO", "LN": ".L", "GY": ".DE", "GR": ".DE", "NA": ".AS", "SM": ".MC", "IM": ".MI", "SW": ".SW",
        "SE": ".SW", "AU": ".AX", "JP": ".T", "JT": ".T", "HK": ".HK", "SS": ".ST", "FH": ".HE", "DC": ".CO", "NO": ".OL",
        "BB": ".BR", "ID": ".IR", "AV": ".VI", "PL": ".LS", "KS": ".KS", "TT": ".TW", "IT": ".TA"}


def ysym(s: str) -> str:
    m = re.fullmatch(r"([A-Z0-9]+)-([A-Z]{2})", s)
    return m.group(1) + YSUF[m.group(2)] if m and m.group(2) in YSUF else s


def log(*a):
    print(*a, flush=True)


def today_il() -> str:
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()


def http_get(url: str, **kw):
    from pipeline.common import get
    return get(url, **kw)


def num(v):
    try:
        f = float(str(v).replace(",", "").replace("%", "").strip())
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def norm_ticker(s) -> str | None:
    s = str(s or "").strip().upper()
    if not s or s in ("-", "NAN", "NONE") or s.startswith("CASH") or len(s) > 10:
        return None
    s = re.sub(r"[./ ]+", "-", s)
    return s if re.fullmatch(r"[A-Z][A-Z0-9]*(-[A-Z0-9]+)?", s) else None


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(text) -> str | None:
    """'As of 18-Nov-2026', 'Nov 18, 2026', '11/18/2026', '2026-11-18' -> '2026-11-18'."""
    s = str(text or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ,]+(\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})", s)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


# ---------------------------------------------------------------- ETF holdings parsers
FUTURES = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\d{2}\b|e-?mini|future", re.I)


def parse_ssga(raw: bytes) -> dict:
    """SSGA daily holdings xlsx: a few lines of fund info ('As of 18-Nov-2026'), then
    Name | Ticker | Identifier (CUSIP) | SEDOL | Weight (%) | Sector | Shares Held | Local Currency."""
    df = pd.read_excel(io.BytesIO(raw), header=None, dtype=object)
    asof, hdr = None, None
    for i in range(min(len(df), 30)):
        cells = [str(x).strip() for x in df.iloc[i].tolist() if x is not None and str(x) != "nan"]
        line = " ".join(cells)
        if asof is None and re.search(r"as of", line, re.I):
            asof = parse_date(line)
        if "Ticker" in cells and any(c.startswith("Weight") for c in cells):
            hdr = i
            break
    if hdr is None:
        raise ValueError("SSGA: no header row")
    cols = [str(x).strip() for x in df.iloc[hdr].tolist()]
    body = df.iloc[hdr + 1:].copy()
    body.columns = cols
    wcol = next(c for c in cols if c.startswith("Weight"))
    rows = []
    for _, r in body.iterrows():
        # SSGA stopped filling the Sector column ("-") in 2026: equities are the rows with a ticker and a CUSIP
        t, sec, w = norm_ticker(r.get("Ticker")), SECT.get(str(r.get("Sector", "")).strip()), num(r.get(wcol))
        name, cu = str(r.get("Name") or "").strip(), str(r.get("Identifier") or "").strip()
        if (t and w is not None and w > 0 and re.fullmatch(r"[0-9A-Z]{9}", cu) and not re.search(r"\bCASH\b|DOLLAR", name, re.I)
                and not FUTURES.search(name)):
            rows.append((t, w / 100.0, name, sec, cu))
    return _pack(rows, asof)


def parse_invesco(text: str) -> dict:
    """Invesco holdings CSV: Fund Ticker,Security Identifier,Holding Ticker,Shares/Par Value,MarketValue,Weight,Name,
    Class of Shares,Sector,Date."""
    df = pd.read_csv(io.StringIO(text.lstrip("﻿")), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    tcol = next(c for c in df.columns if "Holding Ticker" in c or c == "Ticker")
    wcol = next(c for c in df.columns if c.startswith("Weight"))
    dcol = next((c for c in df.columns if c.lower() in ("date", "as of date")), None)
    asof = parse_date(df[dcol].dropna().iloc[0]) if dcol and df[dcol].notna().any() else None
    rows = []
    for _, r in df.iterrows():
        t, w = norm_ticker(r.get(tcol)), num(r.get(wcol))
        if t and w and w > 0:
            rows.append((t, w / 100.0, str(r.get("Name") or "").strip(), SECT.get(str(r.get("Sector", "")).strip()),
                         str(r.get("Security Identifier") or "").strip()))
    return _pack(rows, asof)


def parse_invesco_json(js: dict) -> dict:
    """Invesco's holdings API: {"effectiveDate": ..., "holdings": [{"ticker", "percentageOfTotalNetAssets", "cusip",
    "issuerName", ...}]} (field names vary a little between versions, so several are tried)."""
    items = js.get("holdings") or js.get("data") or []
    asof = parse_date(js.get("effectiveDate") or js.get("asOfDate") or "")
    rows = []
    for h in items:
        t = norm_ticker(h.get("ticker") or h.get("holdingTicker"))
        w = num(h.get("percentageOfTotalNetAssets") or h.get("weight") or h.get("percentOfNetAssets"))
        if t and w and w > 0:
            rows.append((t, w / 100.0, str(h.get("issuerName") or h.get("name") or "").strip(), None, str(h.get("cusip") or "")))
    return _pack(rows, asof)


def parse_ftp(html: str) -> dict:
    """First Trust holdings page: a table with Security Name | Identifier (ticker) | CUSIP | ... | Weighting."""
    asof = None
    m = re.search(r"[Hh]oldings[^<]{0,40}?[Aa]s [Oo]f[^<]{0,20}?(\d{1,2}/\d{1,2}/\d{4})", html)
    if m:
        asof = parse_date(m.group(1))
    tables = pd.read_html(io.StringIO(html), match="Weighting")
    df = max(tables, key=len)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(x) for x in c if "Unnamed" not in str(x)).strip() for c in df.columns]
    df.columns = [str(c).strip() for c in df.columns]
    hdr = None
    if not any("Weighting" in c for c in df.columns):        # header sits in the first data row
        for i in range(min(len(df), 5)):
            if any("Weighting" in str(x) for x in df.iloc[i].tolist()):
                hdr = i
                break
        if hdr is not None:
            df.columns = [str(x).strip() for x in df.iloc[hdr].tolist()]
            df = df.iloc[hdr + 1:]
    tcol = next((c for c in df.columns if c in ("Identifier", "Ticker", "Symbol")), None)
    wcol = next((c for c in df.columns if "Weighting" in c), None)
    ncol = next((c for c in df.columns if "Name" in c), None)
    ccol = next((c for c in df.columns if "CUSIP" in c), None)
    if not tcol or not wcol:
        raise ValueError(f"First Trust columns {list(df.columns)[:8]} rows {df.head(2).values.tolist()}")
    rows = []
    for _, r in df.iterrows():
        t, w = norm_ticker(r.get(tcol)), num(r.get(wcol))
        if t and w and w > 0:
            rows.append((t, w / 100.0, str(r.get(ncol) or "").strip() if ncol else "", None,
                         str(r.get(ccol) or "").strip() if ccol else ""))
    return _pack(rows, asof)


def _pack(rows, asof) -> dict:
    if not rows:
        raise ValueError("no equity rows")
    h, meta = {}, {}
    for t, w, name, sec, cusip in rows:
        h[t] = h.get(t, 0.0) + w
        meta.setdefault(t, {"name": name, "s": sec, "cu": cusip[:9] if re.fullmatch(r"[0-9A-Z]{8,9}", cusip or "") else None})
    tot = sum(h.values())
    return {"h": {t: round(w / tot, 6) for t, w in sorted(h.items(), key=lambda x: -x[1])}, "meta": meta,
            "asof": asof, "raw_sum": round(tot, 4), "n": len(h)}


def canon_keys(d: dict, known: set) -> dict:
    """Map tickers written without the class dash (BRKB) onto the known ones (BRK-B)."""
    flat = {k.replace("-", ""): k for k in known}
    out = {}
    for k, v in d.items():
        kk = k if k in known else flat.get(k.replace("-", ""), k)
        out[kk] = (out[kk] + v) if (kk in out and isinstance(v, float)) else v
    return out


def fetch_raw(t: str):
    """(raw response, parser, source name) for one ETF."""
    if t in SSGA_ETFS:
        return http_get(SSGA.format(t=t.lower()), timeout=60), lambda r: parse_ssga(r.content), "SSGA"
    if t == "QQQ":
        try:
            r = http_get(INVESCO_API.format(t=t), timeout=60, headers={"Accept": "application/json"})
            return r, lambda r: parse_invesco_json(r.json()), "Invesco"
        except Exception:
            return (http_get(INVESCO_URL.format(t=t), timeout=60, headers={"Accept": "text/csv,*/*;q=0.8"}),
                    lambda r: parse_invesco(r.text), "Invesco")
    if t == "CIBR":
        return http_get(FTP_URL.format(t=t), timeout=60), lambda r: parse_ftp(r.text), "First Trust"
    raise KeyError(t)


def nasdaq100() -> tuple[set, str]:
    """Current Nasdaq-100 members: Nasdaq's own list, else Wikipedia's table."""
    try:
        js = http_get("https://api.nasdaq.com/api/quote/list-type/nasdaq100", expect_json=True, timeout=30,
                      headers={"Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com",
                               "Referer": "https://www.nasdaq.com/"})
        rows = (((js or {}).get("data") or {}).get("data") or {}).get("rows") or []
        syms = {norm_ticker(r.get("symbol")) for r in rows} - {None}
        if 95 <= len(syms) <= 105:
            return syms, "Nasdaq"
        log(f"nasdaq100: Nasdaq list has {len(syms)} names")
    except Exception as e:
        log(f"nasdaq100: Nasdaq {type(e).__name__}: {str(e)[:120]}")
    html = http_get("https://en.wikipedia.org/wiki/Nasdaq-100", timeout=30).text
    for df in pd.read_html(io.StringIO(html)):
        col = next((c for c in df.columns if str(c).strip() in ("Ticker", "Symbol")), None)
        if col is not None and 95 <= len(df) <= 105:
            syms = {norm_ticker(x) for x in df[col]} - {None}
            if 95 <= len(syms) <= 105:
                return syms, "Wikipedia"
    raise ValueError("no Nasdaq-100 list")


def preview(r) -> str:
    """A short look at a response the parser could not read, for the log."""
    ct = r.headers.get("content-type", "")
    if r.content[:2] == b"PK":
        try:
            df = pd.read_excel(io.BytesIO(r.content), header=None, dtype=object)
            return f"xlsx {df.shape}: " + " | ".join(
                ";".join(str(x)[:24] for x in df.iloc[i].tolist() if str(x) != "nan") for i in range(min(len(df), 9)))
        except Exception as e:
            return f"xlsx unreadable {e}"
    return f"{ct} {len(r.content)}B: " + re.sub(r"\s+", " ", r.text[:700])


# ---------------------------------------------------------------- prices
def yahoo_closes(syms: list[str], days: int = 760) -> pd.DataFrame:
    import yfinance as yf
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    frames = []
    for i in range(0, len(syms), 120):
        chunk = syms[i:i + 120]
        for attempt in range(2):
            try:
                raw = yf.download(chunk, start=start, auto_adjust=False, actions=False, progress=False, threads=True,
                                  group_by="column", multi_level_index=True, timeout=30)
                c = raw["Close"]
                if isinstance(c, pd.Series):
                    c = c.to_frame(chunk[0])
                frames.append(c)
                break
            except Exception as e:
                log(f"  prices chunk {i}: {type(e).__name__} {str(e)[:120]}")
                time.sleep(5)
    if not frames:
        return pd.DataFrame()
    close = pd.concat(frames, axis=1)
    close = close.loc[:, ~close.columns.duplicated()]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close.sort_index().dropna(how="all")
    from zoneinfo import ZoneInfo
    ny = dt.datetime.now(ZoneInfo("America/New_York"))
    if len(close) and close.index[-1].date() >= ny.date() and ny.hour * 60 + ny.minute < 16 * 60 + 20:
        close = close.iloc[:-1]           # today's bar while the US session is open is not a close
    return close


def price_stats(close: pd.DataFrame, bench: str = "SPY") -> dict:
    """Per symbol: last price and date, 12-month price return (%), beta vs bench on up to 104 weekly returns."""
    out = {}
    if close.empty:
        return out
    wk = close.resample("W-FRI").last()
    wr = wk.pct_change(fill_method=None).iloc[-105:]
    b = wr[bench] if bench in wr else None
    last_day = close.index[-1]
    for s in close.columns:
        col = close[s].dropna()
        if col.empty or (last_day - col.index[-1]).days > 7:
            continue
        px, d = float(col.iloc[-1]), col.index[-1]
        r1 = None
        yr = col[col.index <= d - pd.DateOffset(years=1)]
        if len(yr) and (d - pd.DateOffset(years=1) - yr.index[-1]).days <= 7:
            r1 = round((px / float(yr.iloc[-1]) - 1) * 100, 2)
        beta = None
        if b is not None and s != bench:
            j = pd.concat([wr[s], b], axis=1, keys=["x", "b"]).dropna()
            if len(j) >= 52 and j["b"].var() > 0:
                beta = round(float(j["x"].cov(j["b"]) / j["b"].var()), 2)
        elif s == bench:
            beta = 1.0
        out[s] = {"px": round(px, 4), "d": d.date().isoformat(), "r1": r1, "beta": beta}
    return out


SNAP_PRICE_DATE = "2026-11-11"   # the 12.11.2026 snapshot's weights are as of the 11.11.2026 US close


def roll_weights(h: dict, frm: str, close: pd.DataFrame) -> tuple[dict, str | None]:
    """Weights at date frm carried to the last close: w_i * P_i(last) / P_i(frm), renormalized to the same total
    (a residual share outside the listed names stays as it was). Names without prices keep their weight."""
    idx = close.index
    i0 = idx.searchsorted(pd.Timestamp(frm), side="right") - 1
    if i0 < 0:
        return h, None
    p0, p1 = close.iloc[i0], close.iloc[-6:].ffill().iloc[-1]   # no price in the last week = no longer trades
    new = {}
    for k, w in h.items():
        a, b = p0.get(k), p1.get(k)
        if k in close.columns and (b is None or b != b):
            continue
        new[k] = w * (b / a) if a is not None and b is not None and a == a and b == b and a > 0 else w
    tot0, tot1 = sum(h.values()), sum(new.values())
    return {k: round(v * tot0 / tot1, 6) for k, v in sorted(new.items(), key=lambda x: -x[1])}, idx[-1].date().isoformat()


# ---------------------------------------------------------------- fundamentals
def _cagr(a, b, years):
    if a is None or b is None or b <= 0 or a <= 0:
        return None
    return round(((a / b) ** (1 / years) - 1) * 100, 2)


def fundamentals(sym: str) -> dict:
    """Yahoo quote summary + annual income statement for one symbol (ratios only, so currency does not matter)."""
    import yfinance as yf
    tk = yf.Ticker(sym)
    info = tk.info or {}
    if not info or info.get("quoteType") not in (None, "EQUITY"):
        raise ValueError(f"quoteType {info.get('quoteType')}")
    f = lambda k, m=1.0: (None if num(info.get(k)) is None else round(num(info.get(k)) * m, 4))
    r = {"at": today_il(), "pxAt": f("regularMarketPrice") or f("currentPrice") or f("previousClose"),
         "mcap": f("marketCap", 1e-9), "pe": f("trailingPE"), "eps": f("trailingEps"),
         "dy": f("trailingAnnualDividendYield", 100), "dyF": f("dividendYield"), "roe": f("returnOnEquity", 100), "roa": f("returnOnAssets", 100),
         "nm": f("profitMargins", 100), "de": f("debtToEquity", 0.01), "pb": f("priceToBook"),
         "qs1": f("revenueGrowth", 100), "name": info.get("shortName") or info.get("longName"),
         "country": info.get("country"), "ysec": info.get("sector"), "cur": info.get("currency")}
    try:
        inc = tk.income_stmt
        if inc is not None and not inc.empty:
            inc = inc[sorted(inc.columns, key=pd.Timestamp, reverse=True)]
            rev = next((inc.loc[k] for k in ("Total Revenue", "Operating Revenue") if k in inc.index), None)
            eps = next((inc.loc[k] for k in ("Diluted EPS", "Basic EPS") if k in inc.index), None)
            rv = [num(x) for x in rev.tolist()] if rev is not None else []
            ev = [num(x) for x in eps.tolist()] if eps is not None else []
            r["fy"] = pd.Timestamp(inc.columns[0]).date().isoformat()
            if len(rv) >= 2:
                r["s1"] = _cagr(rv[0], rv[1], 1)
            if len(rv) >= 4:
                r["s3"] = _cagr(rv[0], rv[3], 3)
            elif len(rv) == 3:
                r["s3"] = _cagr(rv[0], rv[2], 2)
            if len(ev) >= 4:
                r["e3"] = _cagr(ev[0], ev[3], 3)
            elif len(ev) == 3:
                r["e3"] = _cagr(ev[0], ev[2], 2)
    except Exception as e:
        r["incErr"] = f"{type(e).__name__}"[:40]
    return {k: v for k, v in r.items() if v is not None}


def refresh_fundamentals(fund: dict, syms: list[str], budget_s: float, max_n: int) -> tuple[int, int, list[str]]:
    """Refresh the names with the oldest data first, within the time budget. Returns (done, failed, errors)."""
    order = sorted(syms, key=lambda s: ("mcap" in fund.get(s, {}), fund.get(s, {}).get("at", ""), s))   # missing first
    t0, done, failed, errs = time.time(), 0, 0, []
    todo = order[:max_n]

    def one(s):
        if time.time() - t0 > budget_s:
            return s, None, "budget"
        try:
            return s, fundamentals(ysym(s)), None
        except Exception as e:
            return s, None, f"{type(e).__name__}: {str(e)[:80]}"

    with ThreadPoolExecutor(max_workers=4) as ex:
        for s, data, err in ex.map(one, todo):
            if data:
                fund[s] = data
                done += 1
            elif err != "budget":
                failed += 1
                prev = fund.get(s, {})
                fund[s] = {**prev, "at": prev.get("at", ""), "err": err}
                if len(errs) < 8:
                    errs.append(f"{s}: {err}")
    return done, failed, errs


# ---------------------------------------------------------------- factors
def pct_ranker(values: list[float]):
    ref = np.sort(np.array(values, dtype=float))
    n = len(ref)

    def rank(v):
        if v is None or n == 0:
            return None
        lo = np.searchsorted(ref, v, side="left")
        hi = np.searchsorted(ref, v, side="right")
        return (lo + (hi - lo) / 2) / n
    return rank


def factor_scores(rows: dict, sp: set[str]) -> dict:
    """rows: {sym: {metric: value, 's': sector}} -> {sym: {fq, fg, fv, flv, fm}} (0-1)."""
    metrics = {k for f in FACTORS.values() for k, _ in f}
    rankers = {}
    for m in metrics:
        vals = [r[m] for s, r in rows.items() if s in sp and r.get(m) is not None and not (m == "de" and r.get("s") == "F")]
        rankers[m] = pct_ranker(vals) if len(vals) >= 50 else None
    out = {}
    for s, r in rows.items():
        sc = {}
        for fk, ms in FACTORS.items():
            ps = []
            for m, sign in ms:
                if m == "de" and r.get("s") == "F":
                    continue
                v = r.get(m)
                if v is None or rankers[m] is None:
                    continue
                p = rankers[m](v)
                ps.append(p if sign > 0 else 1 - p)
            sc[fk] = round(float(np.mean(ps)), 3) if len(ps) >= MIN_METRICS[fk] else None
        out[s] = sc
    return out


# ---------------------------------------------------------------- main
def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def country_he(c):
    if not c:
        return None
    if c in COUNTRY:
        return COUNTRY[c]
    return "אירופה" if c in EUROPE else c


def dmy(iso: str | None) -> str:
    return "" if not iso else f"{iso[8:10]}.{iso[5:7]}.{iso[2:4]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fund-budget", type=float, default=900, help="seconds for the fundamentals rotation")
    ap.add_argument("--fund-max", type=int, default=160, help="names refreshed per run at most")
    ap.add_argument("--offline", action="store_true", help="rebuild from the saved files, no network")
    a = ap.parse_args()

    ref = load_json(REF_PATH, None)
    prev = load_json(MARKET, {})
    fund = load_json(FUND, {}).get("items", {})
    sources, built = [], dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. ETF holdings
    got, meta_all = {}, {}
    if not a.offline:
        targets = SSGA_ETFS + ["QQQ", "CIBR"]
        for t in targets:
            r = None
            try:
                r, parse, src = fetch_raw(t)
                res = parse(r)
                if t == "SPY" and not 480 <= res["n"] <= 520:
                    raise ValueError(f"SPY has {res['n']} names")
                got[t] = (res, src)
                log(f"holdings {t}: {res['n']} names, as of {res['asof']}, raw weight sum {res['raw_sum']} ({src})")
            except Exception as e:
                log(f"holdings {t}: FAILED {type(e).__name__}: {str(e)[:160]}")
                if r is not None:
                    log("   " + preview(r)[:900])
                if t not in OPTIONAL:
                    sources.append({"key": "h_" + t, "name": f"החזקות {t}", "ok": False, "asOf": None,
                                    "msg": f"{type(e).__name__}: {str(e)[:90]}"})
    etf, prev_etf = {}, prev.get("ETF", {})
    known = set(ref["SEC"]) | set(got.get("SPY", ({"h": {}}, ""))[0]["h"])
    ndx, ndx_src = set(), None
    if not a.offline and "QQQ" not in got:     # no QQQ file: at least keep its member list current
        try:
            ndx, ndx_src = nasdaq100()
            ndx = {CLASS_MERGE.get(k, k) for k in canon_keys({k: 1.0 for k in ndx}, known)}
            log(f"nasdaq100: {len(ndx)} names ({ndx_src})")
        except Exception as e:
            log(f"nasdaq100: FAILED {type(e).__name__}: {str(e)[:120]}")
    for t, (res, src) in got.items():   # iShares writes BRKB for BRK-B: map such tickers onto the known ones
        res["h"] = canon_keys(res["h"], known)
        res["meta"] = canon_keys(res["meta"], known)
        for k, v in res["meta"].items():
            old = meta_all.get(k, {})
            meta_all[k] = {kk: old.get(kk) or v.get(kk) for kk in ("name", "s", "cu")}
    # wAt = the price date the weights belong to; weights that did not come fresh from the issuer are rolled forward
    # by price below, which is how an index's weights drift between its rebalances
    for t, m in ref["ETF"].items():
        e = {k: v for k, v in m.items() if k != "h"}
        pe_ = prev_etf.get(t, {})
        if t in got:
            res, src = got[t]
            e.update(h=res["h"], m="actual", asOf=res["asof"] or today_il(), wAt=res["asof"] or today_il(), stale=0, live=1,
                     src=f"{src} – קובץ ההחזקות היומי של המנפיק ({res['n']} רכיבים, נכון ל-{dmy(res['asof'])})")
            e.pop("res", None)
        elif pe_.get("h") and pe_.get("wAt") and t not in PROXY and t != "RSP":
            e.update({k: pe_[k] for k in ("h", "m", "src0", "asOf", "wAt", "res", "live") if k in pe_}, stale=1)
            if not pe_.get("res"):
                e.pop("res", None)
        else:
            e.update(h=m["h"], asOf=ref["asof_snapshot"], wAt=SNAP_PRICE_DATE, stale=1 if m["kind"] == "equity" and m["h"] else 0,
                     src0=m.get("src", ""))
        etf[t] = e

    for e in etf.values():
        if any(k in CLASS_MERGE for k in e.get("h", {})):
            h = {}
            for k, w in e["h"].items():
                kk = CLASS_MERGE.get(k, k)
                h[kk] = round(h.get(kk, 0.0) + w, 6)
            e["h"] = dict(sorted(h.items(), key=lambda x: -x[1]))

    # 2. universe: every stock in an ETF + the reference list (Tel Aviv-only names stay on the snapshot for now)
    in_etf = {k for e in etf.values() for k in e.get("h", {})}
    universe = sorted((in_etf | ndx | set(ref["SEC"])) - {k for k, v in ref["SEC"].items() if v.get("il")})
    log(f"universe: {len(universe)} names")

    # 3. prices
    px, close = {}, pd.DataFrame()
    if not a.offline:
        try:
            ys = {ysym(x): x for x in universe}
            close = yahoo_closes(list(ys) + (["SPY"] if "SPY" not in ys else []))
            close = close.rename(columns=ys)
            px = price_stats(close)
            sources.append({"key": "prices", "name": "מחירים, תשואה 12 ח׳ ובטא (Yahoo)", "ok": len(px) >= 0.9 * len(universe),
                            "asOf": max((v["d"] for v in px.values()), default=None), "msg": f"{len(px)}/{len(universe)} מניות"})
        except Exception as e:
            sources.append({"key": "prices", "name": "מחירים (Yahoo)", "ok": False, "asOf": None, "msg": f"{type(e).__name__}: {str(e)[:90]}"})
        log(f"prices: {len(px)} / {len(universe)}")
    if not px:
        px = load_json(FUND, {}).get("px", {})

    # 3b. roll the weights that are not fresh from the issuer, then the rule-based and proxy ETFs
    for t, e in etf.items():
        if e.get("stale") and e.get("h") and not close.empty:
            h2, to = roll_weights(e["h"], e["wAt"], close)
            if to and to > e["wAt"]:
                e.update(h=h2, wAt=to)
        if e.get("stale") and e.get("kind") == "equity" and e.get("h"):
            base = e.get("src0") or e.get("src", "")
            e["src0"] = base
            e["src"] = (base + f" · רשימת הרכיבים נכון ל-{dmy(e['asOf'])}, משקלים מגולגלים לפי מחירים עד {dmy(e['wAt'])}")
    spy = etf["SPY"]["h"]
    sp = set(spy)
    etf["RSP"].update(h={k: round(1 / len(spy), 6) for k in spy}, m="rule", asOf=etf["SPY"]["asOf"], wAt=etf["SPY"]["wAt"],
                      stale=etf["SPY"].get("stale", 0), live=etf["SPY"].get("live", 0),
                      src=f"שווה משקל על {len(spy)} רכיבי S&P 500 לפי SPY (שיטת המדד)")
    etf["RSP"].pop("res", None)
    for t, p in PROXY.items():
        etf[t].update(h=etf[p]["h"], m="proxy", asOf=etf[p]["asOf"], wAt=etf[p]["wAt"], stale=etf[p].get("stale", 0),
                      src=f"פירוק לפי {p} (אותו ענף GICS)")
        etf[t].pop("res", None)
    log(f"SPY: {len(sp)} names")

    # 4. fundamentals rotation
    if not a.offline:
        done, failed, errs = refresh_fundamentals(fund, universe, a.fund_budget, a.fund_max)
        have = sum(1 for s in universe if fund.get(s, {}).get("at") and "mcap" in fund.get(s, {}))
        oldest = min((fund[s]["at"] for s in universe if fund.get(s, {}).get("at")), default=None)
        sources.append({"key": "fund", "name": "נתונים פיננסיים לפקטורים (Yahoo)", "ok": have >= 0.85 * len(universe),
                        "asOf": today_il(), "msg": f"עודכנו {done}, נכשלו {failed} · יש נתונים ל-{have}/{len(universe)} · הישן ביותר {dmy(oldest)}"
                        + (f" · {'; '.join(errs[:3])}" if errs else "")})
        log(f"fundamentals: {done} refreshed, {failed} failed, {have}/{len(universe)} with data, oldest {oldest}; {errs[:4]}")

    # 4b. market caps quoted in another currency (Paris, Toronto listings) -> USD
    fx = {"USD": 1.0}
    curs = sorted({fund[x].get("cur") for x in universe if fund.get(x, {}).get("cur") not in (None, "USD")})
    if curs and not a.offline:
        pairs = {c: ("GBP" if c in ("GBp", "GBX") else c) + "USD=X" for c in curs}
        try:
            fxc = yahoo_closes(sorted(set(pairs.values())), days=20)
            for c, pr in pairs.items():
                if pr in fxc and fxc[pr].notna().any():
                    fx[c] = float(fxc[pr].dropna().iloc[-1]) / (100 if c in ("GBp", "GBX") else 1)
        except Exception as e:
            log(f"fx: {e}")
        log(f"fx: {fx}")

    # 5. per-stock records. Price metrics (beta, 12-month return) are fresh for every name with prices; the
    # fundamentals are Yahoo's when the rotation has read the name, else the 12.11.2026 snapshot (marked "snap").
    held_by = {}
    for t, e in etf.items():
        if e.get("m") != "proxy":
            for k in e.get("h", {}):
                held_by.setdefault(k, []).append(t)
    sec, rows = {}, {}
    for s in universe + [k for k, v in ref["SEC"].items() if v.get("il")]:
        r0, m0, f0, p0 = ref["SEC"].get(s, {}), meta_all.get(s, {}), fund.get(s, {}), px.get(s, {})
        snap = r0.get("snap", {})
        by = held_by.get(s, [])
        sl = (r0.get("s") or next((ETF_SECTOR[t] for t in by if t in ETF_SECTOR), None) or m0.get("s")
              or SECT.get(f0.get("ysec") or "") or "X")
        th = r0["th"] if "th" in r0 else sorted(set(AUTO_THEME.get(sl, []) + [ETF_THEME[t] for t in by if t in ETF_THEME]))
        rec = {"n": r0.get("n") or f0.get("name") or (m0.get("name") or s).title(), "s": sl,
               "c": r0.get("c") or country_he(f0.get("country")) or ('ארה"ב' if ysym(s) == s else "אירופה"),
               "th": th,
               "w": spy.get(s, 0.0), "sp": int(s in sp)}
        if not r0:
            rec["new"] = 1          # not in the reference list: themes need a manual tag
        if m0.get("cu"):
            rec["cu"] = m0["cu"]
        fresh = bool(f0.get("mcap")) and not r0.get("il")
        if fresh:
            k = (p0["px"] / f0["pxAt"]) if p0.get("px") and f0.get("pxAt") else 1.0
            if not 0.5 < k < 2:
                k = 1.0             # a split between the two reads: keep Yahoo's own figures
            cfx = fx.get(f0.get("cur") or "USD")
            if cfx is None:
                cfx = 1.0
                log(f"  {s}: no FX for {f0.get('cur')}, market cap left in local currency")
            mcu = f0["mcap"] * k * cfx
            rec["mc"] = round(mcu, 3 if mcu < 10 else 1)
            rec["pe"] = round(f0["pe"] * k, 1) if f0.get("pe") and f0["pe"] > 0 else None
            dyv = f0.get("dy")
            if dyv is not None and (dyv > 25 or (f0.get("dyF") and dyv > 3 * f0["dyF"] + 0.5)):
                dyv = f0.get("dyF")  # trailing yield in the wrong currency (some ADRs): Yahoo's own yield instead
            rec["dy"] = round(dyv / k, 2) if dyv else None
            fd = {kk: f0.get(kk) for kk in ("roe", "roa", "nm", "de", "pb", "s1", "s3", "e3")}
            if fd["s1"] is None and f0.get("qs1") is not None:
                fd["s1"] = f0["qs1"]
            rec["fa"] = f0["at"]
            rec["src"] = (("SSGA SPY " + dmy(etf["SPY"]["asOf"]) + " · ") if s in sp else "") + \
                f"Yahoo Finance: נתונים פיננסיים {dmy(f0['at'])}, מחיר {dmy(p0.get('d'))}"
        else:
            rec.update({kk: snap.get(kk) for kk in ("mc", "pe", "dy")})
            fd = dict(snap.get("fd") or {})
            if snap.get("nd") or rec.get("mc") is None:
                rec["nd"] = 1
            rec["src"] = (snap.get("src") + " · תמונת מצב 12.11.26") if snap.get("src") else "אין עדיין נתונים פיננסיים"
            rec["snap"] = 1
        if p0:
            fd.update(beta=p0.get("beta"), r1=p0.get("r1"))
            rec["pd"] = p0.get("d")
        rec["fd"] = {kk: (round(v, 2) if isinstance(v, float) else v) for kk, v in fd.items() if v is not None}
        if not rec["fd"]:
            rec.pop("fd")
        sec[s] = rec
        fdv = rec.get("fd", {})
        pe = rec.get("pe")
        ey = (1 / pe) if pe else (-0.05 if fresh and f0.get("eps") is not None and f0["eps"] < 0 else None)
        rows[s] = {"s": sl, "roe": fdv.get("roe"), "roa": fdv.get("roa"), "nm": fdv.get("nm"), "de": fdv.get("de"),
                   "s3": fdv.get("s3"), "s1": fdv.get("s1"), "e3": fdv.get("e3"), "ey": ey,
                   "dy": (rec.get("dy") or 0.0) if fresh else rec.get("dy"), "beta": fdv.get("beta"), "r1": fdv.get("r1")}
    for s, sc in factor_scores(rows, sp).items():
        sec[s].update(sc)

    # 5b. QQQ without its file: the current Nasdaq-100 members; members already listed keep their rolled weights,
    # new members get the weight their market cap implies at the median weight/cap ratio of the smaller members
    if ndx and etf["QQQ"].get("stale"):
        e = etf["QQQ"]
        h = {k: w for k, w in e["h"].items() if k in ndx}
        small = sorted((w / sec[k]["mc"]) for k, w in h.items() if sec.get(k, {}).get("mc") and w < 0.02)
        ratio = small[len(small) // 2] if small else None
        added = sorted(ndx - set(h))
        for k in added:
            mc = sec.get(k, {}).get("mc")
            h[k] = mc * ratio if (mc and ratio) else min(h.values())
        dropped = sorted(set(e["h"]) - ndx)
        tot = sum(h.values())
        e["h"] = {k: round(v / tot, 6) for k, v in sorted(h.items(), key=lambda x: -x[1])}
        e["src"] = (f"רשימת הרכיבים: {ndx_src} {dmy(today_il())} · משקלים: הקובץ האחרון מגולגל לפי מחירים עד {dmy(e['wAt'])}"
                    + (f" · נוספו {', '.join(added)} לפי שווי שוק" if added else "") + (f" · יצאו {', '.join(dropped)}" if dropped else ""))
        e["asOf"] = today_il()
        log(f"QQQ: {len(e['h'])} names, added {added}, dropped {dropped}")

    # 6. coverage and checks
    def cov(k):
        tot = sum(spy.values()) or 1
        return round(100 * sum(w for t, w in spy.items() if sec.get(t, {}).get(k) is not None) / tot, 1)
    fcov = {k: cov(k) for k in FACTORS}
    ss = {}
    for t, w in spy.items():
        ss[sec[t]["s"]] = round(ss.get(sec[t]["s"], 0) + w, 4)
    nfund = sum(1 for v in sec.values() if v.get("fa"))
    us_dates = sorted(v["d"] for v in px.values()) if px else []
    asof = us_dates[len(us_dates) // 2] if us_dates else prev.get("asof")
    stale_etf = [t for t, e in etf.items() if e.get("stale")]
    for e in etf.values():
        e.pop("src0", None) if not e.get("stale") else None
    sources.insert(0, {"key": "holdings", "name": "החזקות תעודות הסל (קובצי המנפיקים)", "ok": "SPY" in got and not [t for t in stale_etf if t in SSGA_ETFS],
                       "asOf": etf["SPY"]["asOf"], "msg": f"עודכנו {len(got)} תעודות" + (f" · ישנות: {', '.join(stale_etf)}" if stale_etf else "")})
    ok = all(x["ok"] for x in sources)
    market = {"_comment": "Built by tools/expo/build.py (see its docstring). Public market data only, no fund holdings.",
              "v": 1, "asof": asof, "built": built, "ok": ok, "sources": sources, "fcov": fcov, "nfund": nfund,
              "SS_SECT": ss, "SEC": sec, "ETF": etf}
    # sanity: SPY weights sum, factor coverage
    assert abs(sum(spy.values()) - 1) < 0.01, "SPY weights do not sum to 1"
    write(MARKET, market)
    keep = set(universe)
    fund = {k: v for k, v in fund.items() if k in keep or v.get("at", "") >= (dt.date.today() - dt.timedelta(days=30)).isoformat()}
    write(FUND, {"_comment": "Cache of tools/expo/build.py: fundamentals per symbol with the date read (items), last prices (px).",
                 "items": dict(sorted(fund.items())), "px": px})
    log(json.dumps({"asof": asof, "ok": ok, "fcov": fcov, "nfund": nfund, "stale": stale_etf,
                    "sources": [(x["key"], x["ok"], x["asOf"], x["msg"]) for x in sources]}, ensure_ascii=False))
    for t in ["AAPL", "NVDA", "MSFT", "AMZN", "LLY", "JPM", "XOM", "TSM"]:
        v = sec.get(t, {})
        log(f"  {t}: mc {v.get('mc')} pe {v.get('pe')} dy {v.get('dy')} " + " ".join(f"{k}={v.get(k)}" for k in FACTORS)
            + f" | snap " + " ".join(f"{k}={ref['SEC'].get(t, {}).get('snap', {}).get(k)}" for k in FACTORS))


def write(p: Path, obj: dict):
    """One entry per line for the big maps, so the nightly diffs stay readable."""
    def dl(o):
        return json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    parts = []
    for k, v in obj.items():
        if isinstance(v, dict) and len(v) > 30:
            inner = ",\n".join(dl(kk) + ":" + dl(vv) for kk, vv in v.items())
            parts.append(dl(k) + ":{\n" + inner + "\n}")
        else:
            parts.append(dl(k) + ":" + dl(v))
    p.write_text("{\n" + ",\n".join(parts) + "\n}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
