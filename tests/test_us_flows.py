"""Offline tests of "where money flows in the US": the SSGA NAV-history parser, split-adjusted ETF flows, the payload
windows, and the S&P 500 pressure estimate (usflows.pressure, the Israel method in dollars)."""
import io

import numpy as np
import openpyxl
import pandas as pd

from pipeline import usflows


def _navhist(days, nav, so, disclaimer=True) -> bytes:
    """A workbook laid out like SSGA's: fund name, ticker, blank, header, rows newest first, then disclaimer text."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Fund Name:", "Test Select Sector SPDR ETF"])
    ws.append(["Ticker Symbol:", "XLT"])
    ws.append([])
    ws.append(["Date", "NAV", "Shares Outstanding", "Total Net Assets"])
    for d, n, s in sorted(zip(days, nav, so), reverse=True):
        ws.append([pd.Timestamp(d).strftime("%d-%b-%Y"), n, s, n * s])
    if disclaimer:
        ws.append([])
        ws.append(["Past performance is not a reliable indicator of future performance."])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _fund(n=300, seed=1, split_at=None):
    rng = np.random.default_rng(seed)
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-11-24", periods=n)]
    nav = 100 * np.exp(np.cumsum(rng.normal(0, .01, n)))
    units = rng.integers(-20, 21, n) * 50_000       # creation units of 50,000 shares
    units[0] = 0
    so = 200_000_000 + np.cumsum(units)
    so = so.astype(float)
    if split_at:
        nav[split_at:] /= 2
        so[split_at:] *= 2
    return days, nav, so, units


def test_parse_newest_first_with_disclaimer():
    days, nav, so, _ = _fund()
    df = usflows.parse_navhist(_navhist(days, nav, so))
    assert list(df.index) == days and abs(df["nav"].iloc[-1] - nav[-1]) < 1e-9 and df["so"].iloc[0] == so[0]
    # early stop: only the newest rows, still oldest first
    short = usflows.parse_navhist(_navhist(days, nav, so), keep=40)
    assert len(short) == 40 and list(short.index) == days[-40:]


def test_flows_are_units_times_nav_and_ignore_a_split():
    days, nav, so, units = _fund(split_at=200)
    df = usflows.parse_navhist(_navhist(days, nav, so))
    f = usflows.daily_flows(df)
    # every day but the split: the change in shares x NAV; on the split day the new units at the post-split count
    exp = pd.Series(units[1:] * 1.0, index=days[1:])
    exp.iloc[199:] *= 2       # after the split each creation unit is twice as many (half-price) shares
    assert np.allclose(f.values, exp.values * df["nav"].iloc[1:].values)
    assert abs(f.iloc[199]) <= 20 * 50_000 * 2 * df["nav"].iloc[200] + 1   # the split day: no 10-million-share "inflow"


def test_payload_windows_and_shares():
    cfg = {"groups": {"market": "השוק", "sector": "סקטור"},
           "etfs": [["SPY", "market", "S&P 500", None], ["XLK", "sector", "טכנולוגיה", "Information Technology"],
                    ["XLF", "sector", "פיננסים", "Financials"]]}
    frames, flows = {}, {}
    for i, t in enumerate(("SPY", "XLK", "XLF")):
        days, nav, so, _ = _fund(seed=i + 3)
        frames[t] = usflows.parse_navhist(_navhist(days, nav, so))
        flows[t] = usflows.daily_flows(frames[t])
    P = usflows.payload(frames, cfg)
    assert P["asof"] == "2026-11-24" and [r["sym"] for r in P["etfs"]] == ["SPY", "XLK", "XLF"]
    xlk = P["etfs"][1]
    assert abs(xlk["f20"] - flows["XLK"].iloc[-20:].sum() / 1e6) < 0.06
    assert abs(xlk["f1"] - flows["XLK"].iloc[-1] / 1e6) < 0.06
    base = frames["XLK"]["tna"].iloc[-21]
    assert abs(xlk["p20"] - flows["XLK"].iloc[-20:].sum() / base) < 1e-4 and abs(xlk["b20"] - base / 1e6) < 1
    # the daily sector total is XLK + XLF; SPY separately
    assert abs(P["hist"]["sec"][-1] - (flows["XLK"].iloc[-1] + flows["XLF"].iloc[-1]) / 1e6) < 0.06
    assert abs(P["hist"]["spy"][-1] - flows["SPY"].iloc[-1] / 1e6) < 0.06
    M = P["months"]
    assert len(M["m"]) == 13 and M["m"][-1] == "2026-11"
    nov = flows["XLK"][[d.startswith("2026-11") for d in flows["XLK"].index]].sum() / 1e6
    assert abs(M["etf"]["XLK"]["n"][-1] - nov) < 0.06


def test_pressure_in_dollars_by_gics_sector():
    rng = np.random.default_rng(5)
    n, k = 360, 60
    idx = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-11-25", periods=n)]
    syms = [f"S{i}" for i in range(k)]
    c = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, .015, (n, k)), axis=0)), index=idx, columns=syms)
    bars = {"close": c, "high": c * (1 + rng.uniform(0, .02, c.shape)), "low": c * (1 - rng.uniform(0, .02, c.shape)),
            "volume": pd.DataFrame(rng.uniform(1e6, 1e7, c.shape), index=idx, columns=syms)}
    info = {s: (f"Co {s}", "Information Technology" if i % 2 else "Energy") for i, s in enumerate(syms)}
    F = usflows.pressure(c, bars, info)
    assert F["unit"] == "מיליוני דולר" and F["sectorNames"] == {"Energy": "אנרגיה", "Information Technology": "טכנולוגיה"}
    turn = c.iloc[-340:] * bars["volume"].iloc[-340:]       # dollars, no agorot division
    assert abs(F["total"]["turn20"] - turn.sum(axis=1).iloc[-20:].mean() / 1e6) < 0.1
    assert {x["key"] for x in F["sectors"]} == {"Energy", "Information Technology"} and len(F["stocks"]) == k
