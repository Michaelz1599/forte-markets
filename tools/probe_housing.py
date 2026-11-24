"""One-off probe (temporary branch probe-housing only): data sources for the marketing tab's housing, banks and mortgage sections.

Lists the Bank of Israel SDMX series of the real-estate, construction, mortgage and bank financial-statement flows (one
observation each, with labels), and the CBS index catalog plus the dwelling-price index, so that the pipeline can be
written against real series codes.
"""
import csv
import io
import json
import pathlib
import sys
import traceback

sys.path.insert(0, ".")
from pipeline.common import get  # noqa: E402

OUT = pathlib.Path("state/probe_housing")
OUT.mkdir(parents=True, exist_ok=True)
BOI = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2"
CBS = "https://api.cbs.gov.il"
MAX = 900_000


def save(name, text):
    (OUT / f"{name}.txt").write_text(text[:MAX], encoding="utf-8")


def safe(name, fn):
    try:
        fn()
    except Exception:
        save(name + "_ERR", traceback.format_exc())


def boi_list(flow):
    r = get(f"{BOI}/data/dataflow/BOI.STATISTICS/{flow}/1.0",
            params={"format": "csv", "lastNObservations": 1, "labels": "both"}, timeout=180, tries=2)
    rows = list(csv.reader(io.StringIO(r.text)))
    save(f"boi_{flow}_head", " | ".join(rows[0]) if rows else "(empty)")
    head = rows[0] if rows else []
    keep = [i for i, h in enumerate(head) if any(k in h.upper() for k in ("SERIES_CODE", "SERIES NAME", "SERIES_NAME", "FREQ", "UNIT", "TIME_PERIOD", "OBS_VALUE", "BANK", "TITLE"))]
    save(f"boi_{flow}", "\n".join(" | ".join(x[i] for i in keep if i < len(x)) for x in rows))


for flow in ("REAL_ES_DF", "CONS", "BIR_MRTG_99", "BMB_99", "BFR_99", "EZER_PIK_MOS", "DEBT_AGG"):
    safe("boi_" + flow, lambda f=flow: boi_list(f))


def cbs_catalog():
    js = get(f"{CBS}/index/catalog/catalog", params={"format": "json", "download": "false"}, timeout=60, tries=2, expect_json=True)
    save("cbs_index_catalog", json.dumps(js, ensure_ascii=False, indent=0))


safe("cbs_index_catalog", cbs_catalog)


def cbs_index(code):
    js = get(f"{CBS}/index/data/price", params={"id": code, "format": "json", "download": "false", "last": 30}, timeout=60, tries=2, expect_json=True)
    save(f"cbs_index_{code}", json.dumps(js, ensure_ascii=False, indent=0))


for code in (40010, 40020, 70000, 120010):
    safe(f"cbs_index_{code}", lambda c=code: cbs_index(c))


def cbs_series_levels():
    out = []
    for lvl in (1, 2):
        try:
            js = get(f"{CBS}/series/catalog/level", params={"id": lvl, "format": "json", "download": "false"}, timeout=60, tries=2, expect_json=True)
            out.append(f"== level {lvl}\n" + json.dumps(js, ensure_ascii=False, indent=0))
        except Exception as e:
            out.append(f"== level {lvl} ERROR {e}")
    save("cbs_series_levels", "\n\n".join(out))


safe("cbs_series_levels", cbs_series_levels)
print("done")
