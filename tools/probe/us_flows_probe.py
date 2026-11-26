"""Temporary probe (not part of the site): fetch the inputs of the US money-flow section for offline development."""
import datetime as dt, json, pathlib, time, traceback
import requests
from pipeline import breadth, markets

OUT = pathlib.Path("probe_out"); OUT.mkdir(exist_ok=True)
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
TICK = ["SPY", "XLK", "XLF", "XLV", "XLY", "XLC", "XLI", "XLP", "XLE", "XLU", "XLRE", "XLB", "KRE", "KBE", "XBI", "XRT",
        "XHB", "XOP", "XME", "XAR", "XSD", "XSW", "KIE", "MDY", "SPYG", "SPYV", "SPLG", "XTL", "XHE", "XPH"]
URL = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/navhist-us-en-{t}.xlsx"
for t in TICK:
    try:
        r = requests.get(URL.format(t=t.lower()), headers=HDR, timeout=60)
        print(t, r.status_code, len(r.content), r.headers.get("content-type"))
        if r.ok:
            (OUT / f"navhist_{t}.xlsx").write_bytes(r.content)
    except Exception as e:
        print(t, "ERR", e)
    time.sleep(0.3)
t0 = time.time()
syms, src, info = breadth.members()
json.dump({"src": src, "info": info}, open(OUT / "members.json", "w"))
start = (dt.date.today() - dt.timedelta(days=520)).isoformat()
bars = markets.yf_ohlc(syms, start)
print("bars", {k: v.shape for k, v in bars.items()}, round(time.time() - t0, 1), "s")
for k, v in bars.items():
    v.to_csv(OUT / f"sp_{k}.csv.gz", float_format="%.6g")
