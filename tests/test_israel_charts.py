"""Offline tests of the Israeli stock candles: storage in data/prices/il_*.csv and the chart payloads."""
import json

import numpy as np
import pandas as pd

from pipeline import israel


def _bars(syms, start, end="2026-11-12", seed=0):
    rng = np.random.default_rng(seed)
    idx = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, end)]
    c = pd.DataFrame(1000 * np.exp(np.cumsum(rng.normal(0, .01, (len(idx), len(syms))), axis=0)), index=idx, columns=syms)
    o = c.shift(1).fillna(c)
    h = np.maximum(o, c) * 1.01
    lo = np.minimum(o, c) * 0.99
    return {"close": c, "open": o, "high": h, "low": lo, "volume": c * 0 + 1e5}


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(israel, "IL_OHLC", {f: tmp_path / f"il_{f}.csv" for f in ("open", "high", "low", "close")})
    monkeypatch.setattr(israel, "DERIVED", tmp_path / "israel.json")


def test_first_run_backfills_then_only_new_stocks(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    calls = []

    def fake(syms, start):
        calls.append((tuple(syms), start))
        return _bars(syms, "2013-01-01", seed=1)
    monkeypatch.setattr(israel, "yf_ohlc", fake)
    recent = _bars(["A.TA", "B.TA"], "2025-06-01", seed=1)
    msg = israel.store_ohlc(recent, ["A.TA", "B.TA"], {"A.TA", "B.TA", "C.TA"})
    assert calls == [(("A.TA", "B.TA"), israel.OHLC_FROM)] and "2" in msg
    st = israel.read_ohlc()
    assert st["close"].index[0] == "2013-01-01" and list(st["close"].columns) == ["A.TA", "B.TA"]
    # next run: nothing new to backfill; a stock that joins the list gets its whole history once
    israel.store_ohlc(_bars(["A.TA", "B.TA"], "2025-06-01", seed=1), ["A.TA", "B.TA"], {"A.TA", "B.TA", "C.TA"})
    assert len(calls) == 1
    israel.store_ohlc(_bars(["A.TA", "B.TA", "C.TA"], "2025-06-01", seed=1), ["A.TA", "B.TA", "C.TA"], {"A.TA", "B.TA", "C.TA"})
    assert calls[-1] == (("C.TA",), israel.OHLC_FROM)
    assert israel.read_ohlc()["close"]["C.TA"].first_valid_index() == "2013-01-01"
    # a stock dropped from the configuration is dropped from the files
    israel.store_ohlc(_bars(["A.TA"], "2025-06-01", seed=1), ["A.TA"], {"A.TA"})
    assert list(israel.read_ohlc()["close"].columns) == ["A.TA"]


def test_bad_bars_are_dropped_and_close_kept(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(israel, "yf_ohlc", lambda syms, start: _bars(syms, "2013-01-01"))
    b = _bars(["A.TA"], "2025-06-01")
    d = b["close"].index[-3]
    b["high"].loc[d, "A.TA"] = b["close"].loc[d, "A.TA"] * 0.5      # high below the close: not a valid bar
    israel.store_ohlc(b, ["A.TA"], {"A.TA"})
    st = israel.read_ohlc()
    assert np.isnan(st["high"]["A.TA"].reindex([d]).iloc[0]) and np.isnan(st["open"]["A.TA"].reindex([d]).iloc[0])
    assert not np.isnan(st["close"].loc[d, "A.TA"])


def test_chart_payloads(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(israel, "yf_ohlc", lambda syms, start: _bars(syms, "2013-01-01"))
    israel.store_ohlc(_bars(["LUMI.TA"], "2025-06-01"), ["LUMI.TA"], {"LUMI.TA"})
    (tmp_path / "israel.json").write_text(json.dumps({"sectorNames": {"banks": "בנקים"}, "stocks": [
        {"sym": "LUMI", "y": "LUMI.TA", "name": "לאומי", "sec": "banks", "rs": 80, "raw": 0.2, "cmf": 0.12},
        {"sym": "GONE", "y": "GONE.TA", "name": "x", "sec": "banks"}]}), encoding="utf-8")
    files, items = israel.chart_payloads()
    assert list(files) == ["LUMI.TA"] and list(items) == ["LUMI.TA"]
    f, it = files["LUMI.TA"], items["LUMI.TA"]
    assert len(f["t"]) == len(f["c"]) == len(f["o"]) == len(f["h"]) == len(f["l"]) > 2000
    assert all(x is not None for x in f["c"])
    assert it["il"] and it["ta"] == "LUMI" and it["rs"]["rs"] == 80 and it["cmf"]["cmf"] == 0.12
    assert it["last"] == f["c"][-1] and "spark" not in it and it["desc"].startswith("בנקים")
    json.dumps(files, allow_nan=False)


def test_unit_jump_rescaled_to_latest_unit():
    b = _bars(["A.TA", "B.TA"], "2025-01-01")
    d = b["close"].index[100]
    real = {k: b[k].copy() for k in ("open", "high", "low", "close")}
    for k in real:                                   # before d, A is quoted in shekels (100x smaller)
        b[k].loc[b[k].index < d, "A.TA"] /= 100
    vol = b["volume"].copy()
    assert israel.fix_units(b) == ["A.TA"]
    for k in real:
        assert np.allclose(b[k]["A.TA"], real[k]["A.TA"]) and np.allclose(b[k]["B.TA"], real[k]["B.TA"])
    assert b["volume"].equals(vol)
    assert israel.fix_units(b) == []                 # nothing left to fix


def test_large_real_moves_are_not_touched():
    b = _bars(["A.TA"], "2025-01-01")
    d = b["close"].index[50]
    for k in ("open", "high", "low", "close"):
        b[k].loc[b[k].index >= d, "A.TA"] *= 8      # a x8 day (e.g. a biotech) stays as it is
    before = b["close"]["A.TA"].copy()
    assert israel.fix_units(b) == [] and b["close"]["A.TA"].equals(before)


def test_single_day_bad_ticks_are_blanked():
    b = _bars(["A.TA", "B.TA"], "2025-01-01")
    d = b["close"].index[60]
    for k in ("open", "high", "low", "close"):
        b[k].loc[d, "A.TA"] = b["close"].loc[d, "A.TA"] / 7     # one bad tick that recovers the next day
    b["close"].loc[b["close"].index[80]:, "B.TA"] /= 3          # a real fall of two thirds that stays
    assert israel.drop_spikes(b) == 1
    assert np.isnan(b["close"].loc[d, "A.TA"]) and np.isnan(b["high"].loc[d, "A.TA"])
    assert b["close"]["B.TA"].notna().all()
