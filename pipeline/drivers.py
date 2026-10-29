"""What drives inflation: each CPI component's contribution to the yearly inflation rate, US and Israel.

contribution = basket weight x the component's yearly change. Weights are the latest published baskets
(BLS relative importance, December 2025; CBS basket of January 2025), applied to the whole history, so
older years are approximate. The sum of the parts is shown next to the published headline rate.
"""
from __future__ import annotations

import io
import csv

import pandas as pd

from .common import ROOT, get, save_probe

OUT = ROOT / "data" / "derived" / "cpi_drivers.json"

# FRED series, seasonally adjusted; weights in % of the CPI (BLS relative importance, Dec 2025)
US_PARTS = [
    ("shelter", "דיור", "CUSR0000SAH1", 35.625),
    ("svc", "שירותים ללא דיור ואנרגיה", None, 25.119),      # services less energy services, minus shelter
    ("goods", "מוצרים ללא מזון ואנרגיה", "CUSR0000SACL1E", 19.176),
    ("food", "מזון", "CPIUFDSL", 13.698),
    ("energy", "אנרגיה", "CPIENGSL", 6.383),
]
US_SERVICES = ("CUSR0000SASLE", 60.744)
US_HEADLINE = "CPIAUCSL"

# CBS price-index codes and weights (per 1000) of the January 2025 basket
IL_PARTS = [
    ("housing", "דיור", [(120450, 267.86)]),
    ("transport", "תחבורה ותקשורת", [(121320, 186.32)]),
    ("food", "מזון, כולל פירות וירקות", [(110050, 179.08)]),
    ("upkeep", "תחזוקת הדירה (כולל חשמל ומים)", [(120520, 94.36)]),
    ("culture", "חינוך, תרבות ובידור", [(121050, 93.38)]),
    ("other", "בריאות, ריהוט, הלבשה ושונות", [(121230, 62.75), (120660, 32.11), (120850, 26.62), (121430, 57.52)]),
]
IL_HEADLINE = 120010


def _yoy_fred(fred, code: str) -> pd.Series:
    s = pd.Series(fred(code), dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    return (s / s.shift(12) - 1) * 100


def us(fred) -> dict:
    yoy = {code: _yoy_fred(fred, code) for code in [p[2] for p in US_PARTS if p[2]] + [US_SERVICES[0], US_HEADLINE]}
    sh = yoy["CUSR0000SAH1"]
    w_sv, w_sh = US_SERVICES[1], 35.625
    svc = (yoy[US_SERVICES[0]] * w_sv - sh * w_sh) / (w_sv - w_sh)
    parts = {}
    for key, name, code, w in US_PARTS:
        y = svc if key == "svc" else yoy[code]
        parts[key] = (name, w, y * w / 100)
    return _pack(parts, yoy[US_HEADLINE], "BLS (דרך FRED), משקלות דצמבר 2025")


def il(cbs) -> dict:
    """cbs = callable code -> ({date: yearly %}, {date: monthly %})."""
    head = pd.Series(cbs(IL_HEADLINE)[0], dtype=float)
    head.index = pd.to_datetime(head.index)
    parts, failed = {}, []
    for key, name, codes in IL_PARTS:
        acc, wsum = None, 0.0
        for code, w in codes:
            try:
                y = pd.Series(cbs(code)[0], dtype=float)
            except Exception as e:
                failed.append(f"{code}: {str(e)[:60]}")
                continue
            y.index = pd.to_datetime(y.index)
            acc = y * w if acc is None else acc.add(y * w, fill_value=None)
            wsum += w
        if acc is not None:
            parts[key] = (name, wsum / 10, acc / 1000)
    if len(parts) < 4:
        raise ValueError("CBS components: " + "; ".join(failed[:4]))
    res = _pack(parts, head.sort_index(), "הלמ\"ס, משקלות סל ינואר 2025")
    if failed:
        res["failed"] = failed
    return res


def _pack(parts: dict, headline: pd.Series, src: str, years: int = 12) -> dict:
    df = pd.DataFrame({k: v[2] for k, v in parts.items()})
    df["_head"] = headline
    df = df.sort_index()
    df = df[df.index >= df.index.max() - pd.DateOffset(years=years)]
    df = df.dropna(subset=[k for k in parts], how="all")
    return {"d": [d.strftime("%Y-%m-%d") for d in df.index],
            "parts": [{"key": k, "name": v[0], "w": round(v[1], 2), "v": [None if pd.isna(x) else round(float(x), 3) for x in df[k]]}
                      for k, v in parts.items()],
            "headline": [None if pd.isna(x) else round(float(x), 2) for x in df["_head"]],
            "src": src}


def boi_probe() -> None:
    """The Bank of Israel series keys for the 2-year yield and inflation expectations are not documented where
    we could read them: list the candidate dataflows' series once, so the keys can be wired in."""
    base = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2"
    for name, url in (("boi_flows", f"{base}/structure/dataflow/BOI.STATISTICS?format=sdmx-json"),
                      ("boi_secdwh", f"{base}/data/dataflow/BOI.STATISTICS/SECDWH/1.0?format=csv&lastNObservations=1&labels=both"),
                      ("boi_zcm", f"{base}/data/dataflow/BOI.STATISTICS/ZCM/1.0?format=csv&lastNObservations=1&labels=both"),
                      ("boi_infexp", f"{base}/data/dataflow/BOI.STATISTICS/INFEXP/1.0?format=csv&lastNObservations=1&labels=both")):
        try:
            r = get(url, timeout=40, tries=1)
            text = r.text
            if name == "boi_flows":
                import json as _json
                js = _json.loads(text)
                flows = js.get("data", {}).get("dataflows", [])
                text = "\n".join(f"{f.get('id')}|{f.get('version')}|{f.get('name') or (f.get('names') or {}).get('he') or (f.get('names') or {}).get('en')}" for f in flows)
            else:
                rows = list(csv.reader(io.StringIO(text)))
                head = rows[0] if rows else []
                keep = [i for i, h in enumerate(head) if any(k in h.upper() for k in ("SERIES", "TITLE", "DESC", "LABEL", "TIME_PERIOD", "OBS_VALUE", "FREQ"))]
                text = "\n".join(",".join(r[i] for i in keep if i < len(r)) for r in rows[:400])
            save_probe(name, text, 60000)
        except Exception as e:
            save_probe(name, f"ERROR {type(e).__name__}: {e}")
