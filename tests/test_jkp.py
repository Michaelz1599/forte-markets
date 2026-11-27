"""Israeli factors (JKP): the statistics and the payload of data/jkp_il.json, on synthetic returns."""
import io
import math
import zipfile

import numpy as np
import pandas as pd

from pipeline import jkp

CFG = {"country": "isr", "weighting": "vw_cap", "base": "https://example.org/public/", "page": "https://example.org",
       "themes": [{"id": "value", "name": "ערך", "desc": "", "en": "Value"}, {"id": "momentum", "name": "מומנטום", "desc": "", "en": "Momentum"}],
       "factors": {"be_me": {"label": "Book-to-market equity", "theme": "value"}, "sale_me": {"label": "Sales-to-market", "theme": "value"},
                   "ret_12_1": {"label": "Price momentum t-12 to t-1", "theme": "momentum"}}}


def months(n, start="2001-01"):
    return [p.strftime("%Y-%m") for p in pd.period_range(start, periods=n, freq="M")]


def frames(n=240, seed=1):
    rng = np.random.default_rng(seed)
    ms = months(n)
    mkt = rng.normal(0.008, 0.05, n)
    fac = {"be_me": 0.004 + 0.3 * mkt + rng.normal(0, 0.03, n), "sale_me": 0.002 + rng.normal(0, 0.03, n),
           "ret_12_1": 0.01 - 0.2 * mkt + rng.normal(0, 0.04, n)}
    f = pd.DataFrame([{"location": "isr", "name": k, "direction": 1, "n_stocks": 300, "date": m, "ret": v[i]}
                      for k, v in fac.items() for i, m in enumerate(ms)])
    m = pd.DataFrame({"location": "isr", "name": "mkt", "n_stocks": 500, "date": ms, "ret": mkt})
    return f, m, fac, mkt


def test_period_stats_match_definitions():
    f, m, fac, mkt = frames()
    cal = pd.Index(months(240))
    r = pd.Series(fac["be_me"], index=cal)
    mm = pd.Series(mkt, index=cal)
    st = dict(zip(jkp.STAT_KEYS, jkp.period_stats(r, mm, 60)))
    x, y = fac["be_me"][-60:], mkt[-60:]
    assert math.isclose(st["ret"], round(x.mean() * 12, 4), abs_tol=1e-4)
    assert math.isclose(st["vol"], round(x.std(ddof=1) * math.sqrt(12), 4), abs_tol=1e-4)
    beta = np.cov(x, y, ddof=1)[0, 1] / y.var(ddof=1)
    assert math.isclose(st["beta"], round(beta, 3), abs_tol=1e-3)
    assert math.isclose(st["alpha"], round((x.mean() - beta * y.mean()) * 12, 4), abs_tol=1e-4)
    assert math.isclose(st["cum"], round(float(np.prod(1 + x) - 1), 4), abs_tol=1e-4)
    assert st["n"] == 60
    # too few months in the window: no statistics
    assert jkp.period_stats(r.iloc[:100].reindex(cal), mm, 60) is None


def test_build_themes_from_factors_and_payload():
    f, m, fac, mkt = frames()
    out = jkp.build(f, None, m, CFG, {"modified": "2026-08-04T05:26:05Z"})
    assert out["asof"] == months(240)[-1] and len(out["months"]) == 240
    ids = [t["id"] for t in out["themes"]]
    assert ids == ["value", "momentum"]
    # a theme = the equal-weighted average of its factors
    v = out["series"]["value"]
    assert math.isclose(v[-1], round((fac["be_me"][-1] + fac["sale_me"][-1]) / 2, 5), abs_tol=1e-5)
    assert {x["id"] for x in out["factors"]} == {"be_me", "sale_me", "ret_12_1"}
    assert all(set(t["st"]) == {"y1", "y3", "y5", "y10", "all"} for t in out["themes"])
    # the market against itself: no alpha, beta or information ratio
    assert out["mkt"]["st"]["y5"][3] is None and out["mkt"]["st"]["y5"][4] is None
    th = pd.DataFrame([{"location": "isr", "name": "value", "n_factors": 2, "date": mo, "ret": (fac["be_me"][i] + fac["sale_me"][i]) / 2}
                       for i, mo in enumerate(months(240))])
    out2 = jkp.build(f, th, m, CFG, {})
    assert out2["themes"][0]["chk"] is not None and out2["themes"][0]["chk"] < 1e-9


def test_read_zip_csv():
    f, _, _, _ = frames(24)
    csv = f.assign(date=pd.PeriodIndex(f["date"], freq="M").to_timestamp(how="end").strftime("%Y-%m-%d")).to_csv(index=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[isr]_[all_factors]_[monthly]_[vw_cap].csv", csv.replace("300", "na", 1))
    df = jkp.read_zip_csv(buf.getvalue())
    assert df["date"].iloc[0] == "2001-01" and len(df) == len(f)


def test_url():
    assert jkp.url(CFG, "all_factors") == "https://example.org/public/%5Bisr%5D_%5Ball_factors%5D_%5Bmonthly%5D_%5Bvw_cap%5D.zip"
