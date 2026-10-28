"""Relative strength (RS) for every US stock, and for the factor, sector and theme ETFs.

    RS = percentile of the 6-month return excluding the most recent month (close 21 sessions ago over the
         close 126 sessions ago), across all ranked US common stocks, rounded up to 1..100.

Stock prices come from the daily snapshots of NASDAQ's stock list (close, market cap, sector) kept in the git
history of ozkanpakdil/top-us-stock-tickers; only the snapshots at the needed dates are read. S&P 500 members use
split-adjusted Yahoo closes instead (that also covers the members NASDAQ's list leaves out), and the overlap is how
each snapshot is validated. A split shows up as a price move that the market value does not share, and those
stocks are left out. ETFs are ranked against the same stock distribution, so their RS is on the same scale.
"""
from __future__ import annotations

import datetime as dt
import io
import math
import re
import shutil
import subprocess

import numpy as np
import pandas as pd

from .common import ROOT, dump_json

SNAP_REPO = "https://github.com/ozkanpakdil/top-us-stock-tickers.git"
CACHE = ROOT / ".cache"
DERIVED = ROOT / "data" / "derived"
DIST_CSV = DERIVED / "rs61_dist.csv"    # daily quantiles of the stocks' 6-1 returns (for ETF RS history)
ETF_CSV = DERIVED / "rs61_etf.csv"      # daily 6-1 RS of every ETF in the universe
RS_JSON = DERIVED / "rs.json"           # the stock table and sector ranking (site payload)
ETF_JSON = DERIVED / "rs_etf.json"      # current ETF RS, merged into markets.json at build time

# --------------------------------------------------------------------------- security types
_EXCL = [
    ("warrant", r"\bwarrants?\b"),
    ("right", r"\brights?\b|contingent value"),
    ("unit", r"\bunits?\b(?!.*limited partner)|corporate units?|tangible equity"),
    ("pref", r"preferred|preference shares|\bpfd\b|perpetual|cumulative|(?<!american )depositary|\btrust [ivx]+\b"),
    ("debt", r"\bnotes?\b|debentures?|\bbonds?\b|subordinated|\bdue \d{4}\b|\d(?:\.\d+)?% "),
    ("fund", r"\bfunds?\b|municipal|closed[- ]end|\betf\b|\betn\b|\bportfolio\b|\bstrats\b|term trust"
             r"|(income|dividend|opportunit|strategic|premium|tax[- ]advantaged|equity|high yield|credit|infrastructure"
             r"|utility|enhanced|floating rate|mortgage|science|health sciences|technology|allocation|resources|real asset"
             r"|global|multi[- ]sector|securities|sector|value|growth)[\w\s&,.'-]*\btrust\b(?!.*(realty|property|properties|bancorp|bank))"),
    ("spac", r"\b(acquisition|merger)\s+(corp|corporation|company|co\b|ltd|limited|inc|holdings?)|blank check"
             r"|\b(capital|growth|investment|opportunity|partners)\s+corp(oration)?\.?\s+[ivx]+\b"),
]
_EXCL_RE = [(k, re.compile(p, re.I)) for k, p in _EXCL]


_LP_EQUITY = re.compile(r"common units?|\bl\.?p\.?\b|limited partner", re.I)
_NOT_LP = re.compile(r"corporate|tangible|acquisition|preferred|merger", re.I)


def security_kind(name: str) -> str:
    for k, rx in _EXCL_RE:
        if rx.search(name or ""):
            if k == "unit" and _LP_EQUITY.search(name) and not _NOT_LP.search(name):
                continue      # partnership units (MLPs, AllianceBernstein) are the common equity
            return k
    return "stock"


_CUT = re.compile(r"\s+(class [a-z]\b.*|common stock.*|common shares.*|common units.*|ordinary shares?.*|american depositary.*"
                  r"|ads\b.*|sponsored adr.*|shares of beneficial.*|\(the\).*|- common.*|new common.*|common$)", re.I)
_SUFFIX = re.compile(r"[\s,]+(inc\.?|incorporated|corporation|corp\.?|co\.?|company|ltd\.?|limited|plc|p\.l\.c\.|n\.v\.|nv|s\.a\.|sa|se|ag"
                     r"|l\.p\.|lp|llc|l\.l\.c\.|holdings? inc\.?|group inc\.?)$", re.I)


