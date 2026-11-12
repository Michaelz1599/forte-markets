"""Offline tests of the TA-125 buying/selling pressure estimate (israel.money_flows), short and long windows."""
import datetime as dt

import numpy as np
import pandas as pd

from pipeline import israel


def _bars(n=360, k=50, seed=3, late=None):   # the index total needs 40+ stocks a day
    rng = np.random.default_rng(seed)
    idx = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-11-12", periods=n)]
    syms = [f"S{i}.TA" for i in range(k)]
    c = pd.DataFrame(1000 * np.exp(np.cumsum(rng.normal(0, .015, (n, k)), axis=0)), index=idx, columns=syms)
    h, lo = c * (1 + rng.uniform(0, .02, c.shape)), c * (1 - rng.uniform(0, .02, c.shape))
    v = pd.DataFrame(rng.uniform(1e5, 1e6, c.shape), index=idx, columns=syms)
    if late:
        for df in (c, h, lo, v):
            df.loc[df.index[:-late], syms[0]] = np.nan
    info = {s: (s, "a" if i % 2 else "b") for i, s in enumerate(syms)}
    return c, h, lo, v, info


def _flow(c, h, lo, v):
    turn = c / 100 * v
    clv = (((c - lo) - (h - c)) / (h - lo)).clip(-1, 1).fillna(0)
    w = 0.5 * clv + 0.5 * np.sign(c.diff()).fillna(0)
    return (w * turn).where(turn > 0), turn


def test_windows_match_a_direct_sum():
    c, h, lo, v, info = _bars()
    F = israel.money_flows(c, h, lo, v, info, {"a": "A", "b": "B"})
    flow, turn = _flow(c, h, lo, v)
    s = "S3.TA"
    row = next(r for r in F["stocks"] if r["sym"] == "S3")
    cut = (dt.date(2026, 11, 12) - dt.timedelta(days=365)).isoformat()
    yr = flow.index > cut
    assert abs(row["n20"] - flow[s].iloc[-20:].sum() / 1e6) < 0.01
    assert abs(row["n1y"] - flow[s][yr].sum() / 1e6) < 0.01
    assert abs(row["r1y"] - flow[s][yr].sum() / turn[s][yr].sum()) < 0.001
    assert F["from"]["1y"] > cut and F["from"]["5"] == c.index[-5]
    # the index total is the sum of the stocks, in every window
    for k in ("5", "20", "3m", "1y"):
        assert abs(F["total"]["n" + k] - sum(r["n" + k] for r in F["stocks"])) < 0.5
        assert F["total"]["r" + k] is not None


def test_sectors_months_and_weeks():
    c, h, lo, v, info = _bars()
    F = israel.money_flows(c, h, lo, v, info, {"a": "A", "b": "B"})
    assert {x["key"] for x in F["sectors"]} == {"a", "b"}
    assert abs(sum(x["n3m"] for x in F["sectors"]) - F["total"]["n3m"]) < 0.5
    M = F["months"]
    assert len(M["m"]) == 13 and M["m"][-1] == "2026-11" and len(M["net"]) == 13
    assert all(len(x["r"]) == 13 and len(x["n"]) == 13 for x in M["secs"])
    assert len(F["weeks"]["d"]) == len(F["weeks"]["net"]) <= 14 and F["weeks"]["d"][-1] == "2026-11-12"


def test_stock_listed_inside_the_window_is_flagged():
    c, h, lo, v, info = _bars(late=40)
    F = israel.money_flows(c, h, lo, v, info, {"a": "A", "b": "B"})
    row = next(r for r in F["stocks"] if r["sym"] == "S0")
    assert row["from1y"] == row["from3m"] == c.index[-40]
    assert all("from1y" not in r for r in F["stocks"] if r["sym"] != "S0")
