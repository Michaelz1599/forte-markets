"""tools/expo/build.py: the issuer-file parsers, ticker mapping, price statistics and factor percentiles."""
import importlib.util
import io
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("expo_build", Path(__file__).resolve().parents[1] / "tools" / "expo" / "build.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


def test_parse_ssga():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in [["Fund Name:", "SPDR S&P 500 ETF Trust"], ["Ticker Symbol:", "SPY"], ["Holdings:", "As of 18-Nov-2026"], [],
              ["Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency"],
              ["APPLE INC", "AAPL", "037833100", "2046251", 7.5, "-", 1, "USD"],
              ["BERKSHIRE HATHAWAY INC CL B", "BRK.B", "084670702", "2073390", 1.5, "Financials", 1, "USD"],
              ["US DOLLAR", "CASH_USD", "-", "-", 0.1, "-", 1, "USD"]]:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    res = B.parse_ssga(buf.getvalue())
    assert res["asof"] == "2026-11-18"
    assert set(res["h"]) == {"AAPL", "BRK-B"}
    assert abs(sum(res["h"].values()) - 1) < 1e-6
    assert res["meta"]["AAPL"] == {"name": "APPLE INC", "s": None, "cu": "037833100"}   # SSGA leaves Sector as "-"
    assert res["meta"]["BRK-B"]["s"] == "F"


def test_canon_keys():
    m = B.canon_keys({"NVDA": 0.95, "BRKB": 0.05}, {"NVDA", "BRK-B"})
    assert set(m) == {"NVDA", "BRK-B"} and m["BRK-B"] == 0.05


def test_parse_invesco():
    csv = ("Fund Ticker,Security Identifier,Holding Ticker,Shares/Par Value,MarketValue,Weight,Name,Class of Shares,Sector,Date\n"
           "QQQ,037833100,AAPL ,1,1,8.8,Apple Inc,Common Stock,Information Technology,11/18/2026\n"
           "QQQ,02079K305,GOOGL,1,1,2.2,Alphabet Inc,Common Stock,Communication Services,11/18/2026\n")
    res = B.parse_invesco(csv)
    assert res["asof"] == "2026-11-18" and res["h"]["AAPL"] == 0.8


def test_parse_date():
    assert B.parse_date("As of 18-Nov-2026") == "2026-11-18"
    assert B.parse_date("Nov 18, 2026") == "2026-11-18"
    assert B.parse_date("11/18/2026") == "2026-11-18"


def test_price_stats():
    idx = pd.bdate_range("2024-11-01", "2026-11-18")
    rng = np.random.default_rng(1)
    b = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
    x = 50 * (b / 100) ** 2          # twice the log moves of the bench: beta ~2 on weekly returns
    st = B.price_stats(pd.DataFrame({"SPY": b, "X": x}, index=idx))
    assert st["SPY"]["beta"] == 1.0
    assert 1.8 < st["X"]["beta"] < 2.3
    assert st["X"]["d"] == "2026-11-18" and st["X"]["r1"] is not None


def test_factor_scores():
    rows = {f"S{i}": {"s": "T", "roe": i, "roa": i, "nm": i, "de": 100 - i, "s3": i, "s1": i, "e3": i,
                      "ey": i / 1000, "dy": 0.0, "beta": 2 - i / 100, "r1": i} for i in range(100)}
    rows["BANK"] = {"s": "F", "roe": 99, "roa": 99, "nm": 99, "de": 1e9, "s3": None, "s1": None, "e3": None,
                    "ey": None, "dy": None, "beta": None, "r1": None}
    sc = B.factor_scores(rows, set(rows))
    assert sc["S99"]["fq"] > 0.95 and sc["S0"]["fq"] < 0.05
    assert sc["S99"]["flv"] > 0.95 and sc["S99"]["fm"] > 0.95
    assert sc["BANK"]["fq"] > 0.95          # debt/equity is ignored for financials
    assert sc["BANK"]["fg"] is None and sc["BANK"]["fm"] is None


def test_roll_weights():
    idx = pd.to_datetime(["2026-11-10", "2026-11-11", "2026-11-12"])
    close = pd.DataFrame({"A": [10, 10, 20], "B": [10, 10, 10]}, index=idx)
    h, to = B.roll_weights({"A": 0.4, "B": 0.4}, "2026-11-11", close)   # 0.2 of the ETF is a residual outside the list
    assert to == "2026-11-12"
    assert abs(sum(h.values()) - 0.8) < 1e-6 and abs(h["A"] / h["B"] - 2) < 1e-4


def test_gate():
    import datetime as dt
    gs = importlib.util.spec_from_file_location("expo_gate", Path(__file__).resolve().parents[1] / "tools" / "expo" / "gate.py")
    G = importlib.util.module_from_spec(gs)
    gs.loader.exec_module(G)
    utc = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)
    # Wed 25.11.2026 05:00 UTC (00:00 New York): the last finished session is Tue 24.11
    assert G.decide({"asof": "2026-11-24", "built": "2026-11-24T22:00Z"}, utc("2026-11-25T05:00"))[0] is True
    assert G.decide({"asof": "2026-11-23", "built": "2026-11-24T14:55Z"}, utc("2026-11-25T05:00"))[0] is False
    # Thu 26.11.2026 (Thanksgiving) after the close: built after it without data for it -> stop rebuilding
    assert G.decide({"asof": "2026-11-25", "built": "2026-11-26T22:30Z"}, utc("2026-11-26T23:30"))[0] is True
    assert G.decide({"asof": "2026-11-25", "built": "2026-11-26T05:00Z"}, utc("2026-11-26T23:30"))[0] is False
    # Sunday: the last session is Friday
    assert G.decide({"asof": "2026-11-27", "built": "2026-11-28T03:00Z"}, utc("2026-11-29T10:00"))[0] is True
