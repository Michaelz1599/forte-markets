"""Build data/calendar/analysts.json from the raw text the collectors write (raw_*.txt, format in AGENT_TASK.md).

Per company:
  sites  one row per site: bullish (strong buy + buy), neutral (hold), bearish (sell + strong sell), price targets
  avg    the mean of the sites (counts and average target), the lowest low and highest high target
  camp   individual ratings, latest per firm in the last 12 months, by camp: count and mean target
  mult   multiples (P/E, forward P/E ...) for the "valuation" section when the market snapshot lacks them

Checks: a site's targets outside 0.4x-2.5x the price are dropped (stale page, other currency); Tel Aviv targets
written in shekels are moved to agorot; EXCLUDE lists site rows known to be in another currency or stale.
Usage:  python3 build_analysts.py [--asof YYYY-MM-DD] [--keep]   (--keep merges into the existing file)
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "data" / "calendar" / "analysts.json"

# (calendar key, site) rows not to use, with the reason (found while collecting; see the N lines of the raw files)
EXCLUDE = {
    ("ALC", "Investing.com"): "Investing.com shows the Swiss line in CHF",
    ("FNV", "Investing.com"): "Investing.com shows the Toronto line in CAD",
    ("BN", "Investing.com"): "Investing.com page is stale (rows to Feb 2026) and in CAD",
    ("B", "Investing.com"): "Investing.com targets far below the price, stale",
    ("PTNR", "Investing.com"): "Investing.com page contradicts itself",
    ("VYLR", "StockAnalysis"): "StockAnalysis forecast page is stale (3 analysts, targets far below the price)",
}

BULL = re.compile(r"strong[\s-]*buy|\bbuy\b|outperform|overweight|accumulate|positive|add\b|top pick|conviction buy", re.I)
BEAR = re.compile(r"strong[\s-]*sell|\bsell\b|underperform|underweight|reduce|negative", re.I)
NEUT = re.compile(r"hold|neutral|equal[\s-]*weight|market perform|sector perform|in[\s-]*line|peer perform|sector weight|mixed", re.I)


def num(x):
    if x is None:
        return None
    s = str(x).strip().replace("$", "").replace(",", "").replace("₪", "").replace("C$", "")
    if s.upper() in ("", "NA", "N/A", "—", "-"):
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([KMBT]?)", s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    return v * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]


def target(x):
    """'$132 → $125' keeps the new target."""
    parts = re.split(r"→|->", str(x))
    return num(parts[-1])


def camp_of(rating: str):
    r = rating or ""
    if BEAR.search(r):
        return "bear"
    if BULL.search(r):
        return "bull"
    if NEUT.search(r):
        return "neutral"
    return None


def firm_key(f: str) -> str:
    f = f.lower()
    f = re.sub(r"\b(securities|capital( markets)?|research|group|socgen|& co\.?|inc\.?|llc|financial|global|partners|bank|markets)\b", " ", f)
    f = f.replace("j.p.", "jp").replace("bofa", "bank of america").replace("bank of america", "bofa")
    return re.sub(r"[^a-z]", "", f)


def parse(paths):
    cos, cur = {}, None
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#") or len(line) < 3 or line[1] != " ":
                continue
            kind, rest = line[0], line[2:].strip()
            f = [x.strip() for x in rest.split("|")]
            if kind == "T":
                cur = {"key": f[0], "sym": f[1] if len(f) > 1 else None, "cur": (f[2] if len(f) > 2 else "USD").upper(),
                       "price": num(f[3]) if len(f) > 3 else None, "pdate": f[4] if len(f) > 4 and re.match(r"\d{4}-\d\d-\d\d", f[4] or "") else None,
                       "M": None, "S": [], "R": [], "N": []}
                cos[f[0]] = cur          # a later block for the same key replaces an earlier one
            elif cur is None:
                continue
            elif kind == "M":
                cur["M"] = f
            elif kind == "S":
                cur["S"].append(f)
            elif kind == "R":
                cur["R"].append(f)
            elif kind == "N":
                cur["N"].append(rest)
    return cos


def build_one(c, asof: str):
    key, price, ccy = c["key"], c["price"], c["cur"]
    tlv = ccy in ("ILA", "ILS")
    notes = []

    def fix_pt(v):
        """Tel Aviv: a target written in shekels next to an agorot price goes to agorot."""
        if v is None or not price:
            return v
        if ccy == "ILA" and 0.4 <= v * 100 / price <= 2.5 and not 0.4 <= v / price <= 2.5:
            return v * 100
        return v

    def ok_pt(v):
        return v is not None and (not price or 0.4 <= v / price <= 2.5)

    out = {"sym": c["sym"], "cur": ccy, "price": price, "priceDate": c["pdate"], "asof": asof}
    # multiples
    m = c["M"]
    if m:
        mult = {k: num(m[i]) if len(m) > i else None for i, k in enumerate(["mcap", "ev", "pe", "fpe", "ps", "pb", "evEbitda", "peg"])}
        mult = {k: v for k, v in mult.items() if v is not None and (k in ("mcap", "ev") or 0 < v < 1000)}
        if mult:
            mult.update({"src": m[8] if len(m) > 8 else "StockAnalysis", "url": m[9] if len(m) > 9 else None,
                         "cur": "ILS" if tlv else ccy, "asof": asof})
            out["mult"] = mult
    # sites
    sites = []
    for f in c["S"]:
        f = f + ["NA"] * (11 - len(f))
        src = f[0]
        if (key, src) in EXCLUDE:
            notes.append(EXCLUDE[(key, src)])
            continue
        sb, b, h, s, ss = (num(x) for x in f[3:8])
        lo, avg, hi = (fix_pt(num(x)) for x in f[8:11])
        row = {"src": src, "url": f[1] if f[1].startswith("http") else None, "asof": f[2] if re.match(r"\d{4}-\d\d-\d\d", f[2]) else None}
        if any(x is not None for x in (sb, b, h, s, ss)):
            row.update({"bull": (sb or 0) + (b or 0), "neutral": h or 0, "bear": (s or 0) + (ss or 0)})
        if ok_pt(avg):
            row.update({"ptAvg": avg, "ptLow": lo if ok_pt(lo) or (lo and lo <= avg) else None, "ptHigh": hi if hi and hi >= avg else None})
        elif avg is not None:
            notes.append(f"{src}: price target dropped (out of range against the price)")
        if "bull" in row or "ptAvg" in row:
            sites.append(row)
    if sites:
        cnt = [x for x in sites if "bull" in x]
        pts = [x for x in sites if "ptAvg" in x]
        mean = lambda a: round(sum(a) / len(a), 1) if a else None
        avg = {"bull": mean([x["bull"] for x in cnt]), "neutral": mean([x["neutral"] for x in cnt]), "bear": mean([x["bear"] for x in cnt]),
               "ptAvg": round(sum(x["ptAvg"] for x in pts) / len(pts), 2) if pts else None,
               "ptLow": min([x["ptLow"] for x in pts if x.get("ptLow") is not None], default=None),
               "ptHigh": max([x["ptHigh"] for x in pts if x.get("ptHigh") is not None], default=None)}
        if cnt:
            avg["n"] = round(avg["bull"] + avg["neutral"] + avg["bear"], 1)
            out["avg"] = avg
        out["sites"] = sites
    # camps from individual ratings
    cutoff = (dt.date.fromisoformat(asof) - dt.timedelta(days=365)).isoformat()
    latest = {}
    for f in c["R"]:
        f = f + ["NA"] * (5 - len(f))
        src, d, firm, rating, tg = f[:5]
        if (key, src) in EXCLUDE or not re.match(r"\d{4}-\d\d-\d\d", d or "") or d < cutoff:
            continue
        k = firm_key(firm)
        if not k:
            continue
        if k not in latest or d > latest[k]["d"]:
            latest[k] = {"d": d, "camp": camp_of(rating), "t": fix_pt(target(tg)), "src": src}
    if latest:
        camp, used, srcs = {}, 0, set()
        for side in ("bull", "neutral", "bear"):
            ts = [x["t"] for x in latest.values() if x["camp"] == side and ok_pt(x["t"])]
            camp[side] = {"n": len(ts), "pt": round(sum(ts) / len(ts), 2) if ts else None}
            used += len(ts)
        srcs = sorted({x["src"] for x in latest.values()})
        if used:
            camp.update({"ratings": used, "from": min(x["d"] for x in latest.values()), "src": " ו-".join(srcs)})
            out["camp"] = camp
    if c["N"] and not sites:
        out["note"] = "לא נמצא כיסוי אנליסטים פומבי לחברה הזו באתרים שנבדקו (StockAnalysis, Investing.com)."
    if notes:
        out["checks"] = sorted(set(notes))
    one = len(sites) == 1
    if one:
        out["flag"] = "אתר אחד בלבד"
    stale = [x["asof"] for x in sites if x.get("asof") and x["asof"] < (dt.date.fromisoformat(asof) - dt.timedelta(days=60)).isoformat()]
    if stale:
        out["flag"] = (out.get("flag", "") + (" · " if out.get("flag") else "") + "נתונים ישנים מחודשיים")
    return out


def main():
    asof = dt.date.today().isoformat()
    if "--asof" in sys.argv:
        asof = sys.argv[sys.argv.index("--asof") + 1]
    paths = sorted(glob.glob(str(HERE / "raw_*.txt")))
    cos = parse(paths)
    items = {}
    if "--keep" in sys.argv and OUT.exists():
        items = json.loads(OUT.read_text(encoding="utf-8")).get("items", {})
    for k, c in cos.items():
        items[k] = build_one(c, asof)
    data = {"asof": asof, "note": "דעות אנליסטים ומכפילים, ממוצע של כמה אתרים. נבנה ע\"י tools/calendar/analysts/build_analysts.py",
            "sources": ["StockAnalysis", "Investing.com"], "items": items}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with_avg = sum(1 for x in items.values() if x.get("avg"))
    with_mult = sum(1 for x in items.values() if x.get("mult"))
    print(f"{len(items)} companies · {with_avg} with analysts' views · {with_mult} with multiples -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
