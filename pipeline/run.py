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
from zoneinfo import ZoneInfo

from . import analogs, drivers, breadth, earnings, israel, macro, markets, rs, sources
from .common import (ROOT, SITE_DIR, STATE_DIR, Status, cutoff_date, dump_json, il_live_date, merge_series, read_series, today_utc)

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
    px = markets.with_baskets(markets.read_prices(), u)

    if not offline:
        # 1. Prices for indices, factors, sectors and volatility (Yahoo Finance)
        res = step(st, "prices", "מחירי מדדים ופקטורים (Yahoo Finance)", lambda: markets.update_prices(u))
        if res:
            px, rep = res
            miss = rep["missing"]
            st.add("prices", "מחירי מדדים ופקטורים (Yahoo Finance)", len(miss) <= 3,
                   (px["^GSPC"].dropna().index.max() if "^GSPC" in px.columns else px.dropna(how="all").index.max()), f"{len(px.columns)} סימולים" + (f" · חסרים: {', '.join(miss[:8])}" if miss else "")
                   + (f" · חסרים בסלי הטכנולוגיה: {', '.join(rep['missingMembers'][:8])}" if rep.get("missingMembers") else ""))
            step(st, "ath", "שיאי כל הזמנים למרחק מהשיא", lambda: markets.update_ath(u, px))
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
        # 2b. Chaikin Money Flow of the S&P 500 (SPY)
        res = step(st, "cmf", "Chaikin Money Flow · SPY", lambda: markets.spy_cmf(read_series("cmf_spy")))
        if res:
            merge_series("cmf_spy", res)
            st.add("cmf", "Chaikin Money Flow · SPY", True, _last(res), f"{len(res)} ימים")
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
        # 7b. Macro: inflation, rates, spreads by rating, labour, money, fuel and power
        res = step(st, "macro", "מאקרו: FRED, הלמ\"ס, בנק ישראל, EIA", macro.run)
        if res:
            data, cv, msg = res
            for sid, pts in data.items():
                merge_series(sid, pts)
            if cv:
                dump_json(ROOT / "data" / "derived" / "curve.json", cv)
            st.add("macro", "מאקרו: FRED, הלמ\"ס, בנק ישראל, EIA", len(data) >= 40, _last(data.get("ust10y", {})), msg)
        # 7b2. What drives inflation (CPI components' contributions), US and Israel
        def _drivers():
            res, msg = {}, []
            for k, fn in (("us", lambda: drivers.us(macro.fred_series)), ("il", lambda: drivers.il(macro.cbs_cpi))):
                try:
                    res[k] = fn(); msg.append(f"{k.upper()} עד {res[k]['d'][-1][:7]}")
                except Exception as e:
                    msg.append(f"{k.upper()}: {type(e).__name__} {str(e)[:80]}")
            if not res:
                raise ValueError("; ".join(msg))
            old = json.loads(drivers.OUT.read_text(encoding="utf-8")) if drivers.OUT.exists() else {}
            dump_json(drivers.OUT, {**old, **res})
            return msg
        res = step(st, "drivers", "מאקרו: מרכיבי האינפלציה", _drivers)
        if res:
            st.add("drivers", "מאקרו: מרכיבי האינפלציה", not any(":" in m for m in res), None, " · ".join(res))
        # 7c. Macro analogs: past months that looked like today, and what stocks and industries did next
        res = step(st, "analogs", "מאקרו: תקופות דומות בעבר", lambda: analogs.run(macro.fred_series))
        if res:
            dump_json(analogs.OUT, res)
            st.add("analogs", "מאקרו: תקופות דומות בעבר", True, res["now"], f"{len(res['analogs'])} תקופות דומות מאז {res['from']}"
                   + ("" if res["ff"] else " · בלי נתוני תעשיות (Ken French לא זמין)"))
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
        bextra = None
        if res:
            data, msg, mom, bextra = res
            for sid, pts in data.items():
                merge_series(sid, pts)
            if mom:
                dump_json(ROOT / "data" / "derived" / "sp_momentum.json", mom)
            summation_from_oscillator()
            st.add("breadth", "רוחב שוק ומומנטום מרכיבי S&P 500", True, _last(data.get("sp_pct200", {})), msg)
        # 10. RS for every US stock and for every factor, sector and theme ETF
        def _rs():
            members = bextra["members"] if bextra else None
            if members is None:
                try:
                    members = breadth.members()[2]
                except Exception:
                    members = None
            try:
                bars = markets.etf_ohlc(u)
            except Exception:
                bars = None
            if bars:
                dump_json(ROOT / "data" / "derived" / "cmf.json", markets.cmf_payload(bars))
                fac = [it["sym"] for g in u["groups"] if g["kind"] == "factor" for it in g["items"]] + [u["benchmark"]]
                fac = [c for c in dict.fromkeys(fac) if c in bars["close"].columns]
                ohlc = {k: v[fac] for k, v in bars.items() if k in ("close", "high", "low")}
            else:
                ohlc = None
            return rs.run(px, u, members, bextra["bars"] if bextra else None, ohlc)
        # 10a. Economic calendar: implied moves for the coming reports, reactions and EPS for the reported ones
        if (earnings.CAL / "manifest.json").exists():
            res = step(st, "earnings", "יומן כלכלי: תנועה מגולמת ותוצאות דוחות", lambda: earnings.run(px))
            if res:
                st.add("earnings", "יומן כלכלי: תנועה מגולמת ותוצאות דוחות", True, res[0]["asof"][:10], res[1])
        # 10b. Israel: breadth, sentiment proxies, sectors, RS of the large TASE names, Israeli macro
        res = step(st, "israel", "ישראל: רוחב, סנטימנט, סקטורים ומאקרו", lambda: israel.run(px))
        if res:
            data, payload, msg = res
            for sid, pts in data.items():
                if pts:
                    merge_series(sid, pts)
            dump_json(israel.DERIVED, payload)
            live = il_live_date()
            if live and live > cutoff_date() and payload.get("asof") == live:
                msg += " · ת\"א ושער הדולר: נכון ל-" + dt.datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%H:%M")
            st.add("israel", "ישראל: רוחב, סנטימנט, סקטורים ומאקרו", payload["n"] >= 50, payload["asof"], msg)
        res = step(st, "rs", "RS לכל המניות, הפקטורים והסקטורים", _rs)
        if res:
            out, msg = res
            st.add("rs", "RS לכל המניות, הפקטורים והסקטורים", True, out["asof"], msg)

    # 11. Build the site
    build(st, u, px)
    status = st.to_dict()
    dump_json(STATE_DIR / "status.json", status)
    print(json.dumps({"ok": status["ok"], "failed": status["failed"]}, ensure_ascii=False))
    if status["failed"]:
        print("::warning title=sources failed::" + ", ".join(status["failed"]))
    return 0


