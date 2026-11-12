"""One-off probe (temporary branch only): which sources can feed a market-cap-to-GDP (Buffett) indicator
for the US and Israel. Writes everything it finds to state/probe_buffett/."""
import csv
import io
import json
import pathlib
import sys
import traceback

sys.path.insert(0, ".")
from pipeline.common import get  # noqa: E402
from pipeline.sources import _fred_csv  # noqa: E402

OUT = pathlib.Path("state/probe_buffett")
OUT.mkdir(parents=True, exist_ok=True)


def save(name, text):
    (OUT / f"{name}.txt").write_text(text, encoding="utf-8")


def safe(name, fn):
    try:
        fn()
    except Exception:
        save(name + "_ERR", traceback.format_exc())


BOI = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2"


def boi_list(flow):
    r = get(f"{BOI}/data/dataflow/BOI.STATISTICS/{flow}/1.0",
            params={"format": "csv", "lastNObservations": 1, "labels": "both"}, timeout=120, tries=2)
    rows = list(csv.reader(io.StringIO(r.text)))
    head = rows[0] if rows else []
    save(f"boi_{flow}_head", ",".join(head) + "\n" + "\n".join(",".join(x) for x in rows[1:4]))
    keep = [i for i, h in enumerate(head) if any(k in h.upper() for k in ("SERIES", "TITLE", "DESC", "LABEL", "TIME_PERIOD", "OBS_VALUE", "FREQ", "UNIT", "MULT", "NAME"))]
    save(f"boi_{flow}_all", "\n".join(",".join(x[i] for i in keep if i < len(x)) for x in rows))


for flow in ("SECDWH", "NA"):
    safe(f"boi_{flow}", lambda f=flow: boi_list(f))

FRED = ["NCBEILQ027S", "GDP", "BOGZ1LM793164105Q", "BOGZ1FL793164105Q", "BOGZ1LM893064105Q", "BOGZ1LM103164103Q",
        "DDDM01ILA156NWDB", "DDDM01USA156NWDB", "CPMNACSCAB1GQIL", "CPMNACNSAB1GQIL", "NGDPSAXDCILQ", "NGDPNSAXDCILQ",
        "MKTGDPILA646NWDB", "WILL5000PRFC"]
for code in FRED:
    safe("fred_" + code, lambda c=code: save("fred_" + c, _fred_csv(c).text))


def wb(ind, c):
    js = get(f"https://api.worldbank.org/v2/country/{c}/indicator/{ind}", params={"format": "json", "per_page": 100},
             timeout=60, tries=2, expect_json=True)
    rows = [(x["date"], x["value"]) for x in (js[1] if len(js) > 1 and js[1] else []) if x.get("value") is not None]
    save(f"wb_{ind}_{c}", "\n".join(f"{d},{v}" for d, v in sorted(rows)))


for ind in ("CM.MKT.LCAP.GD.ZS", "CM.MKT.LCAP.CD", "NY.GDP.MKTP.CN", "NY.GDP.MKTP.CD"):
    for c in ("ISR", "USA"):
        safe(f"wb_{ind}_{c}", lambda i=ind, cc=c: wb(i, cc))


def yahoo():
    import yfinance as yf
    out = []
    for sym in ("^GSPC", "^W5000", "^TA125.TA", "TA35.TA", "^TA90.TA"):
        try:
            raw = yf.download(sym, start="1945-01-01", interval="1mo", auto_adjust=False, actions=False, progress=False, threads=False)
            c = raw["Close"].dropna()
            if hasattr(c, "columns"):
                c = c.iloc[:, 0]
            out.append(f"{sym}: n={len(c)} first={c.index[0].date() if len(c) else None} {c.iloc[0] if len(c) else None} "
                       f"last={c.index[-1].date() if len(c) else None} {c.iloc[-1] if len(c) else None}")
            if sym in ("^GSPC", "^W5000"):
                save("yf_" + sym.strip("^"), c.to_csv())
        except Exception as e:
            out.append(f"{sym}: ERROR {type(e).__name__} {e}")
    save("yahoo_summary", "\n".join(out))


safe("yahoo", yahoo)


def tase():
    # TASE end-of-day API used by the pipeline for VTA35: try a few index ids and print the fields of one item
    import requests
    url = "https://api.tase.co.il/api/index/historyeod"
    hdr = {"Content-Type": "application/json", "Accept": "application/json", "Accept-Language": "he-IL",
           "Origin": "https://market.tase.co.il", "Referer": "https://market.tase.co.il/",
           "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
    lines = []
    for oid in (137, 142, 168, 145, 143):
        try:
            r = requests.post(url, json={"pType": 1, "oId": oid, "pageNum": 1, "TotalRec": 1, "lang": "0"}, headers=hdr, timeout=30)
            items = (r.json() or {}).get("Items") or []
            lines.append(f"oId={oid} status={r.status_code} n={len(items)} first={json.dumps(items[0], ensure_ascii=False) if items else None}")
        except Exception as e:
            lines.append(f"oId={oid} ERROR {e}")
    save("tase_eod", "\n".join(lines))


safe("tase", tase)
print("done")
