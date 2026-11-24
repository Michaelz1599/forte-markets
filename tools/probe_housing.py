"""One-off probe (temporary branch probe-housing only), round 2: dimensions of the mortgage series, history depth of the
bank financial-statement series, the CBS dwelling-price chapter and the CBS series API (unsold new apartments)."""
import csv
import io
import json
import pathlib
import sys
import traceback

sys.path.insert(0, ".")
from pipeline.common import get  # noqa: E402

OUT = pathlib.Path("state/probe_housing2")
OUT.mkdir(parents=True, exist_ok=True)
BOI = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2"
MAX = 900_000


def save(name, text):
    (OUT / f"{name}.txt").write_text(text[:MAX], encoding="utf-8")


def safe(name, fn):
    try:
        fn()
    except Exception:
        save(name + "_ERR", traceback.format_exc())


def boi_full(flow):
    r = get(f"{BOI}/data/dataflow/BOI.STATISTICS/{flow}/1.0", params={"format": "csv", "lastNObservations": 1, "labels": "both"}, timeout=180, tries=2)
    rows = list(csv.reader(io.StringIO(r.text)))
    head = rows[0]
    drop = [i for i, h in enumerate(head) if any(k in h.upper() for k in ("CONF_STATUS", "PUB_WEBSITE", "INTERNAL_PROCESS", "DATA_SOURCE", "DP_DIRECTIVE", "TIME_COLLECT", "RELEASE", "COMMENTS", "FR_UPDATED", "CONSOLIDAT", "UNIT_MULT"))]
    save(f"boi_{flow}_full", "\n".join(" | ".join(x[i] for i in range(len(x)) if i not in drop) for x in rows))


for flow in ("BMB_99", "BIR_MRTG_99"):
    safe("boi_" + flow, lambda f=flow: boi_full(f))


def boi_hist(flow, key):
    r = get(f"{BOI}/data/dataflow/BOI.STATISTICS/{flow}/1.0/{key}", params={"startperiod": "1990-01-01", "format": "csv"}, timeout=90, tries=2)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    save(f"hist_{key}", "\n".join(f"{x.get('TIME_PERIOD')},{x.get('OBS_VALUE')}" for x in rows))


for key in ("BNK_10001_FR_FINREP_1134", "BNK_10001_FR_FINREP_486", "BNK_10001_FR_FINREP_223", "BNK_10001_FR_FINREP_248",
            "BNK_10001_FR_FINREP_327", "BNK_99910_FR_FINREP_1134", "BNK_12001_FR_FINREP_228"):
    safe("hist_" + key, lambda k=key: boi_hist("BFR_99", k))
for key in ("BNK_99034_LR_BIR_MRTG_897", "BNK_99034_LR_BIR_MRTG_155"):
    safe("hist_" + key, lambda k=key: boi_hist("BIR_MRTG_99", k))
safe("hist_IND_FLT_M", lambda: boi_hist("REAL_ES_DF", "IND_FLT_M"))
safe("hist_BMB_OL_7", lambda: boi_hist("BMB_99", "BNK_99034_LR_MRTG_OL_7"))


def cbs_chapter():
    js = get("https://api.cbs.gov.il/index/catalog/chapter", params={"id": "aa", "format": "json", "download": "false"}, timeout=60, tries=2, expect_json=True)
    save("cbs_chapter_aa", json.dumps(js, ensure_ascii=False, indent=0))


safe("cbs_chapter_aa", cbs_chapter)


def cbs_series():
    out = []
    for host in ("https://apis.cbs.gov.il", "https://api.cbs.gov.il"):
        for params in ({"id": 1, "format": "json", "download": "false"}, {"id": 1, "format": "json", "download": "false", "lang": "he"},
                       {"id": 2, "subject": 1, "format": "json", "download": "false"}):
            try:
                r = get(f"{host}/series/catalog/level", params=params, timeout=60, tries=1)
                out.append(f"== {host} {params} -> {r.status_code}\n{r.text[:20000]}")
            except Exception as e:
                out.append(f"== {host} {params} ERROR {e}")
    save("cbs_series_try", "\n\n".join(out))


safe("cbs_series", cbs_series)


def cbs_walk():
    """Walk the series catalog for construction / housing subjects (if the API answers)."""
    host = "https://apis.cbs.gov.il"
    lines = []
    def level(lvl, subject=None):
        p = {"id": lvl, "format": "json", "download": "false"}
        if subject is not None:
            p["subject"] = subject
        return get(f"{host}/series/catalog/level", params=p, timeout=60, tries=1, expect_json=True)
    js = level(1)
    lines.append(json.dumps(js, ensure_ascii=False)[:5000])
    def items(o):
        if isinstance(o, dict):
            for k in ("catalogs", "catalog", "items", "data"):
                if k in o:
                    return items(o[k])
            return [o]
        if isinstance(o, list):
            return o
        return []
    for it in items(js):
        nm = json.dumps(it, ensure_ascii=False)
        if any(w in nm for w in ("בנ", "דיור", "דירות", "construction", "Construction")):
            sid = it.get("id") or (it.get("path") or [None])[-1]
            try:
                j2 = level(2, sid)
                lines.append(f"== level2 subject {sid}\n" + json.dumps(j2, ensure_ascii=False)[:30000])
            except Exception as e:
                lines.append(f"== level2 subject {sid} ERROR {e}")
    save("cbs_series_walk", "\n\n".join(lines))


safe("cbs_walk", cbs_walk)
print("done")
