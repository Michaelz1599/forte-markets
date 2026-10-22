"""Offline tests on synthetic data: indicators math, rotation, breadth, site build."""
import datetime as dt
import json

import numpy as np
import pandas as pd

from pipeline import breadth, markets


def _dates(n, end="2026-10-20"):
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=end, periods=n)]


def test_metrics_basic():
    idx = _dates(400)
    s = pd.Series(np.linspace(100, 200, 400), index=idx)
    m = markets.metrics(s)
    assert m["last"] == 200 and m["trend"] == "up"
    assert abs(m["m1"] - (200 / s.iloc[-22] - 1)) < 1e-4
    assert m["dd52"] == 0 and m["pos52"] == 100
    assert m["rsi"] > 95  # only up days
    assert m["ma200"] > 0 and m["ma50"] > 0


def test_metrics_downtrend_and_rsi_bounds():
    idx = _dates(400)
    s = pd.Series(np.linspace(200, 100, 400), index=idx)
    m = markets.metrics(s)
    assert m["trend"] == "down" and m["rsi"] < 5 and m["dd52"] < 0


def test_relative_and_rotation():
    idx = _dates(400)
    b = pd.Series(np.linspace(100, 110, 400), index=idx)
    a = b * np.linspace(1, 1.2, 400)  # steadily beats the benchmark
    r = markets.relative(a, b)
    assert r["ex"]["y1"] > 0 and r["score"] > 0 and r["rsUp"] is True
    x, y, d = r["rrg"][-1]
    assert x > 100 and d == idx[-1]
    assert len(r["rrg"]) == 6


def test_breadth_counts():
    idx = _dates(300)
    rng = np.random.default_rng(1)
    up = pd.DataFrame({f"U{i}": np.linspace(10, 20, 300) for i in range(60)}, index=idx)
    dn = pd.DataFrame({f"D{i}": np.linspace(20, 10, 300) for i in range(40)}, index=idx)
    close = pd.concat([up, dn], axis=1) * (1 + rng.normal(0, 1e-9, (300, 100)))
    out = breadth.compute(close)
    last = idx[-1]
    assert abs(out["sp_pct200"][last] - 60) < 1e-6
    assert abs(out["sp_pct50"][last] - 60) < 1e-6
    assert abs(out["sp_adr10"][last] - 1.5) < 1e-6
    assert abs(out["sp_hl"][last] - 20) < 1e-6  # 60% at highs, 40% at lows


def test_ratio_and_yield_guard():
    idx = _dates(10)
    px = pd.DataFrame({"A": np.arange(1, 11, dtype=float), "B": np.full(10, 2.0)}, index=idx)
    r = markets.ratio_series(px, "A", "B")
    assert r[idx[-1]] == 5.0 and len(r) == 10


def test_stock_momentum_and_mom_breadth():
    idx = _dates(320)
    up = pd.DataFrame({f"U{i}": np.linspace(10, 20, 320) for i in range(30)}, index=idx)
    dn = pd.DataFrame({f"D{i}": np.linspace(20, 10, 320) for i in range(20)}, index=idx)
    close = pd.concat([up, dn], axis=1)
    out = breadth.compute(close)
    assert abs(out["sp_mom12"][idx[-1]] - 60) < 1e-6
    info = {s: (s, "Information Technology" if s.startswith("U") else "Energy") for s in close.columns}
    m = breadth.stock_momentum(close, info)
    assert m["n"] == 50 and m["pctPos"] == 60.0
    assert m["leaders"][0]["sym"].startswith("U") and m["laggards"][0]["sym"].startswith("D")
    assert m["sectors"][0]["sector"] == "טכנולוגיה" and m["sectors"][0]["inTop50"] == 30


# --------------------------------------------------------------------------- RS
from pipeline import rs  # noqa: E402


