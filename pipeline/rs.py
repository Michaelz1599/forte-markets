"""Relative strength (RS) for every US stock, and for the factor, sector and theme ETFs.

The method is the one on the RS Leaders page:
    move in ATR  = (Close_t - Close_t-10) / ATR(10)        ATR = mean True Range of the last 10 sessions
    RS           = percentile of that move across all ranked US common stocks, rounded up to 1..100

Stock prices come from the daily snapshots of NASDAQ's stock list (OHLC, market cap, sector) kept
in the git history of ozkanpakdil/top-us-stock-tickers. Each snapshot is taken before the US open
and holds the previous session. S&P 500 members use Yahoo daily bars instead (split-adjusted, and
it covers the members NASDAQ's list leaves out); the overlap is also how each snapshot is validated.
ETFs are ranked against the same stock distribution, so an ETF's RS is on the same scale as a stock's.
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
DIST_CSV = DERIVED / "rs_dist.csv"      # daily quantiles of the stock distribution (for ETF RS history)
ETF_CSV = DERIVED / "rs_etf.csv"        # daily RS of every ETF in the universe
RS_JSON = DERIVED / "rs.json"           # the stock table and sector ranking (site payload)
ETF_JSON = DERIVED / "rs_etf.json"      # current ETF RS, merged into markets.json at build time
N = 10                                  # look-back and ATR length, in sessions
PREV = 5                                # "a week ago" = 5 sessions back

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


def read_snapshots(repo, trading_days: list[str], want: int = 22) -> dict[str, pd.DataFrame]:
    log = _git(["-C", str(repo), "log", "--format=%H %cI", "--", "tickers/all.csv"]).split("\n")
    out = {}
    for line in log:
        if not line.strip():
            continue
        h, t = line.split()
        s = session_of(dt.datetime.fromisoformat(t), trading_days)
        if s is None or s in out:
            continue          # newest commit for a session wins; commits during market hours are skipped
        raw = _git(["-C", str(repo), "show", f"{h}:tickers/all.csv"], timeout=60)
        df = pd.read_csv(io.StringIO(raw), dtype={"symbol": str})
        if not {"symbol", "high", "low", "close"}.issubset(df.columns):
            continue          # snapshots from before OHLC was added
        df = df.drop_duplicates("symbol").set_index("symbol")
        out[s] = df
        if len(out) >= want:
            break
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- core computation
def window_stats(c: pd.DataFrame, h: pd.DataFrame, lo: pd.DataFrame, end: int) -> pd.DataFrame:
    """moveATR, return and ATR% over sessions end-N..end (row positions) for every column with full data.
    raw is NaN when the range was zero all window long."""
    if end - N < 0:
        return pd.DataFrame(columns=["raw", "ret", "atr", "flat"])
    cw, hw, lw = c.iloc[end - N:end + 1], h.iloc[end - N:end + 1], lo.iloc[end - N:end + 1]
    full = cw.notna().all() & hw.iloc[1:].notna().all() & lw.iloc[1:].notna().all() & (cw > 0).all()
    cw, hw, lw = cw.loc[:, full], hw.loc[:, full], lw.loc[:, full]
    prev = cw.shift(1).iloc[1:]
    hh, ll = hw.iloc[1:], lw.iloc[1:]
    tr = pd.concat([(hh - ll), (hh - prev).abs(), (ll - prev).abs()]).groupby(level=0).max()
    atr = tr.mean()
    move = cw.iloc[-1] - cw.iloc[0]
    flat = (cw.diff().iloc[1:] == 0).sum()
    df = pd.DataFrame({"raw": move / atr.replace(0, np.nan), "ret": cw.iloc[-1] / cw.iloc[0] - 1,
                       "atr": atr / cw.iloc[-1], "flat": flat, "close": cw.iloc[-1]})
    return df.replace([np.inf, -np.inf], np.nan)


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


_SPLITS = [2, 3, 4, 5, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100, 1.5]


def split_like(r: float) -> bool:
    if not math.isfinite(r) or r <= 0 or 0.55 < r < 1.8:
        return False
    return any(abs(r / k - 1) < 0.04 or abs(r * k - 1) < 0.04 for k in _SPLITS)


def corporate_actions(snaps: dict[str, pd.DataFrame], sessions: list[str], syms) -> dict[str, str]:
    """Symbols whose price series is broken inside the window by a split or another corporate action.

    NASDAQ's own last-sale price in snapshot s+1 is the close of session s, so a gap between it and the
    Yahoo close in snapshot s means one side was adjusted and the other not."""
    flags = {}
    for a, b in zip(sessions, sessions[1:]):
        A, B = snaps.get(a), snaps.get(b)
        if A is None or B is None or "price" not in B.columns:
            continue
        j = A.index.intersection(B.index)
        d = (B.loc[j, "price"] / A.loc[j, "close"] - 1).abs().dropna()
        if len(d) and (d > 0.02).mean() > 0.03:
            continue          # the whole pair disagrees: a timing problem, not corporate actions
        for s in d[d > 0.02].index:
            flags.setdefault(s, f"{b}: מחיר NASDAQ {B.at[s, 'price']:.2f} מול סגירה {A.at[s, 'close']:.2f}")
    last, prev = sessions[-1], sessions[-2]
    L, P = snaps.get(last), snaps.get(prev)
    if L is not None and P is not None:
        j = L.index.intersection(P.index)
        r = (L.loc[j, "close"] / P.loc[j, "close"]).dropna()
        for s, v in r.items():
            if split_like(float(v)):
                flags.setdefault(s, f"{last}: יחס {v:.2f} ביום אחד, כמו פיצול")
    return {s: m for s, m in flags.items() if s in set(syms)}


def validate(snaps: dict[str, pd.DataFrame], yfc: pd.DataFrame | None, spx: pd.Series | None) -> dict:
    """How well each snapshot agrees with Yahoo's S&P 500 closes for the session it is mapped to."""
    rep = {"sessions": {}}
    if yfc is not None and not yfc.empty:
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
            share = float((np.abs(a[ok] / b[ok] - 1) < 0.005).mean())
            rep["sessions"][s] = {"n": int(ok.sum()), "match": round(share, 4)}
    if spx is not None and len(snaps) > 1:
        diffs = {}
        ss = sorted(snaps)
        for a, b in zip(ss, ss[1:]):
            if a not in spx.index or b not in spx.index:
                continue
            A, B = snaps[a], snaps[b]
            j = A.index.intersection(B.index)
            w = B.loc[j, "marketCap"].astype(float)
            r = B.loc[j, "close"] / A.loc[j, "close"] - 1
            ok = r.notna() & w.notna() & (w > 1e10) & (r.abs() < 0.5)
            if ok.sum() < 100:
                continue
            cw = float((r[ok] * w[ok]).sum() / w[ok].sum())
            diffs[b] = round((cw - float(spx[b] / spx[a] - 1)) * 100, 3)
        rep["spxTrack"] = diffs
    return rep