def clean_name(name: str) -> str:
    s = str(name or "").strip()
    s = _CUT.sub("", s).strip(" ,.-")
    for _ in range(2):
        s2 = _SUFFIX.sub("", s).strip(" ,.-")
        if not s2:
            break
        s = s2
    return s or str(name or "").strip()


def disp(s: str) -> str:
    """Display / TradingView form of a symbol: BRK/B and BRK-B both become BRK.B."""
    return str(s).replace("/", ".").replace("-", ".")


def norm_sym(s: str) -> str:
    return str(s).strip().upper().replace("/", "-").replace(".", "-")


NAS_HE = {"Technology": "טכנולוגיה", "Finance": "פיננסים", "Health Care": "בריאות", "Consumer Discretionary": "צריכה מחזורית",
          "Industrials": "תעשייה", "Real Estate": "נדל\"ן", "Utilities": "תשתיות", "Energy": "אנרגיה", "Consumer Staples": "צריכה בסיסית",
          "Telecommunications": "תקשורת", "Basic Materials": "חומרי גלם", "Miscellaneous": "שונות", "Uncategorized": "ללא סיווג"}
GICS_HE = {"Information Technology": "טכנולוגיית מידע", "Financials": "פיננסים", "Health Care": "בריאות",
           "Consumer Discretionary": "צריכה מחזורית", "Industrials": "תעשייה", "Real Estate": "נדל\"ן", "Utilities": "תשתיות",
           "Energy": "אנרגיה", "Consumer Staples": "צריכה בסיסית", "Communication Services": "שירותי תקשורת", "Materials": "חומרים"}
# for S&P 500 members that NASDAQ's list leaves out, the nearest NASDAQ sector
GICS_TO_NAS = {"Information Technology": "Technology", "Financials": "Finance", "Health Care": "Health Care",
               "Consumer Discretionary": "Consumer Discretionary", "Industrials": "Industrials", "Real Estate": "Real Estate",
               "Utilities": "Utilities", "Energy": "Energy", "Consumer Staples": "Consumer Staples",
               "Communication Services": "Telecommunications", "Materials": "Basic Materials"}


# --------------------------------------------------------------------------- snapshots
def _git(args: list[str], timeout: int = 300) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, timeout=timeout).stdout


def clone_snapshots(depth: int = 45):
    d = CACHE / "tickers"
    shutil.rmtree(d, ignore_errors=True)
    d.parent.mkdir(parents=True, exist_ok=True)
    _git(["clone", "-q", "--depth", str(depth), "--single-branch", "--branch", "main", SNAP_REPO, str(d)])
    return d


def session_of(t: dt.datetime, trading_days: list[str]) -> str | None:
    """Which session a snapshot committed at time t holds. None when it may hold an unfinished day."""
    t = t.astimezone(dt.timezone.utc)
    mins = t.hour * 60 + t.minute
    d = t.date().isoformat()
    if mins < 13 * 60:                 # before the US open (13:30 UTC in summer, 14:30 in winter)
        cand = [x for x in trading_days if x < d]
    elif mins >= 21 * 60 + 30:         # after the close has settled
        cand = [x for x in trading_days if x <= d]
    else:
        return None
    return cand[-1] if cand else None


def snapshot_sessions(repo, trading_days: list[str]) -> dict[str, str]:
    """{session: commit} for every snapshot that clearly holds one finished session (newest commit wins)."""
    log = _git(["-C", str(repo), "log", "--format=%H %cI", "--", "tickers/all.csv"]).split("\n")
    out = {}
    for line in log:
        if not line.strip():
            continue
        h, t = line.split()
        s = session_of(dt.datetime.fromisoformat(t), trading_days)
        if s is not None and s not in out:
            out[s] = h
    return out


def load_snapshot(repo, commit: str) -> pd.DataFrame | None:
    raw = _git(["-C", str(repo), "show", f"{commit}:tickers/all.csv"], timeout=60)
    df = pd.read_csv(io.StringIO(raw), dtype={"symbol": str})
    if "close" not in df.columns:
        if "price" not in df.columns:
            return None
        df["close"] = df["price"]       # snapshots from before OHLC was added: NASDAQ's last sale
    return df.drop_duplicates("symbol").set_index("symbol")