def _snap(syms, close, high=None, low=None, price=None, cap=1e9, names=None, ind="Technology"):
    high = close * 1.01 if high is None else high
    low = close * 0.99 if low is None else low
    return pd.DataFrame({"name": names or [f"{s} Inc. Common Stock" for s in syms], "price": close if price is None else price,
                         "open": close, "high": high, "low": low, "close": close, "marketCap": cap, "volume": 1000,
                         "industry": ind}, index=pd.Index(syms, name="symbol"))


def test_rs_window_math_matches_hand_calculation():
    days = _dates(11)
    c = pd.DataFrame({"A": [10, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17.0]}, index=days)
    h = c + 0.5
    lo = c - 0.5
    w = rs.window_stats(c, h, lo, 10)
    trs = []
    for i in range(1, 11):
        hi_, lo_, pc = h["A"].iloc[i], lo["A"].iloc[i], c["A"].iloc[i - 1]
        trs.append(max(hi_ - lo_, abs(hi_ - pc), abs(lo_ - pc)))
    assert abs(w.at["A", "raw"] - (17 - 10) / np.mean(trs)) < 1e-9
    assert abs(w.at["A", "ret"] - 0.7) < 1e-9


def test_rs_percentiles_and_against_distribution():
    raw = pd.Series(np.arange(1, 201, dtype=float), index=[f"S{i}" for i in range(200)])
    r = rs.rank_rs(raw)
    assert r.max() == 100 and r.min() == 1 and r["S99"] == 50
    dist = raw.to_numpy()
    assert rs.rs_against(1e9, dist) == 100 and rs.rs_against(-1e9, dist) == 1 and rs.rs_against(100.0, dist) == 50
    q = np.quantile(dist, np.linspace(0, 1, 101))
    assert abs(rs.rs_from_quantiles(100.0, q) - 50) <= 1


def test_security_kind_and_names():
    k = rs.security_kind
    assert k("NVIDIA Corporation Common Stock") == "stock"
    assert k("Sea Limited American Depositary Shares each representing one Class A Ordinary Share") == "stock"
    assert k("MPLX LP Common Units Representing Limited Partner Interests") == "stock"
    assert k("Cheniere Energy Partners LP Common Units") == "stock"
    assert k("AllianceBernstein Holding L.P.  Units") == "stock"
    assert k("PPL Corporation Corporate Units") == "unit"
    assert k("Digital Realty Trust Inc. Common Stock") == "stock"
    assert k("Northern Trust Corporation Common Stock") == "stock"
    assert k("Rigetti Computing Inc. Warrants") == "warrant"
    assert k("Huntington Bancshares Incorporated Depositary Shares Each Representing a 1/40th Interest") == "pref"
    assert k("AT&T Inc. 5.350% Global Notes due 2066") == "debt"
    assert k("PIMCO Dynamic Income Fund Common Stock") == "fund"
    assert k("BlackRock Science and Technology Trust Common Shares of Beneficial Interest") == "fund"
    assert k("Churchill Capital Corp XII Class A Ordinary Shares") == "spac"
    assert k("Patriot Acquisition Corp. Units") in ("unit", "spac")
    assert rs.clean_name("NVIDIA Corporation Common Stock") == "NVIDIA"
    assert rs.clean_name("Alphabet Inc. Class A Common Stock") == "Alphabet"
    assert rs.clean_name("Coca-Cola Company (The) Common Stock") == "Coca-Cola"
    assert rs.disp("BRK/B") == "BRK.B" and rs.disp("BF-B") == "BF.B"


def test_rs_session_mapping():
    days = ["2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20"]
    utc = dt.timezone.utc
    assert rs.session_of(dt.datetime(2026, 10, 19, 8, 3, tzinfo=utc), days) == "2026-10-16"   # Monday morning -> Friday
    assert rs.session_of(dt.datetime(2026, 10, 20, 7, 54, tzinfo=utc), days) == "2026-10-19"
    assert rs.session_of(dt.datetime(2026, 10, 19, 22, 0, tzinfo=utc), days) == "2026-10-19"  # after the close -> same day
    assert rs.session_of(dt.datetime(2026, 10, 19, 15, 0, tzinfo=utc), days) is None          # during the session