def build_panel(snaps: dict[str, pd.DataFrame], sessions: list[str]):
    fields = {}
    for f in ("close", "high", "low"):
        fields[f] = pd.DataFrame({s: snaps[s][f] for s in sessions if s in snaps}).T.reindex(sessions).apply(pd.to_numeric, errors="coerce")
    return fields["close"], fields["high"], fields["low"]


def compute(snaps: dict[str, pd.DataFrame], trading_days: list[str], members: dict | None = None,
            yf: dict[str, pd.DataFrame] | None = None, spx: pd.Series | None = None) -> dict:
    """Everything the site needs. members = {yahoo_symbol: (name, gics_sector)}; yf = {"close","high","low"} frames."""
    if not snaps:
        raise ValueError("no usable snapshots")
    asof = max(snaps)
    ti = trading_days.index(asof)
    sessions = trading_days[max(0, ti - N - PREV - 5):ti + 1]
    have = [s for s in sessions if s in snaps]
    need_now = trading_days[ti - N:ti + 1]
    missing_now = [s for s in need_now if s not in snaps]
    if missing_now:
        raise ValueError(f"missing snapshots for {', '.join(missing_now)}")
    rep = validate({s: snaps[s] for s in have}, yf["close"] if yf else None, spx)
    bad = [s for s, v in rep["sessions"].items() if v["match"] < 0.8 and s in need_now]
    if bad:
        raise ValueError(f"snapshots disagree with Yahoo on {', '.join(bad)}")

    last = snaps[asof]
    kinds = last["name"].fillna("").map(security_kind)
    excluded = {k: int(v) for k, v in kinds[kinds != "stock"].value_counts().items()}
    base = [s for s in last.index if kinds[s] == "stock"]
    c, h, lo = build_panel(snaps, sessions)
    c, h, lo = c[base], h[base], lo[base]
    src = pd.Series("nasdaq", index=base, dtype=object)
    info = {s: {"name": clean_name(last.at[s, "name"]), "sec": str(last.at[s, "industry"] or "Uncategorized"),
                "mcap": float(last.at[s, "marketCap"]) / 1e6 if pd.notna(last.at[s, "marketCap"]) and last.at[s, "marketCap"] > 0 else None}
            for s in base}

    # S&P 500 members: Yahoo bars when Yahoo has the full window, also for members NASDAQ's list leaves out
    gics, spset = {}, set()
    if members:
        bymap = {norm_sym(s): s for s in base}
        oc, oh, ol = {}, {}, {}
        for ysym, (nm, sec) in members.items():
            key = bymap.get(norm_sym(ysym))
            if yf and ysym in yf["close"].columns:
                yc = yf["close"][ysym].reindex(sessions)
                yh = yf["high"][ysym].reindex(sessions)
                yl = yf["low"][ysym].reindex(sessions)
                if yc.loc[need_now].notna().all() and yh.loc[need_now].notna().all() and yl.loc[need_now].notna().all():
                    if key is None:
                        key = norm_sym(ysym)
                        info[key] = {"name": nm, "sec": GICS_TO_NAS.get(sec, "Uncategorized"), "mcap": None}
                    oc[key], oh[key], ol[key] = yc, yh, yl
                    src[key] = "yahoo"
            if key is not None:
                gics[key] = sec
                spset.add(key)
        if oc:
            def over(base_df, o):
                o = pd.DataFrame(o, index=sessions)
                return pd.concat([base_df.drop(columns=[k for k in o.columns if k in base_df.columns]), o], axis=1)
            c, h, lo = over(c, oc), over(h, oh), over(lo, ol)
    syms = list(c.columns)
    ca = corporate_actions(snaps, have, [s for s in syms if src.get(s) == "nasdaq"])

    def ranked(end_pos: int) -> pd.DataFrame:
        w = window_stats(c, h, lo, end_pos)
        w = w[~w.index.isin(list(ca))]
        w = w[(w["flat"] < 4) & (w["close"] >= 1)]
        return w.dropna(subset=["raw"])

    pos_now = len(sessions) - 1
    now = ranked(pos_now)
    now["rs"] = rank_rs(now["raw"])
    prev = pd.DataFrame()
    pos_prev = pos_now - PREV
    prev_date = sessions[pos_prev] if pos_prev >= 0 else None
    if pos_prev - N >= 0 and all(s in snaps for s in sessions[pos_prev - N:pos_prev + 1]):
        prev = ranked(pos_prev)
        prev["rs"] = rank_rs(prev["raw"])

    # the distribution of every date the stored snapshots can cover (for the ETF RS history)
    dists = {}
    for p in range(N, len(sessions)):
        if all(s in snaps for s in sessions[p - N:p + 1]):
            w = ranked(p)
            if len(w) > 500:
                dists[sessions[p]] = np.quantile(w["raw"].to_numpy(), np.linspace(0, 1, 101))

    w_all = window_stats(c, h, lo, pos_now)
    n_flat = int(((w_all["flat"] >= 4) & (w_all["close"] >= 1)).sum())
    # report only the corporate actions that removed a stock that would otherwise be ranked
    ca_shown = {s: m for s, m in ca.items() if s in w_all.index and w_all.at[s, "close"] >= 1 and w_all.at[s, "flat"] < 4}
    rows = []
    for s, r in now.sort_values(["rs", "raw"], ascending=False).iterrows():
        inf = info.get(s, {"name": s, "sec": "Uncategorized", "mcap": None})
        rp = int(prev.at[s, "rs"]) if s in prev.index else None
        rows.append([disp(s), inf["name"], inf["sec"], gics.get(s, ""),
                     1 if s in spset else 0, None if inf["mcap"] is None else round(inf["mcap"], 1),
                     round(float(r["close"]), 2), round(float(r["ret"]) * 100, 2), round(float(r["atr"]) * 100, 2),
                     round(float(r["raw"]), 2), int(r["rs"]), rp])
    df = now.assign(sec=[info[s]["sec"] for s in now.index], gics=[gics.get(s, "") for s in now.index],
                    mcap=[info[s]["mcap"] for s in now.index], sp=[s in spset for s in now.index])
    df["rsPrev"] = prev["rs"].reindex(df.index) if len(prev) else np.nan

    def sector_rows(d: pd.DataFrame, key: str, he: dict) -> list[dict]:
        out = []
        for sec, g in d.groupby(key):
            if not sec:
                continue
            w = g["mcap"].astype(float)
            okw = w.notna() & (w > 0)
            cap_ret = float((g.loc[okw, "ret"] * w[okw]).sum() / w[okw].sum()) if okw.any() else float(g["ret"].median())
            big = g[(g["mcap"].astype(float) >= 1000) | (g["sp"])]
            lead = big.sort_values(["rs", "raw"], ascending=False).head(5)
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

    mism = {s: v for s, v in rep["sessions"].items()}
    return {
        "asof": asof, "from": sessions[pos_now - N], "prevAsof": prev_date if len(prev) else None,
        "n": len(rows), "nSp": int(df["sp"].sum()), "nYahoo": int(sum(1 for s in now.index if src.get(s) == "yahoo")),
        "universe": int(len(last)), "excludedTypes": excluded, "excludedFlat": n_flat,
        "corporateActions": [{"sym": disp(s), "name": info.get(s, {}).get("name", s), "why": m} for s, m in sorted(ca_shown.items())],
        "validation": {"sessions": mism, "spxTrack": rep.get("spxTrack", {})},
        "sectors": {"nas": sector_rows(df, "sec", NAS_HE), "gics": sector_rows(df[df["sp"]], "gics", GICS_HE)},
        "cols": ["sym", "name", "sec", "gics", "sp", "mcap", "px", "ret", "atr", "raw", "rs", "rsPrev"],
        "rows": rows,
        "_dist_now": now["raw"].to_numpy(), "_dist_prev": prev["raw"].to_numpy() if len(prev) else np.array([]),
        "_dists": dists,
    }


