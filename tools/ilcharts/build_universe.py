"""Builds config/tase_all.json, the universe of the "גרפים - ישראל" charts: every share listed on the TASE.

Inputs (taken from market.tase.co.il by hand, see the header of each file):
  tools/ilcharts/tase_<date>.psv          every share: security number, symbol, Hebrew and English names, type
  tools/ilcharts/tase_sectors_<date>.psv  the TASE sector of each security number
The Yahoo symbol is the TASE symbol + ".TA"; for the TA-125 names the symbols that config/israel.json already uses come
first (they are the ones Yahoo answered for). Run again after replacing the two files with a newer list:
  python tools/ilcharts/build_universe.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = sorted((ROOT / "tools" / "ilcharts").glob("tase_2*.psv"))[-1]
SEC = sorted((ROOT / "tools" / "ilcharts").glob("tase_sectors_*.psv"))[-1]
OUT = ROOT / "config" / "tase_all.json"

TAIL = re.compile(r"\s+(ע''ש|ד|יהש|הש|ש|ה''ק|דס|-ש|-ס)$")
GLUED = re.compile(r"(יהש-ש|-ש|-ס)$")
TYPES = {"Ordinary Share": "", "Reit": "reit", "Participating unit": "pu", "Stock": ""}


def clean_name(n: str) -> str:
    """'מזרחי טפחות ע''ש' -> 'מזרחי טפחות', 'אורה סמארט-ש ש' -> 'אורה סמארט', 'גלוב יהש-ש ש הש' -> 'גלוב'."""
    n = n.strip()
    while True:
        m = GLUED.sub("", TAIL.sub("", n)).strip()
        if m == n:
            return n.replace("''", '"')
        n = m


def rows(path: Path) -> list[list[str]]:
    return [ln.split("|") for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def main() -> int:
    asof = re.search(r"(\d{4}-\d{2}-\d{2})", SRC.name).group(1)
    sector, groups = {}, {}
    for i, path, ids in rows(SEC):
        g, l1, leaf = path.split(">")
        groups[leaf] = {"g": g, "l1": l1}
        for sid in filter(None, ids.split(",")):
            sector[sid] = leaf
    il = json.loads((ROOT / "config" / "israel.json").read_text(encoding="utf-8"))
    ta125 = {}
    for alts, name, sec in il["stocks"]:
        a = alts.split("|")
        for y in a:
            ta125[y.removesuffix(".TA")] = (a, name)
    stocks, missing = [], []
    for sid, sym, he, he_sym, typ, turnover, en in rows(SRC):
        if sid not in sector:
            missing.append(sym)
        alts, name = ta125.get(sym, ([f"{sym}.TA"], clean_name(he)))
        if f"{sym}.TA" not in alts:
            alts = [f"{sym}.TA", *alts]
        flags = "".join(k for k, on in (("m", sym.endswith(("-M", "-L"))), ("s", " Sus" in en or " הש" in f" {he} "),
                                         ("d", " DL" in f" {en} "), ("i", sym in ta125)) if on)
        stocks.append({"y": "|".join(alts), "sym": sym, "name": name, "en": en.removesuffix(" MM").strip(),
                       "sec": sector.get(sid, ""), "id": int(sid), **({"t": TYPES[typ]} if TYPES.get(typ) else {}),
                       **({"f": flags} if flags else {})})
    stocks.sort(key=lambda s: s["name"])
    out = {"_comment": "Every share listed on the TASE, for the 'גרפים - ישראל' charts. Built by tools/ilcharts/build_universe.py "
                       "from the TASE lists next to it. y = Yahoo symbols to try in order; sec = TASE sub-sector; t = reit / pu "
                       "(participating unit); f = flags: m maintenance list, s suspended, d dual-listed, i in TA-125.",
           "asof": asof, "version": 1, "sectors": groups, "stocks": stocks}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0).replace("\n", "") + "\n", encoding="utf-8")
    # one stock per line keeps the diffs readable
    txt = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    txt = txt.replace('"stocks":[{', '"stocks":[\n{').replace("},{\"y\"", "},\n{\"y\"")
    OUT.write_text(txt + "\n", encoding="utf-8")
    print(f"{len(stocks)} stocks, {len(groups)} sectors, as of {asof}" + (f"; no sector: {missing}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