def pick_session(have: dict, trading_days: list[str], pos: int, slack: int = 4) -> str | None:
    """The stored session at trading-day position pos, or the nearest earlier one within `slack` days."""
    for k in range(slack + 1):
        if pos - k < 0:
            return None
        d = trading_days[pos - k]
        if d in have:
            return d
    return None


def read_snapshots(repo, trading_days: list[str], offsets: tuple[int, ...]) -> tuple[dict[str, pd.DataFrame], dict[int, str]]:
    """Load only the snapshots at the given session offsets back from the newest one."""
    have = snapshot_sessions(repo, trading_days)
    if not have:
        return {}, {}
    asof = max(have)
    ti = trading_days.index(asof)
    at, snaps = {}, {}
    for off in offsets:
        d = pick_session(have, trading_days, ti - off, 0 if off == 0 else 4)
        if d is None:
            continue
        if d not in snaps:
            df = load_snapshot(repo, have[d])
            if df is None:
                continue
            snaps[d] = df
        at[off] = d
    return snaps, at


# --------------------------------------------------------------------------- core computation
LOOK, SKIP = 126, 21          # RS = 6-month return excluding the most recent month


def rank_rs(raw: pd.Series) -> pd.Series:
    """Percentile of each value in its own distribution, rounded up to 1..100."""
    pct = raw.rank(method="max", pct=True)
    return np.ceil(pct * 100).clip(1, 100).astype(int)


def rs_against(x: float, dist: np.ndarray) -> int | None:
    if x is None or not math.isfinite(x) or len(dist) == 0:
        return None
    frac = float(np.searchsorted(np.sort(dist), x, side="right")) / len(dist)
    return int(min(100, max(1, math.ceil(frac * 100))))


def rs_from_quantiles(x: float, q: np.ndarray) -> int | None:
    if x is None or not math.isfinite(x):
        return None
    frac = float(np.interp(x, q, np.linspace(0, 1, len(q))))
    return int(min(100, max(1, math.ceil(frac * 100))))


_SPLIT_FACTORS = (1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 35, 40, 50, 60, 75, 100, 150, 200, 250)


def split_between(a: pd.DataFrame, b: pd.DataFrame, syms, tol: float = 1.4) -> set:
    """Stocks whose price moved very differently from their market value between two snapshots: a split,
    a reverse split or another change in the share count, which unadjusted closes cannot show."""
    j = [s for s in syms if s in a.index and s in b.index]
    if not j:
        return set()
    pr = (b.loc[j, "close"] / a.loc[j, "close"]).astype(float)
    mr = (b.loc[j, "marketCap"] / a.loc[j, "marketCap"]).astype(float)
    q = np.exp((np.log(pr) - np.log(mr)).abs())
    # new shares from offerings change the share count by arbitrary amounts and the price return stays real;
    # a split changes it by a round factor
    near = q.map(lambda x: math.isfinite(x) and x >= tol and any(abs(x / k - 1) < 0.08 for k in _SPLIT_FACTORS))
    return set(q[near].index)


def validate(snaps: dict[str, pd.DataFrame], yfc: pd.DataFrame | None) -> dict:
    """How well each snapshot agrees with Yahoo's S&P 500 closes for the session it is mapped to."""
    rep = {}
    if yfc is None or yfc.empty:
        return rep
    for s, df in snaps.items():
        if s not in yfc.index:
            continue
        m = {norm_sym(k): k for k in df.index}
        cols = [c for c in yfc.columns if c in m]
        a = df.loc[[m[c] for c in cols], "close"].to_numpy(dtype=float)
        b = yfc.loc[s, cols].to_numpy(dtype=float)
        ok = np.isfinite(a) & np.isfinite(b) & (b > 0)
        if ok.sum() < 200:
            continue
        rep[s] = {"n": int(ok.sum()), "match": round(float((np.abs(a[ok] / b[ok] - 1) < 0.005).mean()), 4)}
    return rep