def _snap_set(n_days=22, n=600, seed=1):
    rng = np.random.default_rng(seed)
    days = _dates(n_days)
    syms = [f"S{i:03d}" for i in range(n)]
    drift = rng.normal(0, 0.01, n)
    paths = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_days, n)) + drift, axis=0))
    snaps = {}
    for i, d in enumerate(days):
        price = paths[i - 1] if i else paths[i]          # NASDAQ's last sale = the previous session's close
        snaps[d] = _snap(syms, paths[i], paths[i] * 1.012, paths[i] * 0.988, price=price)
    return days, syms, paths, snaps


def test_rs_compute_end_to_end_with_yahoo_override_and_corporate_actions():
    days, syms, paths, snaps = _snap_set()
    # a 1:10 reverse split on S105 halfway through the window: Yahoo close jumps 10x, NASDAQ price shows it a day later
    k = len(days) - 5
    for d in days[k:]:
        for f in ("close", "high", "low", "open"):
            snaps[d].at["S105", f] *= 10
    snaps[days[k + 1]].at["S105", "price"] *= 10
    # a flat, illiquid name
    for d in days:
        for f in ("close", "high", "low", "open", "price"):
            snaps[d].at["S106", f] = 5.0
    # S&P 500 members: S000..S049 via Yahoo, plus a member NASDAQ's list leaves out (XYZ)
    members = {s: (f"Name {s}", "Information Technology") for s in syms[:50]}
    members["XYZ"] = ("Xyz Corp", "Financials")
    yc = pd.DataFrame(paths[:, :50], index=days, columns=syms[:50])
    yc["XYZ"] = np.linspace(100, 130, len(days))
    yf = {"close": yc, "high": yc * 1.01, "low": yc * 0.99}
    spx = pd.Series(np.linspace(6000, 6100, len(days)), index=days)
    res = rs.compute(snaps, days, members, yf, spx)
    out = rs.payload(res)
    cols = out["cols"]
    rows = {r[0]: dict(zip(cols, r)) for r in out["rows"]}
    assert "S105" not in rows and "S106" not in rows
    assert any(x["sym"] == "S105" for x in out["corporateActions"])
    assert out["excludedFlat"] >= 1
    assert "XYZ" in rows and rows["XYZ"]["sp"] == 1 and rows["XYZ"]["gics"] == "Financials" and rows["XYZ"]["sec"] == "Finance"
    assert rows["XYZ"]["rs"] >= 95          # a steady 30% climb beats random walks
    assert out["nSp"] == 51 and out["nYahoo"] == 51
    assert all(1 <= r["rs"] <= 100 for r in rows.values())
    assert out["prevAsof"] == days[-1 - rs.PREV] and out["from"] == days[-1 - rs.N]
    assert all(v["match"] == 1.0 for v in out["validation"]["sessions"].values())
    assert {x["sector"] for x in out["sectors"]["gics"]} == {"Information Technology", "Financials"}
    assert sum(x["n"] for x in out["sectors"]["nas"]) == len(rows)
    # the ETF side ranks against the same distribution
    assert res["_dists"] and len(res["_dist_now"]) == len(rows)


def test_rs_refuses_snapshots_that_disagree_with_yahoo():
    days, syms, paths, snaps = _snap_set()
    members = {s: (s, "Industrials") for s in syms[:300]}
    yc = pd.DataFrame(paths[:, :300], index=days, columns=syms[:300])
    yc.iloc[-1] *= 1.05                   # e.g. a snapshot mapped to the wrong session
    yf = {"close": yc, "high": yc * 1.01, "low": yc * 0.99}
    try:
        rs.compute(snaps, days, members, yf, None)
    except ValueError as e:
        assert "disagree" in str(e)
    else:
        raise AssertionError("expected a validation error")


