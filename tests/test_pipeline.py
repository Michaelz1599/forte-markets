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
