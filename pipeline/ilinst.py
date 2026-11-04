"""Institutional buying and selling in the TA-35 stocks, day by day: actual trades of Israeli institutions
(mutual funds, provident and pension funds, and others), as published by Funder ("מחזורי מוסדיים", beta):
https://www.funder.co.il/tStockList and, per stock, https://www.funder.co.il/tStock/<TASE security number>/t/<start date>

Keeps the history in data/derived/il_inst.json and returns, per stock and in total, the net buying of the last
1/5/20/60 sessions and its split between the institution types.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import time

import requests

from .common import ROOT

OUT = ROOT / "data" / "derived" / "il_inst.json"
BASE = "https://www.funder.co.il"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
       "Accept-Language": "he-IL,he;q=0.9,en;q=0.8"}
# TASE security number -> Yahoo symbol of the Israel tab (TA-35)
SEC = {"1082379": "TSEM", "1081124": "ESLT", "604611": "LUMI", "691212": "DSCT", "662577": "POLI", "1119478": "AZRG",
       "273011": "NICE", "323014": "MLSR", "1097260": "BIG", "593038": "FIBI", "1084128": "DLEKG", "746016": "STRS",
       "475020": "NWMD", "720011": "ENLT", "230011": "BEZQ", "1134402": "ORA", "1141571": "OPCE", "777037": "SAE",
       "1133875": "SPEN", "1090315": "DIMRI", "1095264": "CAMT", "585018": "HARL", "695437": "MZTF", "281014": "ICL",
       "767012": "PHOE", "1084557": "NVMI", "629014": "TEVA"}   # read off the list page on 4.11.2026; others by name


def _norm(s: str) -> str:
    s = re.sub(r"\s+(א|יהש|בע\"מ)$", "", s.strip())
    return re.sub(r"[\s\-\.\"'״׳]", "", s).replace("קבוצה", "").replace("השקעות", "")
KINDS = (("tStockData", "all"), ("tStockDataB", "mf"), ("tStockDataC", "pen"), ("tStockDataD", "oth"))


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def parse_list(text: str) -> tuple[str | None, list[dict]]:
    m = re.search(r"תאריך עדכון אחרון\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})", text)
    asof = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None
    tbl = re.search(r"<table.*?</table>", text, flags=re.S | re.I)
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl.group(0) if tbl else "", flags=re.S | re.I):
        sec = re.search(r"tStock/(\d+)/", tr)
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        if not sec or len(cells) < 6:
            continue
        rows.append({"id": sec.group(1), "name": re.sub(r"\s+", " ", cells[0]), "buy": _num(cells[1]), "sell": _num(cells[2]),
                     "turn": _num(cells[5])})
    return asof, rows


def parse_stock(text: str) -> dict[str, dict[str, list]]:
    """{kind: {"d": [...], "buy": [...], "sell": [...]}} from the page's embedded chart data."""
    out = {}
    for var, kind in KINDS:
        m = re.search(r"var\s+" + var + r"\s*=\s*(\{.*?\})\s*;?\s*\n", text) or re.search(r"var\s+" + var + r"\s*=\s*(\{.*?\});", text)
        if not m:
            continue
        try:
            cols = {c[0]: c[1:] for c in json.loads(m.group(1)).get("columns", [])}
        except ValueError:
            continue
        if "day" in cols and "buy" in cols and "sell" in cols:
            out[kind] = {"d": cols["day"], "buy": [_num(x) or 0.0 for x in cols["buy"]], "sell": [_num(x) or 0.0 for x in cols["sell"]]}
    return out


