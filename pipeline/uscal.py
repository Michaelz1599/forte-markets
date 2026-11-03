"""US earnings dates from Nasdaq's earnings calendar, for the economic calendar: every company with market cap >= $10B,
from the Monday of the current week to two weeks ahead (and back to the previous Monday), with BMO/AMC and the EPS
consensus. Writes data/calendar/nasdaq.json {"asof", "events"}; the calendar adds only companies the weekly build does
not have (same id TICKER-YYYY-MM-DD), so it fills gaps between weekly builds and when a weekly run fails.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time

import requests

from .common import ROOT

CAL = ROOT / "data" / "calendar"
OUT = CAL / "nasdaq.json"
URL = "https://api.nasdaq.com/api/calendar/earnings"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
       "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
       "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/market-activity/earnings"}
MIN_CAP = 10e9


def _num(s) -> float | None:
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def fetch_day(s: requests.Session, d: str) -> list[dict]:
    r = s.get(URL, params={"date": d}, headers=HDR, timeout=30)
    r.raise_for_status()
    rows = ((r.json() or {}).get("data") or {}).get("rows") or []
    return rows


def run() -> tuple[dict, str]:
    today = dt.date.today()
    mon = today - dt.timedelta(days=today.weekday())
    days = [mon - dt.timedelta(days=7) + dt.timedelta(days=i) for i in range(28)]
    days = [d for d in days if d.weekday() < 5]
    s = requests.Session()
    events, n_days = [], 0
    for d in days:
        try:
            rows = fetch_day(s, d.isoformat())
        except Exception:
            continue
        n_days += 1
        for x in rows:
            cap = _num(x.get("marketCap"))
            sym = (x.get("symbol") or "").strip().upper()
            if not sym or not cap or cap < MIN_CAP or not re.fullmatch(r"[A-Z.\-]{1,6}", sym):
                continue
            t = (x.get("time") or "")
            sess = "BMO" if "pre" in t else "AMC" if "after" in t else "TBD"
            ev = {"id": f"{sym.replace('.', '-')}-{d.isoformat()}", "ticker": sym.replace(".", "-"), "market": "US", "date": d.isoformat(),
                  "session": sess, "period": (x.get("fiscalQuarterEnding") or "").strip(), "status": "listed",
                  "release": {"text": {"BMO": "before market open", "AMC": "after market close"}.get(sess, "שעה לא צוינה"), "tz": "America/New_York"},
                  "call": {"time": None, "tz": "America/New_York", "confirmed": False, "note": "שעת השיחה לא נאספה (לוח Nasdaq)", "webcast": None, "dial": None},
                  "links": {}, "nasdaq": True, "mcap": cap, "name": (x.get("name") or "").strip(),
                  "sources": [{"label": "Nasdaq · Earnings Calendar", "url": f"https://www.nasdaq.com/market-activity/earnings"}]}
            eps = _num(x.get("epsForecast"))
            if eps is not None:
                ev["consensus"] = {"period": "רבעון נוכחי", "eps": eps, "epsN": _num(x.get("noOfEsts")), "source": "Nasdaq (Zacks)", "quality": "normal"}
            events.append(ev)
        time.sleep(0.4)
    if not n_days:
        raise ValueError("Nasdaq earnings calendar unreachable")
    events.sort(key=lambda e: (e["date"], -(e["mcap"] or 0)))
    out = {"asof": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "events": events}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    return out, f"{len(events)} דוחות של חברות מעל 10 מיליארד דולר · {n_days} ימי מסחר · {days[0]} עד {days[-1]}"
