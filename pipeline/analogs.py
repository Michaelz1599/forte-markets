"""Macro analogs: the past months whose macro backdrop looked most like today's, what the S&P 500 did next,
how deep the drawdowns were, and which industries led or lagged (Ken French's 12 industry portfolios)."""
from __future__ import annotations

import datetime as dt
import io
import math
import zipfile

import numpy as np
import pandas as pd

from .common import ROOT, get, read_series

OUT = ROOT / "data" / "derived" / "macro_analogs.json"
FF_IND = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/12_Industry_Portfolios_CSV.zip"
FF_FAC = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip"
IND_HE = {"NoDur": "צריכה בסיסית", "Durbl": "מוצרים בני-קיימא ורכב", "Manuf": "תעשייה", "Enrgy": "אנרגיה", "Chems": "כימיקלים",
          "BusEq": "טכנולוגיה", "Telcm": "תקשורת", "Utils": "תשתיות", "Shops": "קמעונאות", "Hlth": "בריאות", "Money": "פיננסים", "Other": "אחר (בנייה, שירותים, תחבורה)"}
VARS = [  # key, Hebrew name, unit
    ("cpi_yoy", "אינפלציה שנתית (CPI)", "%"), ("cpi_chg6", "שינוי באינפלציה, חצי שנה", "נק'"), ("unrate", "אבטלה", "%"),
    ("unrate_chg6", "שינוי באבטלה, חצי שנה", "נק'"), ("fedfunds", "ריבית הפד", "%"), ("gs10", "תשואת 10 שנים", "%"),
    ("curve", "עקום 10 שנים פחות 2", "נק'"), ("baa", "מרווח אשראי BAA", "נק'")]


def _ff_table(url: str) -> pd.DataFrame:
    """The first monthly table of a Ken French CSV (rows YYYYMM), in percent."""
    z = zipfile.ZipFile(io.BytesIO(get(url, timeout=60, tries=2).content))
    text = z.read(z.namelist()[0]).decode("latin-1")
    rows, header, started = [], None, False
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not started:
            if len(parts) > 2 and parts[0] == "" and all(p for p in parts[1:]):
                header = parts[1:]
                started = True
            continue
        if len(parts) < 2 or not parts[0].isdigit() or len(parts[0]) != 6:
            if rows:
                break
            continue
        rows.append([parts[0]] + [float(p) for p in parts[1:len(header) + 1]])
    df = pd.DataFrame(rows, columns=["ym"] + header).set_index("ym")
    df.index = pd.to_datetime(df.index, format="%Y%m").to_period("M")
    return df.replace([-99.99, -999], np.nan) / 100


def monthly_vars(fred) -> pd.DataFrame:
    """Monthly macro state since 1976 from FRED (fred = callable code -> {date: value})."""
    def m(code):
        s = pd.Series(fred(code), dtype=float)
        s.index = pd.to_datetime(s.index).to_period("M")
        return s.groupby(level=0).mean()
    cpi = m("CPIAUCSL")
    df = pd.DataFrame({"cpi": cpi, "unrate": m("UNRATE"), "fedfunds": m("FEDFUNDS"), "gs10": m("GS10"), "gs2": m("GS2"), "baa": m("BAA10YM")})
    df["cpi_yoy"] = (df["cpi"] / df["cpi"].shift(12) - 1) * 100
    df["cpi_chg6"] = df["cpi_yoy"] - df["cpi_yoy"].shift(6)
    df["unrate_chg6"] = df["unrate"] - df["unrate"].shift(6)
    df["curve"] = df["gs10"] - df["gs2"]
    return df[[k for k, _, _ in VARS]]


def find_analogs(state: pd.DataFrame, now: pd.Period, candidates: pd.PeriodIndex, k: int = 8, gap: int = 9) -> list[tuple]:
    z = (state - state.mean()) / state.std()
    cur = z.loc[now]
    d = np.sqrt(((z.loc[candidates] - cur) ** 2).mean(axis=1)).dropna().sort_values()
    picked = []
    for p, dist in d.items():
        if all(abs((p - q).n) > gap for q, _ in picked):
            picked.append((p, float(dist)))
        if len(picked) >= k:
            break
    return picked


def forward(spx: pd.Series, start: pd.Timestamp, months: int) -> float | None:
    a = spx[spx.index <= start]
    b = spx[spx.index <= start + pd.DateOffset(months=months)]
    if a.empty or b.empty or b.index[-1] <= a.index[-1] or start + pd.DateOffset(months=months) > spx.index[-1]:
        return None
    return float(b.iloc[-1] / a.iloc[-1] - 1)


