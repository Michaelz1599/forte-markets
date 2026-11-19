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
              ["APPLE INC", "AAPL", "037833100", "2046251", 7.5, "Information Technology", 1, "USD"],
              ["BERKSHIRE HATHAWAY INC CL B", "BRK.B", "084670702", "2073390", 1.5, "Financials", 1, "USD"],
              ["US DOLLAR", "CASH_USD", "-", "-", 0.1, "-", 1, "USD"]]:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    res = B.parse_ssga(buf.getvalue())
    assert res["asof"] == "2026-11-18"
    assert set(res["h"]) == {"AAPL", "BRK-B"}
    assert abs(sum(res["h"].values()) - 1) < 1e-6
    assert res["meta"]["AAPL"] == {"name": "APPLE INC", "s": "T", "cu": "037833100"}


def test_parse_ishares_and_canon():
    csv = ('iShares Semiconductor ETF\nFund Holdings as of,"Nov 18, 2026"\nInception Date,"Jul 10, 2001"\n\n'
           'Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price\n'
           '"NVDA","NVIDIA CORP","Information Technology","Equity","1","9.50","1","1","1"\n'
           '"BRKB","BERKSHIRE","Financials","Equity","1","0.50","1","1","1"\n'
           '"USD","USD CASH","Cash and/or Derivatives","Cash","1","0.10","1","1","1"\n')
    res = B.parse_ishares(csv)
    assert res["asof"] == "2026-11-18" and set(res["h"]) == {"NVDA", "BRKB"}
    m = B.canon_keys(res["h"], {"NVDA", "BRK-B"})
    assert set(m) == {"NVDA", "BRK-B"} and abs(m["NVDA"] - 0.95) < 1e-6


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
