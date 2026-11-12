"""One-off probe (temporary branch only), round 2: Israel inputs for a market-cap-to-GDP indicator."""
import csv
import io
import json
import pathlib
import sys
import time
import traceback

sys.path.insert(0, ".")
from pipeline.common import get  # noqa: E402

OUT = pathlib.Path("state/probe_buffett2")
OUT.mkdir(parents=True, exist_ok=True)


def save(name, text):
    (OUT / f"{name}.txt").write_text(text, encoding="utf-8")


def safe(name, fn):
    try:
        fn()
    except Exception:
        save(name + "_ERR", traceback.format_exc())


BOI = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2"


def boi_series(flow, key, name):
    r = get(f"{BOI}/data/dataflow/BOI.STATISTICS/{flow}/1.0/{key}", params={"startperiod": "1980-01-01", "format": "csv"}, timeout=90, tries=3)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    save(name, "\n".join(f"{x.get('TIME_PERIOD')},{x.get('OBS_VALUE')}" for x in rows))


for key in ("CHAINED_GDP_Q_N", "GDP_Q_N", "CHAINED_GDP_A_N"):
    safe("boi_" + key, lambda k=key: boi_series("NA", k, "boi_" + k))


def boi_list(flow):
    r = get(f"{BOI}/data/dataflow/BOI.STATISTICS/{flow}/1.0",
            params={"format": "csv", "lastNObservations": 1, "labels": "both"}, timeout=120, tries=2)
    rows = list(csv.reader(io.StringIO(r.text)))
    head = rows[0] if rows else []
    keep = [i for i, h in enumerate(head) if any(k in h.upper() for k in ("SERIES", "FREQ", "UNIT", "TIME_PERIOD", "OBS_VALUE"))]
    save(f"boi_{flow}_all", "\n".join(",".join(x[i] for i in keep if i < len(x)) for x in rows))


safe("boi_EXR", lambda: boi_list("EXR"))


def wb(ind, c):
    last = None
    for i in range(5):
        try:
            js = get(f"https://api.worldbank.org/v2/country/{c}/indicator/{ind}", params={"format": "json", "per_page": 200},
                     timeout=60, tries=1, expect_json=True)
            rows = [(x["date"], x["value"]) for x in (js[1] if len(js) > 1 and js[1] else []) if x.get("value") is not None]
            save(f"wb_{ind}_{c}", "\n".join(f"{d},{v}" for d, v in sorted(rows)))
            return
        except Exception as e:
            last = e
            time.sleep(5 * (i + 1))
    raise last


for ind in ("CM.MKT.LCAP.GD.ZS", "CM.MKT.LCAP.CD", "NY.GDP.MKTP.CN", "NY.GDP.MKTP.CD", "PA.NUS.FCRF", "CM.MKT.LDOM.NO"):
    safe(f"wb_{ind}_ISR", lambda i=ind: wb(i, "ISR"))


def yahoo():
    import yfinance as yf
    out = []
    for sym, kw in (("^W5000", dict(period="1mo", interval="1d")), ("^W5000", dict(start="2013-01-01", interval="1d")),
                    ("ILS=X", dict(start="1990-01-01", interval="1mo")), ("^TA125.TA", dict(start="1990-01-01", interval="1mo")),
                    ("^GSPC", dict(start="1960-01-01", interval="1mo"))):
        try:
            raw = yf.download(sym, auto_adjust=False, actions=False, progress=False, threads=False, **kw)
            c = raw["Close"].dropna()
            if hasattr(c, "columns"):
                c = c.iloc[:, 0]
            out.append(f"{sym} {kw}: n={len(c)} first={c.index[0].date() if len(c) else None} last={c.index[-1].date() if len(c) else None} {c.iloc[-1] if len(c) else None}")
            if sym in ("ILS=X", "^TA125.TA"):
                save("yf_" + sym.strip("^").replace("=", "_"), c.to_csv())
        except Exception as e:
            out.append(f"{sym}: ERROR {type(e).__name__} {e}")
    save("yahoo_summary", "\n".join(out))


safe("yahoo", yahoo)


def tase_names():
    # names of a few TASE index ids (to find the all-share index)
    import requests
    hdr = {"Content-Type": "application/json", "Accept": "application/json", "Accept-Language": "he-IL",
           "Origin": "https://market.tase.co.il", "Referer": "https://market.tase.co.il/",
           "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
    lines = []
    for url, body in (("https://api.tase.co.il/api/index/indicesmain", None),
                      ("https://api.tase.co.il/api/index/indexmain", {"oId": 168, "lang": "0"}),
                      ("https://api.tase.co.il/api/index/indexmain", {"oId": 137, "lang": "0"})):
        try:
            r = requests.post(url, json=body or {"lang": "0"}, headers=hdr, timeout=30) if body is not None else requests.get(url, headers=hdr, timeout=30)
            lines.append(f"{url} {body} -> {r.status_code} {r.text[:1500]}")
        except Exception as e:
            lines.append(f"{url} ERROR {e}")
    save("tase_names", "\n\n".join(lines))


safe("tase", tase_names)
print("done")
