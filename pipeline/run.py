"""Daily run: fetch every source, update the stored series, compute, build the static site.

python -m pipeline.run            # full run (what GitHub Actions does)
python -m pipeline.run --offline  # rebuild the site from stored data only (no network)
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import traceback

from . import breadth, markets, sources
from .common import (ROOT, SITE_DIR, STATE_DIR, Status, dump_json, merge_series, read_series, today_utc)

CONFIG = ROOT / "config" / "indicators.json"


def _last(d: dict) -> str | None:
    return max(d) if d else None


def step(status: Status, key: str, name: str, fn):
    try:
        return fn()
    except Exception as e:
        status.add(key, name, False, msg=f"{type(e).__name__}: {e}"[:300])
        traceback.print_exc()
        return None


def run(offline: bool = False) -> int:
    st = Status()
    u = markets.load_universe()
    px = markets.read_prices()

    if not offline:
        # 1. Prices for indices, factors, sectors and volatility (Yahoo Finance)
        res = step(st, "prices", "מחירי מדדים ופקטורים (Yahoo Finance)", lambda: markets.update_prices(u))
        if res:
            px, rep = res
            miss = rep["missing"]
            st.add("prices", "מחירי מדדים ופקטורים (Yahoo Finance)", len(miss) <= 3,
                   px.dropna(how="all").index.max(), f"{len(px.columns)} סימולים" + (f" · חסרים: {', '.join(miss[:8])}" if miss else ""))
            spx = step(st, "spx", "S&P 500 מ-1990", lambda: markets.spx_long(read_series("spx")))
            if spx:
                merge_series("spx", spx)
        # 2. Ratios and series derived from those prices
        if not px.empty:
            for sid, (a, b) in {"rsp_spy": ("RSP", "SPY"), "sphb_splv": ("SPHB", "SPLV"),
                                "xly_xlp": ("XLY", "XLP"), "cu_au": ("HG=F", "GC=F")}.items():
                r = markets.ratio_series(px, a, b)
                if r:
                    merge_series(sid, r)
            mv = markets.column(px, "^MOVE", 2)
            if mv:
                merge_series("move", mv)
        # 3. CNN Fear & Greed and its components
        res = step(st, "cnn", "CNN Fear & Greed (6 סדרות)", sources.cnn)
        if res:
            data, via = res
            for sid, pts in data.items():
                merge_series(sid, pts)
            st.add("cnn", "CNN Fear & Greed (6 סדרות)", True, _last(data["fg"]), f"דרך {via}")
        # 4. Cboe: VIX, VIX3M, VVIX, SKEW (Yahoo as fallback)
        cb = {}
        for sym in ("VIX", "VIX3M", "VVIX", "SKEW"):
            try:
                cb[sym] = sources.cboe_history(sym)
            except Exception as e:
                ysym = "^" + sym
                cb[sym] = markets.column(px, ysym, 2)
                cb[sym + "_err"] = str(e)[:120]
        if cb.get("VIX"):
            merge_series("vix", cb["VIX"])
        if cb.get("VVIX"):
            merge_series("vvix", cb["VVIX"])
        if cb.get("SKEW"):
            merge_series("skew", cb["SKEW"])
        if cb.get("VIX") and cb.get("VIX3M"):
            merge_series("vix_ts", {d: round(v / cb["VIX3M"][d], 4) for d, v in cb["VIX"].items()
                                    if d in cb["VIX3M"] and cb["VIX3M"][d] > 0})
        errs = [k[:-4] for k in cb if k.endswith("_err")]
        st.add("cboe", "Cboe VIX, VIX3M, VVIX, SKEW", bool(cb.get("VIX")), _last(cb.get("VIX", {})),
               ("Yahoo כגיבוי עבור " + ", ".join(errs)) if errs else "")
        # 5. CFTC positioning
        res = step(st, "cftc", "CFTC COT (4 סדרות)", sources.cftc)
        if res:
            for sid, pts in res.items():
                merge_series(sid, pts)
            st.add("cftc", "CFTC COT (4 סדרות)", True, _last(res["cot_es_am"]), "")
        # 6. AAII
        res = step(st, "aaii", "AAII", sources.aaii)
        if res:
            rep = merge_series("aaii_spread", res["aaii_spread"])
            merge_series("aaii_bull", res["aaii_bull"]); merge_series("aaii_bear", res["aaii_bear"])
            st.add("aaii", "AAII", True, _last(res["aaii_spread"]), "שבוע חדש נוסף" if rep["added"] else "אין פרסום חדש")
        # 7. FRED
        res = step(st, "fred", "FRED: פער HY, עקום, NFCI", sources.fred)
        if res:
            for sid, pts in res.items():
                merge_series(sid, pts)
            st.add("fred", "FRED: פער HY, עקום, NFCI", True, _last(res["hy_oas"]), "")
        # 8. Cboe daily put/call (best effort)
        res = step(st, "cboe_pc", "Cboe Put/Call יומי", sources.cboe_putcall)
        if res is not None:
            n = 0
            for sid, pts in res.items():
                if pts:
                    n += merge_series(sid, pts)["added"]
            st.add("cboe_pc", "Cboe Put/Call יומי", True, _last(res.get("pcc", {})) or _last(read_series("pcc")),
                   f"{n} ימים חדשים" if n else "אין יום חדש")
        # 9. S&P 500 member breadth
        res = step(st, "breadth", "רוחב שוק ומומנטום מרכיבי S&P 500", breadth.run)
        if res:
            data, msg, mom = res
            for sid, pts in data.items():
                merge_series(sid, pts)
            if mom:
                dump_json(ROOT / "data" / "derived" / "sp_momentum.json", mom)
            st.add("breadth", "רוחב שוק ומומנטום מרכיבי S&P 500", True, _last(data.get("sp_pct200", {})), msg)

    # 10. Build the site
    build(st, u, px)
    status = st.to_dict()
    dump_json(STATE_DIR / "status.json", status)
    print(json.dumps({"ok": status["ok"], "failed": status["failed"]}, ensure_ascii=False))
    if status["failed"]:
        print("::warning title=sources failed::" + ", ".join(status["failed"]))
    return 0


def build(st: Status, u: dict, px) -> None:
    inds = json.loads(CONFIG.read_text(encoding="utf-8"))
    tmp = SITE_DIR.with_name("site.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "data").mkdir(parents=True)
    shutil.copy(ROOT / "web" / "index.html", tmp / "index.html")
    (tmp / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    epoch = dt.date(1970, 1, 1)
    series = {}
    for ind in inds:
        if ind.get("derive"):
            continue
        s = read_series(ind["id"])
        if not s:
            continue
        ks = sorted(s)
        series[ind["id"]] = {"t": [(dt.date.fromisoformat(k) - epoch).days for k in ks], "v": [s[k] for k in ks]}
    dump_json(tmp / "data" / "series.json", series)
    status = st.to_dict()
    dump_json(tmp / "data" / "meta.json", {"built": status["finished"], "status": status, "indicators": inds})
    mom_file = ROOT / "data" / "derived" / "sp_momentum.json"
    if mom_file.exists():
        shutil.copy(mom_file, tmp / "data" / "momentum.json")
    if not px.empty:
        dump_json(tmp / "data" / "markets.json", markets.build_markets(px, u))
        dump_json(tmp / "data" / "prices.json", markets.prices_payload(px))
    shutil.rmtree(SITE_DIR, ignore_errors=True)
    tmp.rename(SITE_DIR)


if __name__ == "__main__":
    sys.exit(run(offline="--offline" in sys.argv))
