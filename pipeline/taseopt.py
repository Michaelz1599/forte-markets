"""Implied move for Israeli reports from the options on the stock traded on the Tel Aviv exchange.

TASE lists options on about 22 large stocks (Teva, Nice, the banks, Bezeq, ICL, Elbit and others). Globes publishes
every series with its closing price: https://www.globes.co.il/portal/quotes/stock-options/?baseid=<id>&showAll=true
Series names look like TVA-C013500M611: call, strike 135.00 shekels, expiry November 2026 (M + last digit of the year +
month). Prices are in agorot per contract; the contract size differs between stocks and is inferred from put-call parity.

implied move = (call + put) at the strike where the two are closest (at the money) / the stock price, for the first
expiry after the reaction day; the stock price is inferred from put-call parity at that strike (S = K + C - P).
These series rarely trade: the closing price is the exchange's, mostly without a trade that day, so the result is shown
with that caveat and only when both legs have a price and the result is plausible.
"""
from __future__ import annotations

import datetime as dt
import html
import math
import re

import requests

URL = "https://www.globes.co.il/portal/quotes/stock-options/"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
       "Accept-Language": "he-IL,he;q=0.9,en;q=0.8"}
# Globes underlying id -> (ticker in the calendar, Hebrew names to match Maya's company names)
UNDER = {
    "883": ("TEVA", ["טבע"]), "628": ("NICE", ["נייס"]), "400": ("ICL", ["איי.סי.אל", "כיל"]), "120": ("BEZQ", ["בזק"]),
    "267": ("ESLT", ["אלביט מערכות"]), "501": ("LUMI", ["לאומי"]), "706": ("POLI", ["פועלים", "הפועלים"]),
    "243": ("DSCT", ["דיסקונט"]), "590": ("MZTF", ["מזרחי טפחות", "מזרחי"]), "426": ("FIBI", ["בינלאומי", "הבינלאומי"]),
    "45548": ("AZRG", ["עזריאלי קבוצה", "עזריאלי"]), "566": ("MLSR", ["מליסרון"]), "3692": ("PTNR", ["פרטנר"]),
    "27648": ("CEL", ["סלקום"]), "378": ("HARL", ["הראל השקעות", "הראל"]), "437": ("ILCO", ["חברה לישראל"]),
    "236": ("DLEKG", ["דלק קבוצה"]), "231": ("NWMD", ["ניו-מד אנרג יהש", "ניו-מד"]), "440": ("ISRA", ["ישראמקו"]),
    "22855": ("PZOL", ["פז אנרגיה", "פז"]), "277": ("STRS", ["שטראוס"]), "338": ("GCT", ["ג'י סיטי"]),
}
SERIES = re.compile(r"-([CP])(\d+(?:\.\d+)?)M(\d)(\d\d)\b")


def match(ev: dict) -> str | None:
    """Globes underlying id for a calendar event (by ticker, or by the Hebrew name Maya uses)."""
    t = (ev.get("ticker") or "").strip()
    for bid, (tk, names) in UNDER.items():
        if t == tk or any(t == n or t.startswith(n) for n in names):
            return bid
    return None


def last_thursday(y: int, m: int) -> dt.date:
    d = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    while d.weekday() != 3:
        d -= dt.timedelta(days=1)
    return d


def _num(s: str) -> float | None:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def fetch(bid: str, s: requests.Session | None = None) -> list[dict]:
    r = (s or requests).get(URL, params={"baseid": bid, "showAll": "true"}, headers=HDR, timeout=30)
    r.raise_for_status()
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, flags=re.S | re.I):
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]
        if len(cells) < 6:
            continue
        m = SERIES.search(cells[0])
        if not m:
            continue
        k = m.group(2)
        strike = float(k) if "." in k else int(k) / 100.0
        price = _num(cells[2])
        if not price or price <= 0:
            continue
        rows.append({"cp": m.group(1), "k": strike, "y": 2020 + int(m.group(3)), "m": int(m.group(4)), "px": price,
                     "traded": cells[5].strip() not in ("-", "", "0")})
    return rows


def implied(rows: list[dict], react: str) -> dict | None:
    r = dt.date.fromisoformat(react)
    exps = sorted({(x["y"], x["m"]) for x in rows}, key=lambda t: t)
    exps = [e for e in exps if last_thursday(*e) >= r]
    if not exps:
        return None
    y, m = exps[0]
    calls = {x["k"]: x for x in rows if (x["y"], x["m"]) == (y, m) and x["cp"] == "C"}
    puts = {x["k"]: x for x in rows if (x["y"], x["m"]) == (y, m) and x["cp"] == "P"}
    ks = sorted(set(calls) & set(puts), key=lambda k: abs(calls[k]["px"] - puts[k]["px"]))
    if not ks:
        return None
    # contract size differs between stocks: C - P = (S - K) x size x 100 agorot, so the slope of C - P over the strikes
    # gives the size (in agorot per shekel of strike), and the intercept the stock price
    both = sorted(set(calls) & set(puts))
    if len(both) < 3:
        return None
    xs = both
    ys = [calls[k]["px"] - puts[k]["px"] for k in xs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    unit = -slope                      # agorot per contract for one shekel of the underlying
    if unit <= 0:
        return None
    unit = min((1, 10, 100, 1000, 10000), key=lambda u: abs(math.log(unit / u)))   # 100 agorot x 1/10/100/... shares
    k = ks[0]
    c, p = calls[k]["px"] / unit, puts[k]["px"] / unit
    spot = k + c - p
    if spot <= 0:
        return None
    move = (c + p) / spot
    exp = last_thursday(y, m)
    dte = max(1, (exp - dt.date.today()).days)
    if not (0.005 < move < 0.4):
        return None
    iv = (c + p) / (0.8 * spot * math.sqrt(dte / 365.0))     # Brenner-Subrahmanyam approximation for the ATM straddle
    return {"move": round(move, 4), "spot": round(spot, 2), "strike": k, "exp": exp.isoformat(), "dte": dte,
            "iv": round(iv, 3), "listing": "TASE", "cur": "ILS", "traded": bool(calls[k]["traded"] or puts[k]["traded"]),
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")}