def summation_from_oscillator() -> None:
    """McClellan Summation by stock count: the running total of the stored S&P 500 McClellan Oscillator."""
    mco = read_series("sp_mco")
    if not mco:
        return
    tot, out = 0.0, {}
    for d in sorted(mco):
        tot += mco[d]
        out[d] = round(tot, 1)
    from .common import write_series
    write_series("sp_mcsi", out)


def build(st: Status, u: dict, px) -> None:
    inds = json.loads(CONFIG.read_text(encoding="utf-8")) + macro.indicator_defs() + israel.indicator_defs()
    tmp = SITE_DIR.with_name("site.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "data").mkdir(parents=True)
    shutil.copy(ROOT / "web" / "index.html", tmp / "index.html")
    if (ROOT / "web" / "vendor").exists():
        shutil.copytree(ROOT / "web" / "vendor", tmp / "vendor")
    (tmp / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    if (ROOT / "web" / "calendar").exists():   # the economic calendar app and its data (weekly task + live.json)
        shutil.copytree(ROOT / "web" / "calendar", tmp / "calendar")
        if (ROOT / "data" / "calendar").exists():
            shutil.copytree(ROOT / "data" / "calendar", tmp / "calendar" / "data")
    epoch = dt.date(1970, 1, 1)
    series = {}
    summation_from_oscillator()
    try:
        israel.finish()
    except Exception:
        traceback.print_exc()
    for ind in inds:
        if ind.get("derive") or ind.get("tab"):
            continue
        s = read_series(ind["id"])
        if not s:
            continue
        ks = sorted(s)
        series[ind["id"]] = {"t": [(dt.date.fromisoformat(k) - epoch).days for k in ks], "v": [s[k] for k in ks]}
    dump_json(tmp / "data" / "series.json", series)
    status = st.to_dict()
    dump_json(tmp / "data" / "meta.json", {"built": status["finished"], "status": status, "indicators": inds, "macro": macro.site_meta()})
    curve_file = ROOT / "data" / "derived" / "curve.json"
    dump_json(tmp / "data" / "israel.json", israel.site_payload())
    an_file = analogs.OUT
    dump_json(tmp / "data" / "macro.json", {"series": macro.payload(),
                                             "analogs": json.loads(an_file.read_text(encoding="utf-8")) if an_file.exists() else {},
                                             "drivers": json.loads(drivers.OUT.read_text(encoding="utf-8")) if drivers.OUT.exists() else {},
                                             "curve": json.loads(curve_file.read_text(encoding="utf-8")) if curve_file.exists() else {}})
    ev_file = ROOT / "config" / "events.jsonl"   # curated market events for the peaks and troughs of the charts
    if ev_file.exists():
        evs = [json.loads(x) for x in ev_file.read_text(encoding="utf-8").splitlines() if x.strip()]
        dump_json(tmp / "data" / "events.json", {"events": evs})
    mom_file = ROOT / "data" / "derived" / "sp_momentum.json"
    if mom_file.exists():
        shutil.copy(mom_file, tmp / "data" / "momentum.json")
    rs_file = ROOT / "data" / "derived" / "rs.json"
    if rs_file.exists():
        shutil.copy(rs_file, tmp / "data" / "rs.json")
    if not px.empty:
        mk = markets.build_markets(px, u)
        cmf_file = ROOT / "data" / "derived" / "cmf.json"
        if cmf_file.exists():
            for sym, rec in json.loads(cmf_file.read_text(encoding="utf-8")).items():
                if sym in mk["items"]:
                    mk["items"][sym]["cmf"] = rec
        etf_file = ROOT / "data" / "derived" / "rs_etf.json"
        if etf_file.exists():
            etf = json.loads(etf_file.read_text(encoding="utf-8"))
            mk["rs"] = {k: etf.get(k) for k in ("asof", "from", "to", "prevAsof", "method")}
            for sym, rec in etf.get("items", {}).items():
                if sym in mk["items"]:
                    mk["items"][sym]["rs"] = rec
        dump_json(tmp / "data" / "markets.json", mk)
        dump_json(tmp / "data" / "ticker.json", markets.ticker_payload(px, u))
        dump_json(tmp / "data" / "prices.json", markets.prices_payload(px, u=u))
    shutil.rmtree(SITE_DIR, ignore_errors=True)
    tmp.rename(SITE_DIR)


if __name__ == "__main__":
    sys.exit(run(offline="--offline" in sys.argv))