def compute(snaps: dict[str, pd.DataFrame], at: dict[int, str], members: dict | None = None,
            yfc: pd.DataFrame | None = None) -> dict:
    """RS for every US stock: percentile of the return from t-126 to t-21 sessions (6 months, skipping the last month).
    snaps = {session: snapshot}, at = {offset: session}; members = {yahoo_symbol: (name, gics)}; yfc = Yahoo closes of members."""
    for k in (0, SKIP, LOOK):
        if k not in at:
            raise ValueError(f"no snapshot {k} sessions back")
    val = validate({at[k]: snaps[at[k]] for k in at}, yfc)
    bad = [s for s, v in val.items() if v["match"] < 0.8]
    if bad:
        raise ValueError(f"snapshots disagree with Yahoo on {', '.join(bad)}")
    t0, t1, t6 = snaps[at[0]], snaps[at[SKIP]], snaps[at[LOOK]]
    kinds = t0["name"].fillna("").map(security_kind)
    excluded = {k: int(v) for k, v in kinds[kinds != "stock"].value_counts().items()}
    base = [s for s in t0.index if kinds[s] == "stock"]
    info = {s: {"name": clean_name(t0.at[s, "name"]), "sec": str(t0.at[s, "industry"] or "Uncategorized"),
                "mcap": float(t0.at[s, "marketCap"]) / 1e6 if pd.notna(t0.at[s, "marketCap"]) and t0.at[s, "marketCap"] > 0 else None}
            for s in base}

    def closes(off):
        d = at.get(off)
        return snaps[d]["close"].reindex(base).astype(float) if d else pd.Series(np.nan, index=base)
    px = pd.DataFrame({off: closes(off) for off in at})
    src = pd.Series("nasdaq", index=base, dtype=object)
    # S&P 500 members: split-adjusted Yahoo closes at the same sessions (also those NASDAQ's list leaves out)
    gics, spset = {}, set()
    if members:
        bymap = {norm_sym(s): s for s in base}
        for ysym, (nm, sec) in members.items():
            key = bymap.get(norm_sym(ysym))
            if yfc is not None and ysym in yfc.columns:
                yv = {off: yfc[ysym].get(d, np.nan) for off, d in at.items()}
                if all(pd.notna(yv.get(k)) for k in (0, SKIP, LOOK)):
                    if key is None:
                        key = norm_sym(ysym)
                        info[key] = {"name": nm, "sec": GICS_TO_NAS.get(sec, "Uncategorized"), "mcap": None}
                    px.loc[key] = pd.Series(yv)
                    src[key] = "yahoo"
            if key is not None:
                gics[key] = sec
                spset.add(key)
    nas = [s for s in px.index if src.get(s, "nasdaq") == "nasdaq"]
    ca = split_between(t6, t1, nas) | split_between(t1, t0, nas)
    prev_ok = (SKIP + 5) in at and (LOOK + 5) in at
    if prev_ok:
        ca_prev = split_between(snaps[at[LOOK + 5]], snaps[at[SKIP + 5]], nas)

    def ranked(o1, o6, drop):
        r = (px[o1] / px[o6] - 1).replace([np.inf, -np.inf], np.nan)
        ok = r.notna() & (px[0] >= 1) & ~r.index.isin(list(drop))
        return r[ok]
    r61 = ranked(SKIP, LOOK, ca)
    rs = rank_rs(r61)
    prev = pd.Series(dtype=int)
    r61p = pd.Series(dtype=float)
    if prev_ok:
        r61p = ranked(SKIP + 5, LOOK + 5, ca_prev)
        prev = rank_rs(r61p)
    m1 = (px[0] / px[SKIP] - 1).where(~px.index.isin(list(ca)))
    rows = []
    order = sorted(r61.index, key=lambda s: (-int(rs[s]), -float(r61[s])))
    for s in order:
        inf = info.get(s, {"name": s, "sec": "Uncategorized", "mcap": None})
        rows.append([disp(s), inf["name"], inf["sec"], gics.get(s, ""), 1 if s in spset else 0,
                     None if inf["mcap"] is None else round(inf["mcap"], 1), round(float(px.at[s, 0]), 2),
                     round(float(r61[s]) * 100, 2), None if pd.isna(m1.get(s)) else round(float(m1[s]) * 100, 2),
                     int(rs[s]), int(prev[s]) if s in prev.index else None])
    df = pd.DataFrame({"rs": rs, "ret": r61, "rsPrev": prev.reindex(r61.index) if len(prev) else np.nan,
                       "sec": [info[s]["sec"] for s in r61.index], "gics": [gics.get(s, "") for s in r61.index],
                       "mcap": [info[s]["mcap"] for s in r61.index], "sp": [s in spset for s in r61.index]}, index=r61.index)

    def sector_rows(d: pd.DataFrame, key: str, he: dict) -> list[dict]:
        out = []
        for sec, g in d.groupby(key):
            if not sec:
                continue
            w = g["mcap"].astype(float)
            okw = w.notna() & (w > 0)
            cap_ret = float((g.loc[okw, "ret"] * w[okw]).sum() / w[okw].sum()) if okw.any() else float(g["ret"].median())
            big = g[(g["mcap"].astype(float) >= 1000) | (g["sp"])]
            lead = big.assign(_r=g["ret"]).sort_values(["rs", "_r"], ascending=False).head(5)
            out.append({"sector": sec, "heb": he.get(sec, sec), "n": int(len(g)), "med": float(g["rs"].median()),
                        "mean": round(float(g["rs"].mean()), 1),
                        "p80": round(float((g["rs"] >= 80).mean() * 100), 1), "p20": round(float((g["rs"] <= 20).mean() * 100), 1),
                        "ret": round(cap_ret * 100, 2),
                        "medPrev": None if g["rsPrev"].notna().sum() < 0.5 * len(g) else float(g["rsPrev"].median()),
                        "leaders": [[disp(s), int(r["rs"])] for s, r in lead.iterrows()]})
        out.sort(key=lambda x: (-x["med"], -x["p80"]))
        for i, x in enumerate(out):
            x["rank"] = i + 1
        return out

    shown_ca = sorted(s for s in ca if s in px.index and pd.notna(px.at[s, 0]) and px.at[s, 0] >= 1)
    return {
        "asof": at[0], "from": at[LOOK], "to": at[SKIP], "prevAsof": at.get(5) if prev_ok else None,
        "method": "6-1",
        "n": len(rows), "nSp": int(df["sp"].sum()), "nYahoo": int(sum(1 for s in r61.index if src.get(s) == "yahoo")),
        "universe": int(len(t0)), "excludedTypes": excluded, "excludedFlat": 0,
        "corporateActions": [{"sym": disp(s), "name": info.get(s, {}).get("name", s), "why": "פיצול או שינוי במספר המניות בחלון"} for s in shown_ca],
        "validation": {"sessions": val, "spxTrack": {}, "dropped": []},
        "sectors": {"nas": sector_rows(df, "sec", NAS_HE), "gics": sector_rows(df[df["sp"]], "gics", GICS_HE)},
        "cols": ["sym", "name", "sec", "gics", "sp", "mcap", "px", "ret", "m1", "rs", "rsPrev"],
        "rows": rows,
        "_dist_now": r61.to_numpy(), "_dist_prev": r61p.to_numpy(),
        "_dists": {at[0]: np.quantile(r61.to_numpy(), np.linspace(0, 1, 101))} if len(r61) > 500 else {},
    }


