"""Live numbers for the economic calendar (data/calendar): what the options market prices for upcoming reports,
and what the stock did after each report, with EPS against consensus.

- implied move = ATM straddle (call + put mid) / spot, first expiry on or after the reaction day; with the ATM
  implied volatility of that expiry and of the next one (the drop after the report).
- reaction day: the report day for BMO, the next session for AMC (or unknown timing).
- results are kept once computed (data/calendar/live.json), so each company's EPS lookup runs once.
- report night: once a report is out and before its reaction day closes, the reported EPS against the estimate and
  the move in extended trading (after-hours for AMC, pre-market for BMO) are kept under "reported".
"""
from __future__ import annotations

import datetime as dt
import json
import math

import pandas as pd

from .common import ROOT, today_utc

CAL = ROOT / "data" / "calendar"
LIVE = CAL / "live.json"
WHY = CAL / "why.json"


def load_events() -> list[dict]:
    man = json.loads((CAL / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for w in man.get("weeks", []):
        p = CAL / w["file"].replace("data/", "", 1)
        if p.exists():
            out += json.loads(p.read_text(encoding="utf-8")).get("events", [])
    extra = CAL / "extra.json"      # events added outside the weekly build (missed companies, earlier weeks)
    if extra.exists():
        have = {e["id"] for e in out}
        out += [e for e in json.loads(extra.read_text(encoding="utf-8")).get("events", []) if e.get("id") not in have]
    return out


def mcaps() -> dict:
    man = json.loads((CAL / "manifest.json").read_text(encoding="utf-8"))
    p = CAL / man.get("market", "").replace("data/", "", 1)
    q = json.loads(p.read_text(encoding="utf-8")).get("quotes", {}) if p.exists() and p.is_file() else {}
    return {t: (v.get("mcap") or 0) for t, v in q.items()}


def yahoo_sym(t: str, market: str) -> str:
    return t.replace(".", "-") if market == "US" else (t if t.endswith(".TA") else t + ".TA")


def reaction_day(ev: dict, sessions: list[str]) -> str | None:
    d = ev["date"]
    if ev.get("session") == "BMO":
        return next((s for s in sessions if s >= d), None)
    return next((s for s in sessions if s > d), None)


def _mid(row) -> float | None:
    b, a, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
    if b and a and b > 0 and a > 0 and a >= b:
        return (b + a) / 2
    return float(last) if last and last > 0 else None


def implied_move(sym: str, react: str) -> dict | None:
    import yfinance as yf
    tk = yf.Ticker(sym)
    exps = [e for e in (tk.options or []) if e >= react]
    if not exps:
        return None
    exp = exps[0]
    hist = tk.history(period="5d", auto_adjust=False)
    if hist is None or hist.empty:
        return None
    spot = float(hist["Close"].dropna().iloc[-1])
    ch = tk.option_chain(exp)
    calls, puts = ch.calls.set_index("strike"), ch.puts.set_index("strike")
    strikes = sorted(set(calls.index) & set(puts.index), key=lambda k: abs(k - spot))
    if not strikes:
        return None
    k = strikes[0]
    c, p = _mid(calls.loc[k].to_dict()), _mid(puts.loc[k].to_dict())
    if c is None or p is None:
        return None
    iv = [x for x in (calls.loc[k].get("impliedVolatility"), puts.loc[k].get("impliedVolatility")) if x and x > 0.01]
    out = {"move": round((c + p) / spot, 4), "spot": round(spot, 2), "strike": float(k), "exp": exp,
           "dte": (dt.date.fromisoformat(exp) - today_utc()).days, "iv": round(sum(iv) / len(iv), 3) if iv else None,
           "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")}
    if len(exps) > 1:   # the next expiry's ATM volatility: roughly where implied volatility settles after the report
        try:
            ch2 = tk.option_chain(exps[1])
            c2 = ch2.calls.set_index("strike")
            k2 = min(c2.index, key=lambda s: abs(s - spot))
            v2 = c2.loc[k2].get("impliedVolatility")
            out["ivNext"] = round(float(v2), 3) if v2 and v2 > 0.01 else None
        except Exception:
            pass
    if out["move"] <= 0 or out["move"] > 0.6:
        return None
    return out


def eps_actual(sym: str, date: str) -> tuple[float | None, float | None]:
    """(reported EPS, EPS estimate) from Yahoo's earnings dates, for the report closest to `date`."""
    import yfinance as yf
    df = yf.Ticker(sym).get_earnings_dates(limit=8)
    if df is None or df.empty:
        return None, None
    df = df.copy()
    df.index = [pd.Timestamp(x).tz_localize(None) if pd.Timestamp(x).tzinfo else pd.Timestamp(x) for x in df.index]
    target = pd.Timestamp(date)
    df["gap"] = [abs((x.normalize() - target).days) for x in df.index]
    row = df.sort_values("gap").iloc[0]
    if row["gap"] > 3:
        return None, None
    act, est = row.get("Reported EPS"), row.get("EPS Estimate")
    f = lambda v: float(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None
    return f(act), f(est)


def is_out(ev: dict, now_ny: dt.datetime) -> bool:
    """The report has been published (AMC from 16:05 New York time on the report day)."""
    d = now_ny.date().isoformat()
    if ev["date"] < d:
        return True
    if ev["date"] > d:
        return False
    if ev.get("session") == "BMO":
        return now_ny.hour >= 7
    return now_ny.hour * 60 + now_ny.minute >= 16 * 60 + 5


def extended_move(sym: str) -> tuple[float | None, str | None]:
    """Move in extended trading against the last regular close: (change, "post" | "pre")."""
    import yfinance as yf
    info = yf.Ticker(sym).info or {}
    reg = info.get("regularMarketPrice")
    for key, kind in (("postMarketPrice", "post"), ("preMarketPrice", "pre")):
        v = info.get(key)
        state = info.get("marketState")
        ok = state in ("POST", "POSTPOST", "CLOSED") if kind == "post" else state in ("PRE", "PREPRE")
        if v and reg and v > 0 and reg > 0 and ok:
            ch = v / reg - 1
            if abs(ch) < 0.6:
                return round(ch, 4), kind
    return None, None


def _row(q: pd.DataFrame, names: tuple[str, ...], col) -> float | None:
    for n in names:
        if n in q.index:
            v = q.at[n, col]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                return float(v)
    return None


def fin_actual(sym: str, date: str) -> dict | None:
    """The reported quarter from Yahoo's quarterly income statement (GAAP): revenue, its yearly growth, gross and
    operating margin and their change from a year earlier. None until Yahoo has the quarter (often a day or two)."""
    import yfinance as yf
    q = yf.Ticker(sym).quarterly_income_stmt
    if q is None or q.empty:
        return None
    rd = pd.Timestamp(date)
    cols = sorted(q.columns, key=pd.Timestamp)
    cand = [c for c in cols if pd.Timestamp(c) <= rd and (rd - pd.Timestamp(c)).days <= 100]
    if not cand:
        return None
    c = cand[-1]
    ya = [x for x in cols if abs((pd.Timestamp(c) - pd.DateOffset(years=1) - pd.Timestamp(x)).days) <= 20]
    REV, GP, OI = ("Total Revenue", "Operating Revenue"), ("Gross Profit",), ("Operating Income", "Total Operating Income As Reported")
    rev = _row(q, REV, c)
    if not rev or rev <= 0:
        return None
    out = {"q": pd.Timestamp(c).date().isoformat(), "rev": rev}
    gp, oi = _row(q, GP, c), _row(q, OI, c)
    if gp is not None:
        out["gm"] = round(gp / rev, 4)
    if oi is not None:
        out["om"] = round(oi / rev, 4)
    if ya:
        r0 = _row(q, REV, ya[-1])
        if r0 and r0 > 0:
            out["revYoY"] = round(rev / r0 - 1, 4)
            g0, o0 = _row(q, GP, ya[-1]), _row(q, OI, ya[-1])
            if g0 is not None and "gm" in out:
                out["gmYoY"] = round(out["gm"] - g0 / r0, 4)
            if o0 is not None and "om" in out:
                out["omYoY"] = round(out["om"] - o0 / r0, 4)
    return out


def reported_he(r: dict, im: dict | None) -> str:
    parts = []
    if r.get("epsAct") is not None and r.get("epsEst") is not None:
        rel = "מעל הצפי" if r["epsAct"] > r["epsEst"] else "מתחת לצפי" if r["epsAct"] < r["epsEst"] else "בדיוק כמו הצפי"
        parts.append(f"הרווח למניה, ${r['epsAct']:.2f}, היה {rel} של ${r['epsEst']:.2f}.")
    elif r.get("epsAct") is not None:
        parts.append(f"הרווח למניה: ${r['epsAct']:.2f}.")
    if r.get("ext") is not None:
        where = "במסחר המאוחר" if r.get("extKind") == "post" else "במסחר המוקדם"
        parts.append(f"{where} המניה {'עלתה' if r['ext'] >= 0 else 'ירדה'} {abs(r['ext']) * 100:.1f}%"
                     + (f" (האופציות תמחרו ±{im['move'] * 100:.1f}%)" if im and im.get("move") else "") + ".")
    return " ".join(parts)


def summary_he(name: str, r: dict, im: dict | None) -> str:
    mv, ex = r["move"], r.get("ex")
    s1 = (f"המניה {'עלתה' if mv >= 0 else 'ירדה'} {abs(mv) * 100:.1f}% ביום המסחר שאחרי הדוח"
          + (f", לעומת {'+' if r['spx'] >= 0 else '−'}{abs(r['spx']) * 100:.1f}% ב-S&P 500" if r.get("spx") is not None else "") + ".")
    parts = []
    if r.get("epsAct") is not None and r.get("epsEst") is not None:
        rel = "מעל הצפי" if r["epsAct"] > r["epsEst"] else "מתחת לצפי" if r["epsAct"] < r["epsEst"] else "בדיוק כמו הצפי"
        parts.append(f"הרווח למניה, ${r['epsAct']:.2f}, היה {rel} של ${r['epsEst']:.2f}")
    if im and im.get("move"):
        parts.append(f"התנועה {'גדולה' if abs(mv) > im['move'] else 'קטנה'} מה-±{im['move'] * 100:.1f}% שהאופציות תמחרו")
    return s1 + (" " + ", ו".join(parts) + "." if parts else "")


def run(px: pd.DataFrame, max_implied: int = 90, max_eps: int = 60, max_rep: int = 80, max_fin: int = 80) -> tuple[dict, str]:
    from .markets import yf_close
    events = load_events()
    cap = mcaps()
    live = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else {}
    implied, results, reported, fin = live.get("implied", {}), live.get("results", {}), live.get("reported", {}), live.get("fin", {})
    today = today_utc().isoformat()
    spx = px["^GSPC"].dropna() if "^GSPC" in px.columns else pd.Series(dtype=float)
    sessions = [d for d in spx.index]
    # the next sessions are not in the price table yet: extend with weekdays
    d = dt.date.fromisoformat(sessions[-1]) if sessions else today_utc()
    fut = []
    while len(fut) < 15:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            fut.append(d.isoformat())
    cal_sessions = sessions + fut
    us = [e for e in events if e.get("market") == "US"]
    by_cap = lambda e: -(cap.get(e["ticker"]) or 0)
    # 1. implied move for reports in the next 7 days
    horizon = (today_utc() + dt.timedelta(days=7)).isoformat()
    upcoming = sorted([e for e in us if today <= e["date"] <= horizon], key=by_cap)[:max_implied]
    n_im = 0
    for e in upcoming:
        prev = implied.get(e["id"])
        if prev and prev.get("at", "")[:10] == today:
            continue
        react = reaction_day(e, cal_sessions)
        if not react:
            continue
        try:
            im = implied_move(yahoo_sym(e["ticker"], "US"), react)
        except Exception:
            im = None
        if im:
            implied[e["id"]] = im; n_im += 1
    # 2. results: the reaction-day move for every US report whose reaction day has closed
    done = [e for e in us if e["date"] <= today and e["id"] not in results]
    need = []
    for e in done:
        react = reaction_day(e, cal_sessions)
        if react and react in sessions:
            need.append((e, react))
    if need:
        syms = sorted({yahoo_sym(e["ticker"], "US") for e, _ in need})
        start = (dt.date.fromisoformat(min(r for _, r in need)) - dt.timedelta(days=10)).isoformat()
        closes = yf_close(syms, start)
        n_eps = 0
        for e, react in sorted(need, key=lambda x: by_cap(x[0])):
            sym = yahoo_sym(e["ticker"], "US")
            if sym not in closes.columns:
                continue
            c = closes[sym].dropna()
            if react not in c.index:
                continue
            i = list(c.index).index(react)
            if i == 0:
                continue
            p0, p1 = float(c.iloc[i - 1]), float(c.iloc[i])
            r = {"d0": c.index[i - 1], "d1": react, "move": round(p1 / p0 - 1, 4)}
            if c.index[i - 1] in spx.index and react in spx.index:
                r["spx"] = round(float(spx[react] / spx[c.index[i - 1]] - 1), 4)
                r["ex"] = round(r["move"] - r["spx"], 4)
            if n_eps < max_eps:
                try:
                    act, est = eps_actual(sym, e["date"])
                    n_eps += 1
                except Exception:
                    act, est = None, None
                est = est if est is not None else (e.get("consensus") or {}).get("eps")
                if act is not None:
                    r["epsAct"], r["epsEst"] = act, est
                    if est:
                        r["surprise"] = round((act - est) / abs(est), 4)
            r["he"] = summary_he(e["ticker"], r, implied.get(e["id"]))
            r["at"] = today
            results[e["id"]] = r
    # 3. report night: reports already out whose reaction day has not closed yet
    from zoneinfo import ZoneInfo
    now_ny = dt.datetime.now(ZoneInfo("America/New_York"))
    recent = (today_utc() - dt.timedelta(days=5)).isoformat()
    pend = sorted([e for e in us if e["id"] not in results and e["date"] >= recent and is_out(e, now_ny)], key=by_cap)[:max_rep]
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    n_rep = 0
    for e in pend:
        sym = yahoo_sym(e["ticker"], "US")
        r = dict(reported.get(e["id"], {}))
        if r.get("epsAct") is None:
            try:
                act, est = eps_actual(sym, e["date"])
            except Exception:
                act, est = None, None
            est = est if est is not None else (e.get("consensus") or {}).get("eps")
            if act is not None:
                r["epsAct"], r["epsEst"] = act, est
                if est:
                    r["surprise"] = round((act - est) / abs(est), 4)
        try:
            ext, kind = extended_move(sym)
        except Exception:
            ext, kind = None, None
        if ext is not None:
            r["ext"], r["extKind"] = ext, kind
        if r:
            r["at"] = stamp
            reported[e["id"]] = r; n_rep += 1
    reported = {k: v for k, v in reported.items() if k not in results and k in {e["id"] for e in us if e["date"] >= recent}}
    # 4. the reported quarter's revenue, growth and margins, for every US report of the last 10 days (until Yahoo has it)
    lo10 = (today_utc() - dt.timedelta(days=10)).isoformat()
    for e in sorted([e for e in us if e["id"] not in fin and e["date"] >= lo10 and is_out(e, now_ny)], key=by_cap)[:max_fin]:
        try:
            f = fin_actual(yahoo_sym(e["ticker"], "US"), e["date"])
        except Exception:
            f = None
        if f:
            cons = e.get("consensus") or {}
            if cons.get("rev"):
                f["revEst"] = cons["rev"]
            fin[e["id"]] = f
    # EPS from Yahoo can be in another unit or per-share basis for foreign issuers (ADRs): keep the comparison only
    # when Yahoo's estimate agrees with the calendar's consensus within 25%
    evmap = {e["id"]: e for e in events}
    prof_p = CAL / "profiles.json"
    country = {t: c.get("country") for t, c in (json.loads(prof_p.read_text(encoding="utf-8")).get("companies", {}) if prof_p.exists() else {}).items()}
    for k, r in list(results.items()) + list(reported.items()):
        e = evmap.get(k)
        cons = ((e or {}).get("consensus") or {}).get("eps")
        if r.get("epsAct") is None:
            continue
        foreign = (e or {}).get("market") != "US" or country.get((e or {}).get("ticker"), "US") not in ("US", None)
        bad = foreign or (cons and r.get("epsEst") and abs(r["epsEst"] / cons - 1) > 0.25)   # foreign issuers: unit/basis unclear
        if bad:
            for f in ("epsAct", "epsEst", "surprise"):
                r.pop(f, None)
            if k in results:
                r["he"] = summary_he(k.split("-")[0], r, implied.get(k))
    for k, r in reported.items():
        r["he"] = reported_he(r, implied.get(k))
    for k, f in fin.items():          # foreign issuers report in their own currency: keep growth and margins only
        e = evmap.get(k)
        if e and (e.get("market") != "US" or country.get(e.get("ticker"), "US") not in ("US", None)):
            f.pop("revEst", None)
            f["cur"] = "local"
    # keep the last ~10 weeks
    keep = {e["id"] for e in events}
    implied = {k: v for k, v in implied.items() if k in keep}
    fin = {k: v for k, v in fin.items() if k in keep}
    results = {k: v for k, v in results.items() if k in keep or v.get("d1", "") >= (today_utc() - dt.timedelta(days=70)).isoformat()}
    # the week's largest reporters: the daily "why" task writes their explanation
    lo, hi = (today_utc() - dt.timedelta(days=10)).isoformat(), (today_utc() + dt.timedelta(days=7)).isoformat()
    focus = [e["id"] for e in sorted([e for e in us if lo <= e["date"] <= hi], key=by_cap)[:30]]
    out = {"asof": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "implied": implied, "results": results, "reported": reported, "fin": fin, "focus": focus}
    LIVE.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    return out, f"{n_im} תנועות מגולמות חדשות · {len(results)} דוחות עם תוצאה · {len(reported)} דוחות שפורסמו וממתינים ליום התגובה"