def max_dd(spx: pd.Series, start: pd.Timestamp, months: int = 12) -> float | None:
    w = spx[(spx.index >= start) & (spx.index <= start + pd.DateOffset(months=months))]
    if len(w) < 20:
        return None
    return float((w / w.cummax() - 1).min())


def run(fred) -> dict:
    state = monthly_vars(fred).loc["1976-06":]
    spx_pts = read_series("spx")
    spx = pd.Series(spx_pts, dtype=float)
    spx.index = pd.to_datetime(spx.index)
    spx = spx.sort_index()
    full = state.dropna()
    now = full.index[-1]
    last_fwd = pd.Period(spx.index[-1], "M") - 12
    # recent months look alike simply because the data moves slowly: search history, not the last two years
    cand = full.index[(full.index >= pd.Period("1990-01", "M")) & (full.index <= min(last_fwd, now - 24))]
    picks = find_analogs(full, now, cand)
    try:
        ind = _ff_table(FF_IND)
        fac = _ff_table(FF_FAC)
        mkt = fac["Mkt-RF"] + fac["RF"]
    except Exception:
        ind, mkt = None, None

    def ind_excess(p: pd.Period, months: int = 12) -> dict:
        if ind is None:
            return {}
        w = ind.loc[(ind.index > p) & (ind.index <= p + months)]
        mw = mkt.loc[(mkt.index > p) & (mkt.index <= p + months)]
        if len(w) < months:
            return {}
        r = (1 + w).prod() - 1
        rm = float((1 + mw).prod() - 1)
        return {c: round(float(r[c] - rm), 4) for c in w.columns if pd.notna(r[c])}

    analogs = []
    for p, dist in picks:
        start = p.to_timestamp(how="end").normalize()
        analogs.append({"month": str(p), "dist": round(dist, 3), "values": {k: round(float(full.at[p, k]), 2) for k, _, _ in VARS},
                        "fwd3": forward(spx, start, 3), "fwd6": forward(spx, start, 6), "fwd12": forward(spx, start, 12),
                        "dd12": max_dd(spx, start), "ind": ind_excess(p)})
    # every month since 1990 with a full year ahead, as the baseline
    base = []
    for p in full.index[(full.index >= pd.Period("1990-01", "M")) & (full.index <= last_fwd)]:
        start = p.to_timestamp(how="end").normalize()
        base.append((forward(spx, start, 12), max_dd(spx, start)))
    b12 = [x for x, _ in base if x is not None]
    bdd = [y for _, y in base if y is not None]

    def stats(xs):
        xs = [x for x in xs if x is not None]
        return {"n": len(xs), "avg": round(float(np.mean(xs)), 4) if xs else None, "med": round(float(np.median(xs)), 4) if xs else None,
                "pos": round(float(np.mean([x > 0 for x in xs])), 3) if xs else None, "min": round(float(min(xs)), 4) if xs else None,
                "max": round(float(max(xs)), 4) if xs else None}
    dds = [a["dd12"] for a in analogs if a["dd12"] is not None]
    sectors = []
    if ind is not None:
        for c in ind.columns:
            xs = [a["ind"][c] for a in analogs if c in a["ind"]]
            if len(xs) >= 3:
                sectors.append({"key": c, "name": IND_HE.get(c, c), "avg": round(float(np.mean(xs)), 4), "hit": round(float(np.mean([x > 0 for x in xs])), 3), "n": len(xs)})
        sectors.sort(key=lambda x: -x["avg"])
    pct = {k: round(float((full[k] < full.at[now, k]).mean() * 100), 0) for k, _, _ in VARS}
    return {"now": str(now), "vars": [{"key": k, "name": n, "unit": u, "now": round(float(full.at[now, k]), 2), "pct": pct[k]} for k, n, u in VARS],
            "analogs": analogs, "fwd3": stats([a["fwd3"] for a in analogs]), "fwd6": stats([a["fwd6"] for a in analogs]),
            "fwd12": stats([a["fwd12"] for a in analogs]),
            "dd": {"med": round(float(np.median(dds)), 4) if dds else None, "p10": round(float(np.mean([d <= -0.10 for d in dds])), 3) if dds else None,
                   "p20": round(float(np.mean([d <= -0.20 for d in dds])), 3) if dds else None, "worst": round(float(min(dds)), 4) if dds else None},
            "base": {"fwd12": stats(b12), "ddMed": round(float(np.median(bdd)), 4) if bdd else None,
                     "p10": round(float(np.mean([d <= -0.10 for d in bdd])), 3) if bdd else None},
            "sectors": sectors, "from": str(cand[0]) if len(cand) else None, "ff": ind is not None}
