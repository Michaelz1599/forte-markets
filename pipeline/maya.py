"""Israeli report dates and investor-call times from Maya (TASE disclosure system), for the economic calendar.

Maya's page "מועדי פרסום דוחות ושיחות ועידה" lists, per company and quarter, the report date ("פרסום דוחות") and
the conference calls ("שיחת ועידה", with a time in Israel or New York time), as the companies filed them.
Writes data/calendar/maya.json: {"asof", "events": [calendar events], "profiles": {...}}. The calendar merges these
into the weeks: an event the weekly build already has (same ticker and date) keeps its own data and only gains the
call time when it had none.
"""
from __future__ import annotations

import datetime as dt
import json

import requests

from .common import ROOT

CAL = ROOT / "data" / "calendar"
OUT = CAL / "maya.json"
URL = "https://maya.tase.co.il/api/v1/corporate-actions/financial-reports-schedule"
PAGE = "https://maya.tase.co.il/he/corporate-actions/financial-scheduled"
REPORT = "https://maya.tase.co.il/he/reports/"
HDR = {"Accept": "application/json, text/plain, */*", "Accept-Language": "he-IL", "Content-Type": "application/json",
       "Origin": "https://maya.tase.co.il", "Referer": PAGE,
       "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def fetch(max_pages: int = 30) -> list[dict]:
    s = requests.Session()
    try:
        s.get(PAGE, headers={k: v for k, v in HDR.items() if k in ("User-Agent", "Accept-Language")}, timeout=30)
    except Exception:
        pass
    rows = []
    for pn in range(1, max_pages + 1):
        r = s.post(URL, json={"pageSize": 20, "pageNumber": pn}, headers=HDR, timeout=30)
        r.raise_for_status()
        arr = r.json()
        if not isinstance(arr, list) or not arr:
            break
        rows += arr
        if len(arr) < 20:
            break
    return rows


def _t(x: str | None) -> str | None:
    """'08:30 AM' / '16:30' / '04:30 PM' -> 'HH:MM'."""
    if not x:
        return None
    x = x.strip().upper()
    for fmt in ("%I:%M %p", "%H:%M", "%H:%M:%S"):
        try:
            return dt.datetime.strptime(x[:8].strip(), fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def _he_date(d: str) -> str:
    days = "שני שלישי רביעי חמישי שישי שבת ראשון".split()
    t = dt.date.fromisoformat(d)
    return f"יום {days[t.weekday()]} {t.day}.{t.month}"


def build(rows: list[dict], tickers: dict[str, str]) -> dict:
    groups: dict[tuple, dict] = {}
    for x in rows:
        k = (x.get("companyId"), x.get("period"), x.get("year"))
        g = groups.setdefault(k, {"name": x.get("companyName") or "", "R": [], "C": []})
        kind = "R" if x.get("eventName") == "פרסום דוחות" else "C" if x.get("eventName") == "שיחת ועידה" else None
        if kind:
            g[kind].append({"d": (x.get("scheduledDate") or "")[:10], "t": _t(x.get("scheduledTime")),
                            "ny": str(x.get("timezone") or "") == "1", "rid": x.get("reportId")})
    events, profiles = [], {}
    for (cid, period, year), g in groups.items():
        if not g["R"] and not g["C"]:
            continue
        rep = sorted(g["R"], key=lambda r: r["d"])[0] if g["R"] else None
        date = rep["d"] if rep else sorted(c["d"] for c in g["C"])[0]
        ticker = tickers.get(str(cid)) or g["name"].strip()
        calls = sorted(g["C"], key=lambda c: (c["d"], not c["ny"]))
        ny = next((c for c in calls if c["ny"] and c["t"]), None)
        il = next((c for c in calls if not c["ny"] and c["t"]), None)
        main = ny or il
        call = {"time": None, "tz": None, "confirmed": True, "note": None, "webcast": None, "dial": None}
        if main and main["d"] == date:
            call["time"], call["tz"] = main["t"], "America/New_York" if main is ny else "Asia/Jerusalem"
            if ny and il and il["d"] == date:
                call["hebrewCallIL"] = il["t"]
        elif main:
            call["note"] = f"שיחת משקיעים ב{_he_date(main['d'])}, {main['t']} " + ("שעון ניו יורק" if main is ny else "שעון ישראל")
        else:
            call["note"] = "לא נרשמה שיחת משקיעים במאיה"
        session = "TBD"
        if ny and ny["d"] == date:
            h = int(ny["t"][:2])
            session = "BMO" if h < 12 else "AMC" if h >= 16 else "TBD"
        elif ny and ny["d"] > date:
            session = "AMC"
        rid = (rep or {}).get("rid") or next((c["rid"] for c in calls if c["rid"]), None)
        q = (period or "").replace("דוח רבעון ", "Q").replace("דוח שנתי", "FY").strip()
        events.append({
            "id": f"{ticker}-{date}", "ticker": ticker, "market": "IL", "date": date, "session": session,
            "period": f"{q} {year}".strip(), "status": "confirmed",
            "release": {"text": "שעת הפרסום לא צוינה במאיה" if rep else "מועד פרסום הדוח לא נרשם במאיה; רשומה שיחת ועידה"},
            "call": call, "links": {}, "maya": cid,
            "sources": [{"label": "מאיה · מועדי פרסום דוחות ושיחות ועידה", "url": f"{REPORT}{rid}" if rid else PAGE}]})
        if str(cid) not in tickers:
            profiles[ticker] = {"name": g["name"].strip(), "tags": ["TASE"], "country": "IL", "exchange": "TASE"}
    events.sort(key=lambda e: (e["date"], e["ticker"]))
    return {"events": events, "profiles": profiles}


def run() -> tuple[dict, str]:
    extra = json.loads((CAL / "extra.json").read_text(encoding="utf-8")) if (CAL / "extra.json").exists() else {}
    rows = fetch()
    if not rows:
        raise ValueError("Maya returned no rows")
    out = build(rows, {str(k): v for k, v in (extra.get("maya") or {}).items()})
    out = {"asof": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), **out}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    nxt = [e for e in out["events"] if e["date"] >= dt.date.today().isoformat()]
    return out, f"{len(out['events'])} דוחות ושיחות ועידה מתוזמנים ({len(nxt)} קדימה) · עד {max((e['date'] for e in out['events']), default='—')}"
