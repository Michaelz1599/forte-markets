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


def _snap_set_old(n_days=22, n=600, seed=1):
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


def test_chaikin_money_flow_bounds_and_sign():
    idx = _dates(40)
    h, l, v = pd.Series(11.0, idx), pd.Series(9.0, idx), pd.Series(1e6, idx)
    assert markets.cmf(h, l, pd.Series(11.0, idx), v).iloc[-1] == 1.0
    assert markets.cmf(h, l, pd.Series(9.0, idx), v).iloc[-1] == -1.0
    c = pd.Series(np.where(np.arange(40) % 2, 10.8, 9.6), index=idx)
    s = markets.cmf(h, l, c, v)
    assert len(s) == 21 and (s.abs() <= 1).all()
    bars = {"close": pd.DataFrame({"A": c, "FX": c}), "high": pd.DataFrame({"A": h, "FX": h}), "low": pd.DataFrame({"A": l, "FX": l}),
            "volume": pd.DataFrame({"A": v, "FX": 0.0})}
    p = markets.cmf_payload(bars)
    assert "A" in p and "FX" not in p and p["A"]["date"] == idx[-1]


# --------------------------------------------------------------------------- Israel
from pipeline import israel  # noqa: E402


def test_israel_composite_and_tables():
    idx = _dates(1500)
    rng = np.random.default_rng(2)
    up = pd.Series(np.linspace(0, 10, 1500), index=idx)           # steadily rising component
    ser = {"a": up, "b": -up, "c": pd.Series(rng.normal(size=1500), index=idx)}
    comp = israel.composite(ser, ["a", "b", "c"], {"a": 1, "b": -1, "c": 1}, min_parts=2)
    assert comp.iloc[-1] > 80 and comp.between(0, 100).all()   # a at its high, b at its low (inverted) = greed
    c = pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300))) for s in ("A.TA", "B.TA", "C.TA")}, index=idx[-300:])
    info = {"A.TA": ("א", "banks"), "B.TA": ("ב", "tech"), "C.TA": ("ג", "banks")}
    rows = israel.stock_rows(c, c * 1.01, c * 0.99, info)
    assert {r["sym"] for r in rows} == {"A", "B", "C"} and all(1 <= r["rs"] <= 100 for r in rows)
    secs = {x["key"]: x for x in israel.sector_rows(c, info, {"banks": "בנקים", "tech": "טכנולוגיה"}, None)}
    assert secs["banks"]["n"] == 2 and secs["tech"]["n"] == 1
    cfg = israel.load()
    assert set(cfg["components"]) <= {s["id"] for s in cfg["series"]}
    assert all(d["tab"] == "israel" and not d["pin"] for d in israel.indicator_defs(cfg))



def _snaps61(n=600, seed=3):
    """Snapshots at offsets 0, 5, 21, 26, 126, 131 sessions back, with a known 6-1 return per stock."""
    rng = np.random.default_rng(seed)
    days = _dates(140)
    syms = [f"S{i:03d}" for i in range(n)]
    offs = (0, 5, rs.SKIP, rs.SKIP + 5, rs.LOOK, rs.LOOK + 5)
    lvl = {o: 50 * np.exp(rng.normal(0, 0.3, n)) for o in offs}
    snaps, at = {}, {}
    for o in offs:
        d = days[-1 - o]
        snaps[d] = _snap(syms, lvl[o], cap=lvl[o] * 1e7)
        at[o] = d
    return days, syms, lvl, snaps, at


def test_rs61_ranks_six_minus_one_and_drops_splits():
    days, syms, lvl, snaps, at = _snaps61()
    # S100: 1-for-10 reverse split between t-126 and t-21 (price x10, market value unchanged)
    t1 = at[rs.SKIP]
    snaps[t1].at["S100", "close"] *= 10
    # S101: big share issuance, price and market value move differently but not by a split factor -> kept
    snaps[t1].at["S101", "marketCap"] *= 1.27
    res = rs.compute(snaps, at, None, None)
    out = rs.payload(res)
    rows = {r[0]: dict(zip(out["cols"], r)) for r in out["rows"]}
    assert "S100" not in rows and "S101" in rows
    exp = lvl[rs.SKIP] / lvl[rs.LOOK] - 1
    best = syms[int(np.argmax([e if s not in ("S100",) else -9 for s, e in zip(syms, exp)]))]
    assert rows[best]["rs"] == 100 and abs(rows[best]["ret"] - exp[syms.index(best)] * 100) < 0.01
    assert out["from"] == at[rs.LOOK] and out["to"] == at[rs.SKIP] and out["prevAsof"] == at[5]
    assert all(1 <= r["rs"] <= 100 for r in rows.values()) and any(r["rsPrev"] for r in rows.values())


