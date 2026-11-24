"""Marketing tab: housing, mortgages and the banks (sections "נדל"ן ומשכנתאות", "הבנקים" and the house-price stress test).

Everything here comes from the Bank of Israel's SDMX service (edge.boi.gov.il), flows found by tools/probe_housing.py:
  REAL_ES_DF   the CBS dwelling-price index (monthly; each month is the two-month window that starts in it), new
               dwellings and the six districts
  BIR_MRTG_99  new housing loans of the whole banking system each month: volume, average payment-to-income, interest
               rates, and the volume by LTV and by payment-to-income bracket
  BMB_99       the stock of housing loans: balance, 90+ days in arrears, bullet / balloon loans, loans in a grace period
  BFR_99       the banks' quarterly financial statements as reported to the Supervisor of Banks, per bank: net profit
               and credit-loss provision of the quarter, equity, ROE, credit, housing loans, credit to construction and
               to real-estate activity, risk-weighted assets and the CET1 ratio. The Bank of Israel loads a quarter a few
               weeks after the banks publish it; until then data/marketing/banks.json (written by the daily marketing task
               from the reports) supplies the newest quarter.
The data changes monthly or quarterly, so a run fetches it only when the stored file is older than REFRESH_H hours.
Output: data/derived/mkt_housing.json; marketing.build_payload() adds the hand-kept files and the insurers.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json

from .common import ROOT, dump_json, get, save_probe

OUT = ROOT / "data" / "derived" / "mkt_housing.json"
BOI = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS"
REFRESH_H = 10

BANKS = {"leumi": "10001", "poalim": "12001", "discount": "11001", "mizrahi": "20001", "fibi": "31001", "system": "99910"}
# FINREP item -> (field, divisor): flows in ILS millions, balances in ILS billions, ratios in % as published
BANK_ITEMS = {"486": ("ni", 1e3), "1134": ("llp", 1e3), "41": ("equity", 1e6), "24": ("loans", 1e6), "248": ("mortg", 1e6),
              "223": ("constr", 1e6), "228": ("re", 1e6), "354": ("rwa", 1e6), "327": ("roe", 1), "201": ("allow_r", 1),
              "202": ("npl_r", 1), "203": ("wo_r", 1), "355": ("cet1", 1)}
BANK_FROM = "2015-01-01"

PRICES = {"all": "IND_FLT_M", "new": "IND_FLT_NEW_M", "ta": "IND_FLT_TELAVIV_M", "center": "IND_FLT_CENTER_M",
          "jer": "IND_FLT_JERUSALEM_M", "haifa": "IND_FLT_HAIFA_M", "north": "IND_FLT_NORTH_M", "south": "IND_FLT_SOUTH_M"}
MR = "BNK_99034_LR_BIR_MRTG_"
MORTG = {"new": MR + "897", "new_sa": "BNK_99034_LM_BIR_MRTG_897_SA", "pti": MR + "155", "rate_fix": MR + "467", "rate_cpi": MR + "1485",
         "bullet": MR + "779"}
LTV = {"30": 887, "45": 878, "60": 869, "75": 860, "90": 851, "90+": 842}                       # new housing loans by LTV bracket
PTI = {"10": 161, "20": 160, "30": 815, "40": 806, "50": 159, "60": 158, "80": 157, "80+": 156}  # by payment-to-income bracket
BOOK = {"bal": "BNK_99034_LR_MRTG_OL_7", "arr90": "BNK_99034_LR_MRTG_OL_74", "bullet": "BNK_99034_LR_MRTG_OL_98",
        "grace": "BNK_99034_LR_MRTG_OL_93"}


def boi(flow: str, key: str, start: str = "2005-01-01") -> dict[str, float]:
    """One Bank of Israel series -> {period: value}; periods as published ("2026-08" monthly, "2026-Q2" quarterly)."""
    r = get(f"{BOI}/{flow}/1.0/{key}", params={"startperiod": start, "format": "csv"}, timeout=60, tries=2)
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        d, v = str(row.get("TIME_PERIOD") or "").strip(), row.get("OBS_VALUE")
        try:
            out[d] = float(v)
        except (TypeError, ValueError):
            continue
    if not out:
        save_probe(f"boi_{key}", r.text[:3000])
        raise ValueError(f"BOI {flow}/{key}: no rows")
    return dict(sorted(out.items()))


def _ser(d: dict, div: float = 1, nd: int = 3) -> dict:
    ks = sorted(d)
    return {"d": ks, "v": [round(d[k] / div, nd) for k in ks]}


def yoy(d: dict[str, float]) -> dict[str, float]:
    """12-month % change of a monthly series keyed "YYYY-MM"."""
    out = {}
    for k, v in d.items():
        y, m = int(k[:4]), int(k[5:7])
        b = d.get(f"{y - 1:04d}-{m:02d}")
        if b:
            out[k] = round((v / b - 1) * 100, 2)
    return out


def share(parts: dict[str, dict[str, float]], top: list[str]) -> dict[str, float]:
    """Share (%) of the brackets in `top` in the total of all brackets, month by month."""
    months = set.intersection(*(set(p) for p in parts.values())) if parts else set()
    out = {}
    for m in sorted(months):
        tot = sum(parts[k][m] for k in parts)
        if tot > 0:
            out[m] = round(sum(parts[k][m] for k in top) / tot * 100, 2)
    return out


def ratio(num: dict[str, float], den: dict[str, float]) -> dict[str, float]:
    return {k: round(num[k] / den[k] * 100, 3) for k in num if den.get(k)}


def fetch_prices() -> dict:
    raw = {k: boi("REAL_ES_DF", code, "1994-01-01") for k, code in PRICES.items()}
    out = {"all": _ser({k: v for k, v in raw["all"].items() if k >= "2005-01"}, 1, 1), "yoy": _ser(yoy(raw["all"]), 1, 2),
           "new_yoy": _ser(yoy(raw["new"]), 1, 2), "dist": {}}
    for k in ("ta", "center", "jer", "haifa", "north", "south"):
        y = yoy(raw[k])
        if y:
            last = max(y)
            out["dist"][k] = {"m": last, "yoy": y[last], "y5": round((raw[k][last] / raw[k][f"{int(last[:4]) - 5}{last[4:]}"] - 1) * 100, 1)
                              if f"{int(last[:4]) - 5}{last[4:]}" in raw[k] else None}
    return out


def fetch_mortgages() -> dict:
    m = {k: boi("BIR_MRTG_99", code, "2011-01-01") for k, code in MORTG.items()}
    ltv = {k: boi("BIR_MRTG_99", MR + str(c), "2011-01-01") for k, c in LTV.items()}
    pti = {k: boi("BIR_MRTG_99", MR + str(c), "2011-01-01") for k, c in PTI.items()}
    book = {k: boi("BMB_99", code, "2011-01-01") for k, code in BOOK.items()}
    lm = max(set.intersection(*(set(v) for v in ltv.values())))
    return {
        "new": _ser(m["new"], 1e3, 1), "new_sa": _ser(m["new_sa"], 1e3, 1),      # ILS millions a month
        "pti": _ser(m["pti"], 1, 2), "rate_fix": _ser(m["rate_fix"], 1, 2), "rate_cpi": _ser(m["rate_cpi"], 1, 2),
        "bullet_new": _ser(ratio(m["bullet"], m["new"]), 1, 2),                       # % of the month's new loans
        "ltv60": _ser(share(ltv, ["75", "90", "90+"]), 1, 2),                         # % of new loans with LTV above 60%
        "ltv_m": lm, "ltv_mix": {k: round(v.get(lm, 0) / 1e3, 1) for k, v in ltv.items()},   # ILS millions by LTV bracket, last month
        "pti40": _ser(share(pti, ["50", "60", "80", "80+"]), 1, 2),                   # % with payment-to-income above 40%
        "book": _ser(book["bal"], 1e6, 1),                                            # ILS billions
        "arr90": _ser(ratio(book["arr90"], book["bal"]), 1, 3),                       # % of the balance
        "bullet_book": _ser(ratio(book["bullet"], book["bal"]), 1, 2),
        "grace": _ser(ratio(book["grace"], book["bal"]), 1, 2),
    }


def fetch_banks() -> tuple[dict, list[str]]:
    out, miss = {}, []
    for b, code in BANKS.items():
        rec = {}
        for item, (field, div) in BANK_ITEMS.items():
            try:
                rec[field] = _ser(boi("BFR_99", f"BNK_{code}_FR_FINREP_{item}", BANK_FROM), div, 3)
            except Exception as e:
                miss.append(f"{b}/{field}")
                print("housing: bank series failed", b, field, e)
        if rec:
            out[b] = rec
    return out, miss


def _age_h(path) -> float | None:
    try:
        a = json.loads(path.read_text(encoding="utf-8")).get("asof")
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(a)).total_seconds() / 3600
    except Exception:
        return None


def update(force: bool = False) -> tuple[dict, str]:
    """Refresh the housing / mortgage / bank series (at most every REFRESH_H hours). Returns (payload, message)."""
    age = _age_h(OUT)
    if not force and age is not None and age < REFRESH_H:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        return old, f"נשמר מריצה קודמת ({age:.0f} שעות); מתעדכן פעם ב-{REFRESH_H} שעות"
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    out, msgs = {"asof": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")}, []
    for key, fn in (("prices", fetch_prices), ("mortg", fetch_mortgages)):
        try:
            out[key] = fn()
        except Exception as e:
            msgs.append(f"{key}: {type(e).__name__} {str(e)[:80]}")
            if key in old:
                out[key] = old[key]
    banks, miss = fetch_banks()
    out["banks"] = banks or old.get("banks", {})
    if not banks:
        msgs.append("בנקים: אף סדרה לא התקבלה")
    elif miss:
        msgs.append(f"בנקים: חסרות {len(miss)} סדרות ({', '.join(miss[:5])})")
    if "prices" not in out and "mortg" not in out and not out["banks"]:
        raise ValueError("; ".join(msgs) or "no data")
    dump_json(OUT, out)
    p = (out.get("prices") or {}).get("yoy") or {}
    mg = (out.get("mortg") or {}).get("new") or {}
    q = ((out.get("banks") or {}).get("system") or {}).get("llp") or {}
    head = [f"מחירי דירות עד {p['d'][-1]}" if p.get("d") else "", f"משכנתאות עד {mg['d'][-1]}" if mg.get("d") else "",
            f"בנקים עד {q['d'][-1]}" if q.get("d") else ""]
    return out, " · ".join([h for h in head if h] + msgs)


def last_period(out: dict) -> str | None:
    ds = [s["d"][-1] for s in (((out.get("mortg") or {}).get("new") or {}), ((out.get("prices") or {}).get("yoy") or {})) if s.get("d")]
    return max(ds) if ds else None
