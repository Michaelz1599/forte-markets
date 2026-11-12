"""Offline tests of the Buffett indicator math (pipeline/valuation.py) on synthetic inputs."""
import math

import pandas as pd

from pipeline import valuation as V


def _q(y, k):
    return f"{y}-{(k - 1) * 3 + 1:02d}-01"


def _us_inputs():
    gdp = {_q(y, k): 1000.0 for y in range(1969, 2027) for k in range(1, 5)}       # flat GDP of $1,000bn
    z1 = {_q(y, k): 500_000.0 * (1.01 ** ((y - 1969) * 4 + k)) for y in range(1969, 1994) for k in range(1, 5)}  # $m
    w = {f"{y}-{m:02d}-01": 600.0 for y in range(1989, 2013) for m in range(1, 13)}   # Wilshire points, monthly
    return {"us_gdp": gdp, "us_z1": z1, "w5000_m": w}


def test_us_ratio_is_wilshire_over_gdp():
    inp = _us_inputs()
    daily = pd.Series({d.strftime("%Y-%m-%d"): 700.0 for d in pd.bdate_range("2013-01-02", "2014-12-31")})
    out = V.us_series(inp, daily)
    assert out["1999-12-31"] == 60.0                 # 600 points / $1,000bn
    assert out["2014-12-31"] == 70.0                 # daily data: the last close of the month
    assert "2014-12-30" not in out                   # one point a month
    assert min(out) == "1970-01-30"                  # Z.1 splice before Wilshire
    assert all(type(v) is float for v in out.values())   # numpy scalars would be written as "np.float64(...)"


def test_us_splice_rescaled_to_wilshire():
    inp = _us_inputs()
    out = V.us_series(inp, None)
    # over 1989-1993 Wilshire / (Z.1/1000) averages k; before 1989 the Z.1 ratio is multiplied by k
    k = [600.0 / (inp["us_z1"][q] / 1000) for q in inp["us_z1"] if V.SPLICE[0] <= q <= V.SPLICE[1]]
    scale = sum(k) / len(k)
    q4_1988 = inp["us_z1"]["1988-10-01"] / 1000 * scale / 1000 * 100
    assert abs(out["1988-12-30"] - round(q4_1988, 2)) < 0.01
    # between quarter ends the months are log-linear
    a, b = out["1988-09-30"], out["1988-12-30"]
    assert abs(out["1988-10-31"] - math.exp(math.log(a) * 2 / 3 + math.log(b) / 3)) < 0.02


def test_us_uses_latest_gdp_when_quarter_not_out():
    inp = _us_inputs()
    inp["us_gdp"] = {k: v for k, v in inp["us_gdp"].items() if k <= "2014-04-01"}   # Q3 2014 not published
    inp["us_gdp"]["2014-04-01"] = 1250.0
    daily = pd.Series({d.strftime("%Y-%m-%d"): 700.0 for d in pd.bdate_range("2013-01-02", "2014-09-30")})
    out = V.us_series(inp, daily)
    assert out["2014-09-30"] == 56.0 and out["2014-06-30"] == 56.0 and out["2014-03-31"] == 70.0


def _il_inputs():
    gq = {_q(y, k): 250_000.0 for y in range(1990, 2027) for k in range(1, 5)}       # NIS m a quarter -> 1,000,000 a year
    cap = {str(y): 200e9 for y in range(1993, 2025)}                                   # $200bn every year end
    cap["2020"] = 300e9
    fx = {str(y): 4.0 for y in range(1990, 2026)}
    ta = {f"{y}-{m:02d}-01": 1000.0 for y in range(1992, 2013) for m in range(1, 13)}
    return {"il_gdp": gq, "il_cap": cap, "il_fx_ye": fx, "ta125_m": ta}


def test_il_anchors_hit_exactly_and_gap_spread_over_months():
    inp = _il_inputs()
    daily = pd.Series({d.strftime("%Y-%m-%d"): 1000.0 for d in pd.bdate_range("2013-01-02", "2026-06-30")})
    out = V.il_series(inp, daily)
    assert out["2019-12-31"] == 80.0                 # 200bn x 4.0 = NIS 800bn / 1,000bn
    assert out["2020-12-31"] == 120.0                # 300bn x 4.0 = 1,200bn
    assert abs(out["2020-06-30"] - 80.0 * (1.5 ** 0.5)) < 0.01   # flat index: half the log gap by mid-year
    assert out["2021-12-31"] == 80.0
    # after the last published year end (2024) the value moves with the index only
    assert out["2026-06-30"] == 80.0
    assert all(type(v) is float for v in out.values())


def test_il_after_last_anchor_follows_index():
    inp = _il_inputs()
    d = pd.bdate_range("2013-01-02", "2025-12-31")
    daily = pd.Series({x.strftime("%Y-%m-%d"): (1000.0 if x.year < 2025 else 1100.0) for x in d})
    out = V.il_series(inp, daily)
    assert out["2025-12-31"] == 88.0


def test_month_ends_skip_partial_monthly_bar():
    this = V.today_utc().strftime("%Y-%m-01")
    s = V.month_ends(None, {"2020-01-01": 1.0, this: 2.0})
    assert list(s.values) == [1.0]
