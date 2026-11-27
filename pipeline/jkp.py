"""Israeli factors (the Momentum tab, Israel view) from Global Factor Data by Jensen, Kelly & Pedersen (jkpfactors.com).

JKP publish monthly long-short returns of 153 factors and of 13 themes (each theme = the equal-weighted average of its
factors) for every country, as zipped CSV files in a public S3 bucket:
    https://jkpfactors-data.s3.amazonaws.com/public/[isr]_[all_factors]_[monthly]_[vw_cap].zip
(the selectors are wrapped in literal square brackets). "vw_cap" = capped value weighting, the one JKP recommend.
JKP publish a new release about once a year (the release of August 2026 ends in December 2025), so each run only
checks the Last-Modified header and downloads again when it changed; a failed run keeps the last good file.

From the returns this computes, for every theme and factor and for the last year, 3, 5 and 10 years and the whole
sample, the statistics JKP show on their Analysis page: annualised average return, volatility, Sharpe ratio, CAPM
alpha and beta against the Israeli market, information ratio, plus the compounded return. The monthly returns of the
themes and the market are kept for the charts. Output: data/derived/jkp_il.json (site: data/jkp_il.json).
"""
from __future__ import annotations

import datetime as dt
import email.utils
import io
import json
import math
import zipfile

import numpy as np
import pandas as pd

from .common import ROOT, dump_json, get, http

CFG = ROOT / "config" / "jkp.json"
OUT = ROOT / "data" / "derived" / "jkp_il.json"
PERIODS = (("y1", 12), ("y3", 36), ("y5", 60), ("y10", 120), ("all", None))
STAT_KEYS = ("ret", "vol", "sharpe", "alpha", "beta", "ir", "cum", "n")   # the order of each period's array


def load() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8"))


def url(cfg: dict, sel: str) -> str:
    b = lambda x: f"%5B{x}%5D"
    return f"{cfg['base']}{b(cfg['country'])}_{b(sel)}_{b('monthly')}_{b(cfg['weighting'])}.zip"


def read_zip_csv(raw: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if not names:
        raise ValueError("no CSV in the JKP archive")
    df = pd.read_csv(io.BytesIO(z.read(names[0])), na_values=["na", "NA", ""])
    need = {"name", "date", "ret"}
    if not need <= set(df.columns):
        raise ValueError(f"unexpected JKP columns: {list(df.columns)[:12]}")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m")
    df["ret"] = pd.to_numeric(df["ret"], errors="coerce")
    return df.dropna(subset=["ret"])


def _r(x, d=4):
    return None if x is None or not math.isfinite(x) else round(float(x), d)


def period_stats(r: pd.Series, m: pd.Series, months: int | None) -> list | None:
    """r, m: monthly returns indexed by 'YYYY-MM' on the same calendar (m = the market). The last `months` months of
    the calendar (None = all), with at least 80% of them present (24 months for the whole sample)."""
    if months:
        r = r.iloc[-months:]
    x = r.dropna()
    need = 24 if months is None else math.ceil(months * 0.8)
    if len(x) < need:
        return None
    mean, sd = x.mean(), x.std(ddof=1)
    ann, vol = mean * 12, sd * math.sqrt(12)
    sharpe = ann / vol if vol > 0 else None
    mm = m.reindex(x.index)
    ok = mm.notna()
    alpha = beta = ir = None
    if ok.sum() >= max(12, need * 0.8):
        xs, ms = x[ok].to_numpy(), mm[ok].to_numpy()
        vm = ms.var(ddof=1)
        if vm > 0:
            beta = float(np.cov(xs, ms, ddof=1)[0, 1] / vm)
            a = xs.mean() - beta * ms.mean()
            res = xs - a - beta * ms
            te = res.std(ddof=2) * math.sqrt(12) if len(res) > 2 else 0
            alpha = a * 12
            ir = alpha / te if te > 0 else None
    cum = float(np.prod(1 + x.to_numpy()) - 1)
    return [_r(ann), _r(vol), _r(sharpe, 3), _r(alpha), _r(beta, 3), _r(ir, 3), _r(cum), int(len(x))]


def build(fac: pd.DataFrame, th: pd.DataFrame | None, mkt: pd.DataFrame, cfg: dict, src: dict) -> dict:
    """fac: the all_factors file, th: the all_themes file (None = compute the themes from the factors), mkt: the
    market file. Returns the payload for data/jkp_il.json."""
    months = sorted(set(fac["date"]) | set(mkt["date"]) | (set(th["date"]) if th is not None else set()))
    # one calendar for everything: the factors' first month to the last month of any file
    first = min(fac["date"])
    months = [x for x in months if x >= min(first, min(mkt["date"]))]
    cal = pd.Index(months)
    m = mkt.drop_duplicates("date").set_index("date")["ret"].reindex(cal)
    fmap = cfg["factors"]
    wide = fac.pivot_table(index="date", columns="name", values="ret", aggfunc="last").reindex(cal)
    if th is None or th.empty:   # a theme = the equal-weighted average of its factors (checked against JKP's file)
        tw = {}
        for t in {v["theme"] for v in fmap.values()}:
            cols = [c for c in wide.columns if fmap.get(c, {}).get("theme") == t]
            if cols:
                tw[t] = wide[cols].mean(axis=1, skipna=True)
        thw = pd.DataFrame(tw)
    else:
        thw = th.pivot_table(index="date", columns="name", values="ret", aggfunc="last").reindex(cal)
    nfac = th.groupby("name")["n_factors"].last().to_dict() if th is not None and "n_factors" in th.columns else {}
    # check: JKP's theme returns against the average of the factors that config/jkp.json puts in each theme
    check = {}
    for t in thw.columns:
        cols = [c for c in wide.columns if fmap.get(c, {}).get("theme") == t]
        if cols:
            d = (thw[t] - wide[cols].mean(axis=1, skipna=True)).abs()
            check[t] = float(d.max()) if d.notna().any() else None
    asof = max(x for x in cal if thw.loc[x].notna().any())
    cal_end = list(cal).index(asof) + 1
    cal, m, wide, thw = cal[:cal_end], m.iloc[:cal_end], wide.iloc[:cal_end], thw.iloc[:cal_end]

    def stats_of(s: pd.Series, own_market: bool = False) -> dict:
        out = {k: period_stats(s, m, n) for k, n in PERIODS}
        if own_market:   # the market against itself: no alpha, beta or information ratio
            for v in out.values():
                if v:
                    v[3] = v[4] = v[5] = None
        return out

    tmeta = {t["id"]: t for t in cfg["themes"]}
    order = [t["id"] for t in cfg["themes"] if t["id"] in thw.columns] + sorted(c for c in thw.columns if c not in tmeta)
    themes = []
    for t in order:
        s = thw[t]
        nz = s.dropna()
        if nz.empty:
            continue
        meta = tmeta.get(t, {})
        themes.append({"id": t, "name": meta.get("name") or t.replace("_", " ").title(), "en": meta.get("en") or t.replace("_", " ").title(),
                       "desc": meta.get("desc", ""), "n": int(nfac[t]) if t in nfac else len([c for c in wide.columns if fmap.get(c, {}).get("theme") == t]),
                       "from": nz.index[0], "st": stats_of(s), "chk": _r(check.get(t), 8)})
    factors = []
    nst = fac.sort_values("date").groupby("name").last()
    for f in wide.columns:
        s = wide[f]
        nz = s.dropna()
        if nz.empty:
            continue
        meta = fmap.get(f, {})
        row = nst.loc[f] if f in nst.index else None
        factors.append({"id": f, "label": meta.get("label", f), "theme": meta.get("theme"), "from": nz.index[0], "last": nz.index[-1],
                        "dir": int(row["direction"]) if row is not None and "direction" in row and pd.notna(row["direction"]) else None,
                        "nst": int(row["n_stocks"]) if row is not None and "n_stocks" in row and pd.notna(row["n_stocks"]) else None,
                        "st": stats_of(s)})
    ser = lambda s: [_r(v, 5) for v in s.tolist()]
    mk_n = mkt.sort_values("date").drop_duplicates("date").set_index("date")
    return {
        "asof": asof, "from": cal[0], "months": list(cal),
        "src": {**src, "page": cfg.get("page"), "weighting": cfg["weighting"], "country": cfg["country"]},
        "keys": list(STAT_KEYS), "periods": [k for k, _ in PERIODS],
        "mkt": {"r": ser(m), "st": stats_of(m, True), "nst": int(mk_n["n_stocks"].iloc[-1]) if "n_stocks" in mk_n.columns and pd.notna(mk_n["n_stocks"].iloc[-1]) else None},
        "themes": themes,
        "series": {t["id"]: ser(thw[t["id"]]) for t in themes},
        "factors": factors,
    }


def _modified(headers) -> str | None:
    lm = headers.get("Last-Modified")
    if not lm:
        return None
    try:
        return email.utils.parsedate_to_datetime(lm).astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError):
        return None