# --------------------------------------------------------------------------- ETFs
def read_wide(path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, index_col=0)
    df.index = df.index.astype(str)
    return df.sort_index()


def merge_wide(path, new: pd.DataFrame) -> pd.DataFrame:
    cur = read_wide(path)
    if new.empty:
        return cur
    out = cur.reindex(index=cur.index.union(new.index), columns=list(dict.fromkeys(list(cur.columns) + list(new.columns))))
    for col in new.columns:
        v = new[col].dropna()
        out.loc[v.index, col] = v.values
    out = out.sort_index()
    out.index.name = "date"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, float_format="%.6g")
    return out


def ret61(c: pd.Series, d: str) -> float | None:
    c = c.dropna()
    c = c[c.index <= d]
    if len(c) <= LOOK or c.index[-1] != d:
        return None
    return float(c.iloc[-1 - SKIP] / c.iloc[-1 - LOOK] - 1)


def etf_rs(res: dict, px: pd.DataFrame, groups: dict[str, list[str]]) -> dict:
    """6-1 RS of each factor, sector and theme ETF against the same stock distribution, plus its rank among peers."""
    dist = merge_wide(DIST_CSV, pd.DataFrame({d: q for d, q in res["_dists"].items()}).T.rename(columns=lambda i: f"q{i}"))
    asof, prev_d = res["asof"], res["prevAsof"]
    syms = list(dict.fromkeys(s for g in groups.values() for s in g if s in px.columns))
    hist, cur = {}, {}
    for sym in syms:
        c = px[sym]
        hs = {}
        for d in dist.index:
            r = ret61(c, d)
            if r is not None:
                hs[d] = rs_from_quantiles(r, dist.loc[d].to_numpy(dtype=float))
        r_now = ret61(c, asof)
        if r_now is not None:
            hs[asof] = rs_against(r_now, res["_dist_now"])
        if prev_d and len(res["_dist_prev"]):
            r_prev = ret61(c, prev_d)
            if r_prev is not None:
                hs[prev_d] = rs_against(r_prev, res["_dist_prev"])
        hist[sym] = hs
        if r_now is not None:
            cur[sym] = {"rs": hs.get(asof), "raw": round(r_now, 4), "ret61": round(r_now, 4)}
    wide = pd.DataFrame(hist)
    allrs = merge_wide(ETF_CSV, wide) if not wide.empty else read_wide(ETF_CSV)
    for sym, rec in cur.items():
        s = allrs[sym].dropna() if sym in allrs.columns else pd.Series(dtype=float)
        s = s[s.index <= asof]
        rec["rsPrev"] = int(s[prev_d]) if prev_d and prev_d in s.index else None
        rec["rsHist"] = [[d, int(v)] for d, v in s.iloc[-40:].items()]
    for g, gs in groups.items():
        peer = sorted([s for s in gs if s in cur and cur[s]["rs"] is not None], key=lambda s: -cur[s]["raw"])
        for i, s in enumerate(peer):
            cur[s].setdefault("peer", {})[g] = [i + 1, len(peer)]
    return {"asof": asof, "prevAsof": prev_d, "from": res["from"], "to": res["to"], "method": "6-1", "items": cur}