def test_rs61_yahoo_members_and_validation():
    days, syms, lvl, snaps, at = _snaps61()
    members = {s: (s, "Industrials") for s in syms[:300]}
    members["NEW"] = ("New Co", "Financials")
    yfc = pd.DataFrame({s: [lvl[o][i] if days[-1 - o] in at.values() else np.nan for o in range(140)][::-1] for i, s in enumerate(syms[:300])}, index=days)
    for o, d in at.items():
        yfc.loc[d, syms[:300]] = [lvl[o][i] for i in range(300)]
    yfc["NEW"] = np.nan
    for o, d in at.items():
        yfc.loc[d, "NEW"] = 100.0 * (2.0 if o <= rs.SKIP else 1.0)
    out = rs.payload(rs.compute(snaps, at, members, yfc))
    rows = {r[0]: dict(zip(out["cols"], r)) for r in out["rows"]}
    assert rows["NEW"]["sp"] == 1 and rows["NEW"]["gics"] == "Financials" and abs(rows["NEW"]["ret"] - 100) < 1e-6
    assert out["nYahoo"] == 301 and all(v["match"] == 1.0 for v in out["validation"]["sessions"].values())
    bad = yfc.copy()
    bad.loc[at[0], syms[:300]] *= 1.05
    try:
        rs.compute(snaps, at, members, bad)
    except ValueError as e:
        assert "disagree" in str(e)
    else:
        raise AssertionError("expected a validation error")


