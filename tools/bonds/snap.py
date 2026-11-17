"""Weekly price snapshot for the bond-pairs dashboard ("ניתוח אג"ח").

Prices every corporate bond of data/bonds/base.json and every government bond of its "gov" list from TheMarker
(the dashboard's source), falling back to Bizportal for an id TheMarker does not answer. Writes
data/bonds/snap/<date>.json and data/bonds/latest.json in the dashboard's snapshot format:
    {"d": date, "q": {id: [ytm %, duration, last price, "HH:MM"]}, "src": ..., "at": ..., "stats": {...}}
A run that prices too few bonds writes only data/bonds/status.json and exits non-zero, so a bad week never
replaces a good snapshot.

    python tools/bonds/snap.py [--ids 1196542,1211770]   # --ids: a quick test on a few ids, writes nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as htmllib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "bonds"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TZ = ZoneInfo("Asia/Jerusalem")
NUM = re.compile(r"-?\d[\d,]*\.?\d*")

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "he-IL,he;q=0.9,en;q=0.5"})


def strip(h: str) -> str:
    h = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", h)
    h = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", htmllib.unescape(h))


def num_after(text: str, label: str, span: int = 160) -> float | None:
    i = text.find(label)
    if i < 0:
        return None
    m = NUM.search(text[i + len(label): i + len(label) + span])
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


def parse_date(s: str) -> dt.date | None:
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", s or "")
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def near_raw(h: str, label: str) -> float | None:
    """Same parsing as the dashboard's browser snippet: first occurrence of the label in the raw page, then the
    first number in the next 400 characters once tags are stripped."""
    i = h.find(label)
    if i < 0:
        return None
    seg = re.sub(r"<style[\s\S]*?</style>", " ", h[i + len(label): i + len(label) + 400])
    seg = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg).replace("&quot;", '"'))
    m = re.search(r"-?\d[\d.,]*", seg)
    try:
        return float(m.group(0).replace(",", "").rstrip(".")) if m else None
    except ValueError:
        return None


def themarker(bid: str) -> dict | None:
    r = S.get(f"https://finance.themarker.com/bond/{bid}", timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    h = r.text
    i = h.find("נכון ל")
    m = re.search(r"נכון ל:?\s*([\d.]+),?\s*([\d:]*)", strip(h[i:i + 200])) if i >= 0 else None
    asof, tm = (parse_date(m.group(1)), m.group(2)[:5]) if m else (None, "")
    mh = "מח&quot;מ" if "מח&quot;מ" in h else 'מח"מ'
    ytm, dur, last = near_raw(h, "תשואה לפדיון"), near_raw(h, mh), near_raw(h, "שער אחרון")
    if ytm is None or not dur or dur <= 0:
        return None
    return {"ytm": ytm, "dur": dur, "last": last, "tm": tm, "asof": asof, "src": "TM"}


def bizportal(bid: str) -> dict | None:
    r = S.get(f"https://www.bizportal.co.il/bonds/quote/bondsdata/{bid}", timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    t = strip(r.text)
    m = re.search(r"נכון ל:?\s*(\d{1,2}/\d{1,2}/\d{4})", t)
    asof = parse_date(m.group(1)) if m else None
    ytm, dur = num_after(t, "ברוטו להחזקה", 40), num_after(t, 'מח"מ', 40)
    if ytm is None or not dur or dur <= 0:
        return None
    return {"ytm": ytm, "dur": dur, "last": None, "tm": "", "asof": asof, "src": "BZ"}


def price(bid: str) -> tuple[str, dict | None, str]:
    err = ""
    for fn in (themarker, bizportal):
        for attempt in range(2):
            try:
                v = fn(bid)
                if v:
                    return bid, v, ""
                err = f"{fn.__name__}: no yield/duration"
                break
            except Exception as e:  # network or parse error: retry once, then the next source
                err = f"{fn.__name__}: {type(e).__name__} {str(e)[:60]}"
                time.sleep(2 + attempt * 3)
    return bid, None, err


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="comma-separated ids for a quick test (prints, writes nothing)")
    a = ap.parse_args()
    base = json.loads((DATA / "base.json").read_text(encoding="utf-8"))
    corp = sorted(base["bonds"])
    gov = sorted(base["gov"])
    ids = a.ids.split(",") if a.ids else corp + gov
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(price, ids))
    now = dt.datetime.now(TZ)
    today = now.date()
    q, src, stale, miss, errs = {}, {}, [], [], {}
    for bid, v, err in res:
        if not v:
            miss.append(bid)
            errs[bid] = err
            continue
        if v["asof"] and (today - v["asof"]).days > 7:
            stale.append(bid)
            continue
        q[bid] = [round(v["ytm"], 3), round(v["dur"], 3), v["last"], v["tm"]]
        src[bid] = v["src"]
    if a.ids:
        for bid, v, err in res:
            print(bid, v, err)
        return 0
    n_corp = sum(1 for k in corp if k in q)
    n_gov = sum(1 for k in gov if k in q)
    stats = {"corp": n_corp, "corp_total": len(corp), "gov": n_gov, "gov_total": len(gov), "stale": len(stale),
             "missing": len(miss), "bizportal": sum(1 for v in src.values() if v == "BZ")}
    d = today.isoformat()
    ok = n_corp >= 0.8 * len(corp) and n_gov >= 20
    status = {"d": d, "at": now.strftime("%Y-%m-%d %H:%M"), "ok": ok, "stats": stats,
              "errors": dict(list(errs.items())[:15])}
    (DATA / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    if not ok:
        print("::error::too few bonds priced; snapshot not written")
        return 1
    snap = {"d": d, "q": q, "src": "TheMarker (מחיר אחרון)" + (f"; {stats['bizportal']} מביזפורטל" if stats["bizportal"] else ""),
            "at": now.strftime("%Y-%m-%d %H:%M"), "stats": stats, "srcById": {k: v for k, v in src.items() if v != "TM"}}
    body = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    (DATA / "snap" / f"{d}.json").write_text(body, encoding="utf-8")
    (DATA / "latest.json").write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