def run(force: bool = False) -> tuple[dict, str]:
    cfg = load()
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    u_fac = url(cfg, "all_factors")
    # a new JKP release changes the archive's Last-Modified; until then the stored file stands
    try:
        h = http().head(u_fac, timeout=40)
        mod = _modified(h.headers) if h.status_code == 200 else None
    except Exception:
        mod = None
    if old and not force and mod and old.get("src", {}).get("modified") == mod:
        old["src"]["checked"] = now
        dump_json(OUT, old)
        return old, f"אין שחרור חדש · הנתונים עד {old['asof']} (שחרור {mod[:10]})"
    fac = read_zip_csv(get(u_fac, timeout=180).content)
    mkt = read_zip_csv(get(url(cfg, "mkt"), timeout=120).content)
    try:
        th = read_zip_csv(get(url(cfg, "all_themes"), timeout=120).content)
    except Exception:
        th = None
    if fac["name"].nunique() < 50 or mkt.empty:
        raise ValueError(f"JKP: only {fac['name'].nunique()} factors / {len(mkt)} market months")
    out = build(fac, th, mkt, cfg, {"modified": mod, "checked": now, "url": u_fac})
    if old and old.get("asof") and out["asof"] < old["asof"]:
        raise ValueError(f"JKP: the new file ends in {out['asof']}, before the stored one ({old['asof']})")
    dump_json(OUT, out)
    bad = [t["id"] for t in out["themes"] if t.get("chk") is not None and t["chk"] > 1e-6]
    unk = [f["id"] for f in out["factors"] if not f.get("theme")]
    msg = (f"{len(out['themes'])} נושאים ו-{len(out['factors'])} פקטורים, {out['from']} עד {out['asof']}"
           + (f" · שחרור {mod[:10]}" if mod else "")
           + (f" · נושאים שלא תואמים לרשימת הפקטורים: {', '.join(bad)}" if bad else "")
           + (f" · פקטורים בלי נושא: {', '.join(unk[:6])}" if unk else ""))
    return out, msg