def test_rs61_etfs_against_stock_distribution(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DIST_CSV", tmp_path / "dist.csv")
    monkeypatch.setattr(rs, "ETF_CSV", tmp_path / "etf.csv")
    days, syms, lvl, snaps, at = _snaps61()
    res = rs.compute(snaps, at, None, None)
    idx = _dates(300, end=at[0])
    px = pd.DataFrame({"UP": np.geomspace(100, 10000, 300), "DN": np.geomspace(100, 1, 300)}, index=idx)
    out = rs.etf_rs(res, px, {"factors": ["UP", "DN"]})
    it = out["items"]
    assert it["UP"]["rs"] >= 90 and it["DN"]["rs"] <= 10
    assert it["UP"]["peer"]["factors"] == [1, 2] and abs(it["UP"]["ret61"] - (px["UP"].iloc[-22] / px["UP"].iloc[-127] - 1)) < 1e-3


def test_macro_analogs_pick_nearest_months_with_a_gap():
    from pipeline import analogs
    idx = pd.period_range("1990-01", periods=240, freq="M")
    rng = np.random.default_rng(5)
    state = pd.DataFrame(rng.normal(0, 1, (240, 3)), index=idx, columns=list("abc"))
    now = idx[-1]
    for p in (idx[30], idx[31], idx[100]):  # three months that look exactly like today
        state.loc[p] = state.loc[now]
    picks = analogs.find_analogs(state, now, idx[:200], k=4, gap=9)
    months = [p for p, _ in picks]
    assert months[0] in (idx[30], idx[31]) and idx[100] in months[:2]
    assert not (idx[30] in months and idx[31] in months)  # months closer than the gap are one episode
    assert all(abs((a - b).n) > 9 for i, a in enumerate(months) for b in months[i + 1:])


def test_nyiso_onpeak_average():
    from pipeline import macro
    rows = ["Time Stamp,Name,PTID,LBMP ($/MWHr),Marginal Cost Losses ($/MWHr),Marginal Cost Congestion ($/MWHr)"]
    for h in range(24):
        rows.append(f"10/27/2026 {h:02d}:00,N.Y.C.,61761,{100 if 7 <= h <= 22 else 10},0,0")
        rows.append(f"10/27/2026 {h:02d}:00,WEST,61752,5,0,0")
    for h in range(24):  # a Saturday: no on-peak hours
        rows.append(f"10/24/2026 {h:02d}:00,N.Y.C.,61761,50,0,0")
    out = macro._nyiso_frame("\n".join(rows), "N.Y.C.")
    assert out == {"2026-10-27": 100.0}


def test_rs_skips_snapshot_that_repeats_previous_closes(monkeypatch):
    days = _dates(140)
    rng = np.random.default_rng(9)
    syms = [f"S{i:03d}" for i in range(800)]
    frames = {d: _snap(syms, 50 * np.exp(rng.normal(0, 0.02, 800).cumsum() * 0 + rng.normal(0, 0.05, 800))) for d in days}
    stale_d = days[-1 - (rs.SKIP + 5)]
    frames[stale_d] = frames[days[days.index(stale_d) - 1]].copy()   # the OHLC block of the day before
    have = {d: ["c-" + d] for d in days}
    monkeypatch.setattr(rs, "snapshot_sessions", lambda repo, td: have)
    monkeypatch.setattr(rs, "load_snapshot", lambda repo, h: frames[h[2:]])
    assert rs.same_closes(frames[stale_d], frames[days[days.index(stale_d) - 1]]) == 1.0
    snaps, at = rs.read_snapshots(None, days, (0, 5, rs.SKIP, rs.SKIP + 5, rs.LOOK, rs.LOOK + 5))
    assert at[rs.SKIP + 5] == days[days.index(stale_d) - 1] and at[0] == days[-1] and at[rs.SKIP] == days[-1 - rs.SKIP]
    assert stale_d not in snaps


def test_cpi_drivers_sum_to_headline_when_parts_move_alike():
    from pipeline import drivers
    idx = pd.date_range("2014-01-01", "2026-09-01", freq="MS")
    lvl = {c: 100 * 1.003 ** np.arange(len(idx)) for c in ["CUSR0000SAH1", "CUSR0000SACL1E", "CPIUFDSL", "CPIENGSL", "CUSR0000SASLE", "CPIAUCSL"]}
    fred = lambda code: {d.strftime("%Y-%m-%d"): float(v) for d, v in zip(idx, lvl[code])}
    us = drivers.us(fred)
    k = len(us["d"]) - 1
    total = sum(p["v"][k] for p in us["parts"])
    assert abs(total - us["headline"][k]) < 0.05 and len(us["parts"]) == 5
    cbs = lambda code: ({d.strftime("%Y-%m-%d"): 3.0 for d in idx}, {})
    il = drivers.il(cbs)
    k = len(il["d"]) - 1
    assert abs(sum(p["v"][k] for p in il["parts"]) - 3.0) < 0.01 and il["headline"][k] == 3.0


def test_earnings_live_numbers(tmp_path, monkeypatch):
    import json as _j
    from pipeline import earnings, markets
    cal = tmp_path / "calendar"; (cal / "weeks").mkdir(parents=True); (cal / "market").mkdir()
    days = _dates(40)
    today = days[-1]
    evs = [{"id": "AAA-1", "ticker": "AAA", "market": "US", "date": days[-3], "session": "AMC", "consensus": {"eps": 1.0}},
           {"id": "BBB-1", "ticker": "BBB", "market": "US", "date": today, "session": "BMO"}]
    (cal / "weeks" / "w.json").write_text(_j.dumps({"events": evs}))
    (cal / "market" / "m.json").write_text(_j.dumps({"quotes": {"AAA": {"mcap": 5e9}, "BBB": {"mcap": 9e9}}}))
    (cal / "manifest.json").write_text(_j.dumps({"weeks": [{"file": "data/weeks/w.json"}], "market": "data/market/m.json"}))
    monkeypatch.setattr(earnings, "CAL", cal); monkeypatch.setattr(earnings, "LIVE", cal / "live.json")
    monkeypatch.setattr(earnings, "today_utc", lambda: __import__("datetime").date.fromisoformat(today))
    monkeypatch.setattr(earnings, "implied_move", lambda sym, react: {"move": 0.05, "spot": 10.0, "exp": react, "dte": 1, "iv": 0.6, "at": today + "T08:00+00:00"})
    monkeypatch.setattr(earnings, "eps_actual", lambda sym, d: (1.2, 1.0))
    px = pd.DataFrame({"^GSPC": np.linspace(100, 101, 40)}, index=days)
    closes = pd.DataFrame({"AAA": [10.0] * 38 + [11.0, 11.0]}, index=days)
    monkeypatch.setattr(markets, "yf_close", lambda syms, start: closes)
    out, msg = earnings.run(px)
    r = out["results"]["AAA-1"]
    assert r["d1"] == days[-2] and abs(r["move"] - 0.1) < 1e-9 and r["surprise"] == 0.2
    assert "עלתה 10.0%" in r["he"] and "מעל הצפי" in r["he"]
    assert "BBB-1" in out["implied"] and "BBB-1" not in out["results"]