def fill_mcaps(res: dict, budget_s: float = 60) -> None:
    """Market caps for the S&P 500 members NASDAQ's list leaves out (best effort, from Yahoo)."""
    import time
    i_sym, i_mcap, i_sp = res["cols"].index("sym"), res["cols"].index("mcap"), res["cols"].index("sp")
    todo = [r for r in res["rows"] if r[i_mcap] is None and r[i_sp]]
    if not todo:
        return
    try:
        import yfinance as yf
    except ImportError:
        return
    t0 = time.time()
    for r in todo:
        if time.time() - t0 > budget_s:
            break
        try:
            v = yf.Ticker(r[i_sym].replace(".", "-")).fast_info["marketCap"]
            if v and math.isfinite(float(v)) and float(v) > 0:
                r[i_mcap] = round(float(v) / 1e6, 1)
        except Exception:
            continue


def payload(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def run(px: pd.DataFrame, u: dict, members: dict | None, yf_members: dict | None, ohlc_etf: dict | None = None) -> tuple[dict, str]:
    """members = {yahoo_symbol: (name, gics_sector)}; yf_members = {"close": ...} Yahoo bars of the S&P 500 members."""
    spx = px["^GSPC"].dropna() if "^GSPC" in px.columns else None
    if spx is None or spx.empty:
        raise ValueError("no S&P 500 closes for the trading calendar")
    days = list(spx.index)
    repo = clone_snapshots(depth=200)
    offsets = (0, 5, SKIP, SKIP + 5, LOOK, LOOK + 5)
    snaps, at = read_snapshots(repo, days, offsets)
    res = compute(snaps, at, members, yf_members["close"] if yf_members else None)
    fill_mcaps(res)
    out = payload(res)
    dump_json(RS_JSON, out)
    groups = {g["id"]: [it["sym"] for it in g["items"]] for g in u["groups"] if g["kind"] == "factor"}
    etf = etf_rs(res, px, groups)
    dump_json(ETF_JSON, etf)
    shutil.rmtree(repo, ignore_errors=True)
    v = res["validation"]["sessions"]
    worst = min((x["match"] for x in v.values()), default=None)
    msg = (f"{res['n']:,} מניות · 6-1: {res['from']} עד {res['to']} (נכון ל-{res['asof']})"
           + (f" · התאמה ל-Yahoo: {worst * 100:.1f}% לפחות" if worst is not None else "")
           + (f" · {len(res['corporateActions'])} הוצאו בגלל פיצול" if res["corporateActions"] else "")
           + f" · {len(etf.get('items', {}))} תעודות סל")
    return out, msg