# --------------------------------------------------------------------------- ETFs
def etf_moves(c: pd.Series, h: pd.Series, lo: pd.Series) -> pd.Series:
    """moveATR for every date of one instrument's daily bars."""
    j = pd.concat([c, h, lo], axis=1, keys=["c", "h", "l"]).dropna()
    if len(j) <= N:
        return pd.Series(dtype=float)
    pc = j["c"].shift(1)
    tr = pd.concat([j["h"] - j["l"], (j["h"] - pc).abs(), (j["l"] - pc).abs()], axis=1).max(axis=1)
    tr[pc.isna()] = np.nan
    atr = tr.rolling(N, min_periods=N).mean()
    return ((j["c"] - j["c"].shift(N)) / atr.replace(0, np.nan)).dropna()


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


def etf_rs(res: dict, ohlc: dict[str, pd.DataFrame], groups: dict[str, list[str]]) -> dict:
    """RS of each ETF against the stock distribution, now, a week ago and every stored date."""
    dist = merge_wide(DIST_CSV, pd.DataFrame({d: q for d, q in res["_dists"].items()}).T.rename(columns=lambda i: f"q{i}"))
    asof, prev_d = res["asof"], res["prevAsof"]
    hist = {}
    cur = {}
    for sym in ohlc["close"].columns:
        mv = etf_moves(ohlc["close"][sym], ohlc["high"][sym], ohlc["low"][sym])
        if mv.empty:
            continue
        hs = {}
        for d in dist.index:
            if d in mv.index:
                hs[d] = rs_from_quantiles(float(mv[d]), dist.loc[d].to_numpy(dtype=float))
        if asof in mv.index:
            hs[asof] = rs_against(float(mv[asof]), res["_dist_now"])
        if prev_d and prev_d in mv.index and len(res["_dist_prev"]):
            hs[prev_d] = rs_against(float(mv[prev_d]), res["_dist_prev"])
        hist[sym] = hs
        if asof in mv.index:
            c = ohlc["close"][sym].dropna()
            i = c.index.get_loc(asof)
            cur[sym] = {"rs": hs.get(asof), "raw": round(float(mv[asof]), 2),
                        "ret10": round(float(c.iloc[i] / c.iloc[i - N] - 1), 4) if i >= N else None}
    wide = pd.DataFrame(hist)
    allrs = merge_wide(ETF_CSV, wide) if not wide.empty else read_wide(ETF_CSV)
    for sym, rec in cur.items():
        s = allrs[sym].dropna() if sym in allrs.columns else pd.Series(dtype=float)
        s = s[s.index <= asof]
        rec["rsPrev"] = int(s[prev_d]) if prev_d and prev_d in s.index else None
        rec["rsHist"] = [[d, int(v)] for d, v in s.iloc[-40:].items()]
    for g, syms in groups.items():
        peer = sorted([s for s in syms if s in cur and cur[s]["rs"] is not None], key=lambda s: -cur[s]["raw"])
        for i, s in enumerate(peer):
            cur[s].setdefault("peer", {})[g] = [i + 1, len(peer)]
    return {"asof": asof, "prevAsof": prev_d, "from": res["from"], "items": cur}


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


