"""Candidate dates for the market-events catalogue (config/events.jsonl), for one month.

The charts put a dot on every significant peak or trough of an indicator (web: extremes(), EV_WIN): the highest or
lowest point within 63 daily / 13 weekly / 4 monthly observations on each side, and unusual for its time (5-year
rolling percentile >= 85 or <= 15). This lists, for the month asked, the dates where such dots fall (clustered
across indicators), the large index moves, and whether the catalogue already has an event near each date.

usage: python tools/event_candidates.py 2026-10
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIN = {"d": 63, "w": 13, "m": 4}
MOVES = {"^GSPC": ("S&P 500", 0.015), "^IXIC": ("נאסד\"ק", 0.02), "^SOX": ("מדד השבבים SOX", 0.035),
         "TA35.TA": ("ת\"א 35", 0.015), "^TA125.TA": ("ת\"א 125", 0.015), "^VIX": ("VIX", 0.15)}


def meta() -> dict:
    out = {}
    for f, key in (("indicators.json", "indicators"), ("macro.json", "series"), ("israel.json", "series")):
        p = ROOT / "config" / f
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        items = d if isinstance(d, list) else d.get(key) or d.get("items") or []
        for it in items:
            if isinstance(it, dict) and it.get("id"):
                out[it["id"]] = {"name": it.get("name", it["id"]), "freq": it.get("freq", "d")}
    return out


def read(p: Path) -> list[tuple[str, float]]:
    rows = []
    with p.open(encoding="utf-8") as fh:
        for r in csv.reader(fh):
            if r and r[0][:1].isdigit():
                try:
                    rows.append((r[0], float(r[1])))
                except (ValueError, IndexError):
                    pass
    return rows


def extremes(rows, freq):
    w, n = WIN.get(freq, 63), len(rows)
    vals = [v for _, v in rows]
    out = []
    for i, (d, x) in enumerate(rows):
        lo_k, hi_k = max(0, i - w), min(n - 1, i + w)
        win = vals[lo_k:hi_k + 1]
        is_hi, is_lo = x >= max(win), x <= min(win)
        if not (is_hi or is_lo):
            continue
        start = (date.fromisoformat(d) - timedelta(days=5 * 365)).isoformat()
        past = [v for dd, v in rows[:i] if dd >= start]
        if len(past) < 250 // (5 if freq == "w" else 21 if freq == "m" else 1):
            continue
        pct = 100 * sum(1 for v in past if v <= x) / len(past)
        if (is_hi and pct >= 85) or (is_lo and pct <= 15):
            out.append((d, "שיא" if is_hi else "שפל", x, round(pct)))
    return out


def main(month: str) -> None:
    m = meta()
    events = [json.loads(l) for l in (ROOT / "config" / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    lo = (date.fromisoformat(month + "-01") - timedelta(days=7)).isoformat()
    hi = month + "-31"
    by_day = defaultdict(list)
    for p in sorted((ROOT / "data" / "series").glob("*.csv")):
        sid = p.stem
        info = m.get(sid, {"name": sid, "freq": "d"})
        for d, kind, x, pct in extremes(read(p), info["freq"]):
            if lo <= d <= hi:
                by_day[d].append(f"{info['name']} ({sid}): {kind} {x:g}, אחוזון {pct}")
    # large index moves
    moves = defaultdict(list)
    px = ROOT / "data" / "prices" / "close.csv"
    if px.exists():
        with px.open(encoding="utf-8") as fh:
            rd = csv.reader(fh)
            head = next(rd)
            idx = {s: head.index(s) for s in MOVES if s in head}
            prev = {}
            for r in rd:
                d = r[0]
                for s, j in idx.items():
                    try:
                        v = float(r[j])
                    except (ValueError, IndexError):
                        continue
                    if s in prev and lo <= d <= hi:
                        ch = v / prev[s] - 1
                        if abs(ch) >= MOVES[s][1]:
                            moves[d].append(f"{MOVES[s][0]} {ch * 100:+.1f}%")
                    prev[s] = v

    def near(d):
        t = date.fromisoformat(d)
        return [e["title"] for e in events if abs((date.fromisoformat(e["date"]) - t).days) <= 5]

    days = sorted(set(by_day) | set(moves))
    print(f"# candidates {lo} .. {month} ({len(days)} dates)")
    for d in days:
        print(f"\n{d}  · {len(by_day.get(d, []))} indicator extremes" + (f" · moves: {', '.join(moves[d])}" if moves.get(d) else ""))
        for s in by_day.get(d, [])[:12]:
            print("   -", s)
        ex = near(d)
        print("   existing events within 5 days:", "; ".join(ex) if ex else "none")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m"))