def run(names: dict[str, str] | None = None) -> tuple[dict, str]:
    s = requests.Session()
    r = s.get(f"{BASE}/tStockList", headers=HDR, timeout=30)
    r.raise_for_status()
    asof, rows = parse_list(r.text)
    if not rows:
        raise ValueError("Funder: no rows in the institutional trading table")
    store = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"stocks": {}}
    today = dt.date.today()
    n_new = 0
    for row in rows:
        sym = SEC.get(row["id"])
        if not sym and names:
            key = _norm(row["name"])
            sym = next((v for k, v in names.items() if _norm(k) == key), None)
        if not sym:
            continue
        row["sym"] = sym
        cur = store["stocks"].get(sym) or {"id": row["id"], "name": row["name"], "d": [], "all": [], "mf": [], "pen": [], "oth": [], "buy": [], "sell": []}
        start = (today - dt.timedelta(days=400 if len(cur["d"]) < 100 else 45))
        try:
            p = s.get(f"{BASE}/tStock/{row['id']}/t/{start.year}-{start.month}-{start.day}", headers=HDR, timeout=30)
            p.raise_for_status()
            data = parse_stock(p.text)
        except Exception:
            data = {}
        time.sleep(0.3)
        if "all" not in data:
            continue
        by_day = {d: i for i, d in enumerate(cur["d"])}
        for i, d in enumerate(data["all"]["d"]):
            vals = {"buy": data["all"]["buy"][i], "sell": data["all"]["sell"][i]}
            vals["all"] = vals["buy"] - vals["sell"]
            for k in ("mf", "pen", "oth"):
                x = data.get(k)
                vals[k] = (x["buy"][i] - x["sell"][i]) if x and i < len(x["d"]) and x["d"][i] == d else None
            if d in by_day:
                j = by_day[d]
            else:
                for key in ("d", "all", "mf", "pen", "oth", "buy", "sell"):
                    cur[key].append(None)
                j = len(cur["d"]) - 1
                cur["d"][j] = d
                n_new += 1
            for key in ("all", "mf", "pen", "oth", "buy", "sell"):
                cur[key][j] = None if vals[key] is None else round(vals[key])
        order = sorted(range(len(cur["d"])), key=lambda i: cur["d"][i])[-300:]
        for key in ("d", "all", "mf", "pen", "oth", "buy", "sell"):
            cur[key] = [cur[key][i] for i in order]
        cur["name"] = row["name"]
        store["stocks"][sym] = cur
    store["asof"] = max((v["d"][-1] for v in store["stocks"].values() if v["d"]), default=asof)
    store["unmapped"] = [r["name"] for r in rows if not r.get("sym")]
    OUT.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return store, f"{len(store['stocks'])} מניות ת\"א 35 · עד {store['asof']}" + (f" · בלי מיפוי: {', '.join(store['unmapped'][:5])}" if store["unmapped"] else "")


def payload(store: dict, turnover: dict[str, float] | None = None) -> dict:
    """Net institutional buying (shekels, millions) over 1/5/20/60 sessions, per stock and in total."""
    turnover = turnover or {}
    days = sorted({d for v in store.get("stocks", {}).values() for d in v["d"]})
    stocks = []
    for sym, v in store.get("stocks", {}).items():
        idx = {d: i for i, d in enumerate(v["d"])}
        row = {"sym": sym, "name": v["name"]}
        for n in (1, 5, 20, 60):
            sel = [idx[d] for d in days[-n:] if d in idx]
            for k in ("all", "mf", "pen", "oth"):
                xs = [v[k][i] for i in sel if v[k][i] is not None]
                row[f"{k}{n}"] = round(sum(xs) / 1e6, 1) if xs else None
            bs = [v["buy"][i] + v["sell"][i] for i in sel if v["buy"][i] is not None]
            row[f"gross{n}"] = round(sum(bs) / 1e6, 1) if bs else None
        t = turnover.get(sym)
        row["turnDay"] = round(t, 1) if t else None
        stocks.append(row)
    tot = []
    for d in days[-120:]:
        xs = [v["all"][v["d"].index(d)] for v in store["stocks"].values() if d in v["d"] and v["all"][v["d"].index(d)] is not None]
        tot.append(round(sum(xs) / 1e6, 1) if xs else None)
    return {"asof": store.get("asof"), "stocks": stocks, "hist": {"d": days[-120:], "net": tot}, "src": f"{BASE}/tStockList"}