def run(px: pd.DataFrame, u: dict, members: dict | None, yf_members: dict | None, ohlc_etf: dict | None) -> tuple[dict, str]:
    """members = {yahoo_symbol: (name, gics_sector)}; yf_members / ohlc_etf = {"close","high","low"} frames."""
    spx = px["^GSPC"].dropna() if "^GSPC" in px.columns else None
    if spx is None or spx.empty:
        raise ValueError("no S&P 500 closes for the trading calendar")
    days = list(spx.index)
    repo = clone_snapshots()
    snaps = read_snapshots(repo, days)
    res = compute(snaps, days, members, yf_members, spx)
    fill_mcaps(res)
    out = payload(res)
    dump_json(RS_JSON, out)
    etf = {}
    if ohlc_etf:
        groups = {g["id"]: [it["sym"] for it in g["items"]] for g in u["groups"] if g["kind"] == "factor"}
        etf = etf_rs(res, ohlc_etf, groups)
        dump_json(ETF_JSON, etf)
    shutil.rmtree(repo, ignore_errors=True)
    v = res["validation"]["sessions"]
    worst = min((x["match"] for x in v.values()), default=None)
    msg = (f"{res['n']:,} מניות · {res['from']} עד {res['asof']}"
           + (f" · התאמה ל-Yahoo: {worst * 100:.1f}% לפחות" if worst is not None else "")
           + (f" · {len(res['corporateActions'])} הוצאו בגלל פעולה תאגידית" if res["corporateActions"] else "")
           + (f" · {len(etf.get('items', {}))} תעודות סל" if etf else ""))
    return out, msg