def test_rs_etf_against_stock_distribution(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DIST_CSV", tmp_path / "dist.csv")
    monkeypatch.setattr(rs, "ETF_CSV", tmp_path / "etf.csv")
    days, syms, paths, snaps = _snap_set()
    res = rs.compute(snaps, days, None, None, None)
    up = pd.Series(np.linspace(100, 140, len(days)), index=days)
    dn = pd.Series(np.linspace(100, 70, len(days)), index=days)
    close = pd.DataFrame({"UP": up, "DN": dn})
    out = rs.etf_rs(res, {"close": close, "high": close * 1.005, "low": close * 0.995}, {"factors": ["UP", "DN"]})
    it = out["items"]
    assert it["UP"]["rs"] == 100 and it["DN"]["rs"] == 1
    assert it["UP"]["peer"]["factors"] == [1, 2] and it["DN"]["peer"]["factors"] == [2, 2]
    assert it["UP"]["rsPrev"] == 100 and len(it["UP"]["rsHist"]) >= 2
    assert (tmp_path / "etf.csv").exists() and (tmp_path / "dist.csv").exists()


def test_rs_drops_bad_snapshots_outside_the_window():
    days, syms, paths, snaps = _snap_set()
    members = {s: (s, "Industrials") for s in syms[:300]}
    yc = pd.DataFrame(paths[:, :300], index=days, columns=syms[:300])
    yc.iloc[1] *= 1.05                    # an old session, outside both windows
    yf = {"close": yc, "high": yc * 1.01, "low": yc * 0.99}
    out = rs.payload(rs.compute(snaps, days, members, yf, None))
    assert out["validation"]["dropped"] == [days[1]] and days[1] not in out["validation"]["sessions"]


# --------------------------------------------------------------------------- macro
from pipeline import macro  # noqa: E402


def test_macro_transforms_and_spark():
    idx = pd.date_range("2018-01-01", "2026-09-01", freq="MS").strftime("%Y-%m-%d")
    lvl = {d: 100 * 1.03 ** (i / 12) for i, d in enumerate(idx)}
    yoy = macro._transform(lvl, {"freq": "m", "tf": "yoy"})
    assert abs(yoy["2026-09-01"] - 3.0) < 1e-6 and "2018-06-01" not in yoy
    diff = macro._transform({"2026-08-01": 100.0, "2026-09-01": 103.0}, {"freq": "m", "tf": "diff"})
    assert diff == {"2026-09-01": 3.0}
    bp = macro._transform({"2026-10-01": 3.29}, {"freq": "d", "scale": 100})
    assert abs(bp["2026-10-01"] - 329) < 1e-9
    sp = macro.spark({"2026-10-05": 60.0, "2026-10-20": 40.0}, {"2026-10-02": 3.0})
    assert sp == {"2026-10-05": 60.0 - 7 * 3.0}          # gas older than 4 days is not used


def test_macro_definitions_are_consistent():
    cfg = macro.load()
    secs = {s["id"] for s in cfg["sections"]}
    ids = [s["id"] for s in cfg["series"]]
    assert len(ids) == len(set(ids)) and all(s["sec"] in secs for s in cfg["series"])
    defs = macro.indicator_defs(cfg)
    assert all(d["tab"] == "macro" and not d["pin"] and not d["comp"] and d["pol"] == 0 for d in defs)
    inds = json.loads((macro.ROOT / "config" / "indicators.json").read_text(encoding="utf-8"))
    assert not {d["id"] for d in defs} & {i["id"] for i in inds}
    assert not any(i["group"] == "pos" for i in inds)
    assert any(i["id"] == "sp_mcsi" and i["comp"] for i in inds) and not any(i["id"] == "mcsi" and i["comp"] for i in inds)
