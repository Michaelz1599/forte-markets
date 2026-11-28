"""Offline tests of "גרפים - ישראל": the indicators against TradingView, the page's JavaScript against the Python,
the storage of the bars and the site files."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline import ilcharts

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "mztf_2026-11-27.csv"


def _mztf(intraday=True):
    """Mizrahi Tefahot's bars; with the bar of 27.11.2026 as it stood in the TradingView screenshot (13:xx)."""
    raw = pd.read_csv(FIX, index_col=0)
    raw.index = raw.index.astype(str)
    ohl = {f: raw[[f]].rename(columns={f: "MZTF"}) for f in ilcharts.FIELDS}
    df = ilcharts.bars_frame(ohl, "MZTF")
    if intraday:
        df.loc["2026-11-27", ["h", "l", "c", "v"]] = [20870, 20490, 20750, 512520]
    return df


def test_indicators_match_the_tradingview_screenshot():
    df = _mztf()
    c, h, l, v = (df[k].to_numpy(dtype=float) for k in ("c", "h", "l", "v"))
    assert round(ilcharts.sma(c, 50)[-1]) == 22464
    assert round(ilcharts.sma(c, 21)[-1]) == 21506
    assert abs(ilcharts.sma(c, 200)[-1] - 22699) < 3            # 22,697.9 here; Yahoo's old bars differ slightly
    r = ilcharts.rsi(c)
    assert round(r[-1], 2) == 40.46 and round(ilcharts.sma(r, 14)[-1], 2) == 38.75
    assert round(ilcharts.cmf(h, l, c, v)[-1], 2) == -0.06
    boxes = [(df.index[b["start"]], df.index[b["end"]], b["top"], b["bot"], b["dir"]) for b in ilcharts.darvas(h, l, c)]
    # the last five boxes on the screenshot (September to November 2026)
    assert boxes[-5:] == [("2026-09-17", "2026-09-29", 24380, 23170, -1), ("2026-09-30", "2026-10-15", 23470, 21860, 1),
                          ("2026-10-21", "2026-11-04", 23800, 21960, -1), ("2026-11-10", "2026-11-17", 23040, 20950, -1),
                          ("2026-11-18", "2026-11-23", 21890, 20310, -1)]
    s = ilcharts.summary(df)
    assert s["dv"] == {"top": 21890, "bot": 20310, "open": False, "dir": -1, "brk": "2026-11-24", "ago": 3}
    assert s["ch"] == 1.27 and s["rsi"] == 40.5 and s["cmf"] == -0.057


def test_darvas_rules():
    # top 10 holds three bars, bottom 6 holds one bar, then a high above 10 closes the box upwards
    h = np.array([8, 10, 9, 9, 8, 7, 7.5, 9, 11, 10.5, 10.4, 10.2, 10.1])
    l = np.array([7, 9, 8, 7, 6, 6.5, 7, 8, 10, 9.8, 9.7, 9.9, 9.95])
    c = (h + l) / 2
    b = ilcharts.darvas(h, l, c)
    assert b[0] == {"start": 1, "top": 10, "bot": 6, "formed": 5, "end": 7, "dir": 1}
    # the next top is looked for from the breakout bar: 11 holds three bars, and the bottom 9.7 holds one more
    assert b[1]["start"] == 8 and b[1]["top"] == 11 and b[1]["bot"] == 9.7 and b[1]["dir"] == 0
    # a high above the top before the bottom holds starts the top over
    h2 = np.array([5, 6, 5.5, 5.4, 5.3, 6.5, 6, 5.9, 5.8, 5.7, 6.2])
    l2 = h2 - 1
    b2 = ilcharts.darvas(h2, l2, h2 - .5)
    assert len(b2) == 1 and b2[0] == {"start": 5, "top": 6.5, "bot": 4.7, "formed": 10, "end": 10, "dir": 0}


def _js_block():
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"// ilc-indicators:begin[^\n]*\n([\s\S]*?)// ilc-indicators:end", page)
    assert m, "the indicator block is missing from web/index.html"
    return m.group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_page_indicators_equal_the_pipeline(tmp_path):
    rng = np.random.default_rng(7)
    cases = {"mztf": _mztf()}
    c = 1000 * np.exp(np.cumsum(rng.normal(0, .02, 700)))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * (1 + rng.uniform(0, .02, 700)), np.minimum(o, c) * (1 - rng.uniform(0, .02, 700))
    v = rng.integers(0, 5e5, 700).astype(float)
    v[100:130] = np.nan                                     # days without volume
    cases["rand"] = pd.DataFrame({"o": o, "h": h, "l": l, "c": c, "v": v}, index=[str(i) for i in range(700)])
    data = {k: {f: [None if not np.isfinite(x) else float(x) for x in df[f].to_numpy(dtype=float)] for f in "ohlcv"} for k, df in cases.items()}
    (tmp_path / "in.json").write_text(json.dumps(data))
    js = _js_block() + """
const fs = require('fs'); const d = JSON.parse(fs.readFileSync(process.argv[2]));
const out = {};
for (const [k, b] of Object.entries(d)) {
  const r = ilcRsi(b.c, 14);
  out[k] = { s50: ilcSma(b.c, 50), s200: ilcSma(b.c, 200), rsi: r, rsiMa: ilcSma(r, 14), cmf: ilcCmf(b.h, b.l, b.c, b.v, 20), boxes: ilcDarvas(b.h, b.l, b.c) };
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
"""
    (tmp_path / "t.js").write_text(js)
    subprocess.run(["node", str(tmp_path / "t.js"), str(tmp_path / "in.json"), str(tmp_path / "out.json")], check=True)
    out = json.loads((tmp_path / "out.json").read_text())
    arr = lambda x: np.array([np.nan if y is None else y for y in x], dtype=float)
    for k, df in cases.items():
        c, h, l, v = (df[f].to_numpy(dtype=float) for f in "chlv")
        r = ilcharts.rsi(c)
        for name, py in (("s50", ilcharts.sma(c, 50)), ("s200", ilcharts.sma(c, 200)), ("rsi", r), ("rsiMa", ilcharts.sma(r, 14)), ("cmf", ilcharts.cmf(h, l, c, v))):
            js_v = arr(out[k][name])
            assert np.array_equal(np.isnan(js_v), np.isnan(py)), (k, name)
            assert np.allclose(js_v[~np.isnan(py)], py[~np.isnan(py)], rtol=1e-9, atol=1e-9), (k, name)
        assert out[k]["boxes"] == [{kk: (float(x) if kk in ("top", "bot") else x) for kk, x in b.items()} for b in ilcharts.darvas(h, l, c)], k


def _fake_bars(syms, start, end="2026-11-27", seed=0, unit_jump=None):
    rng = np.random.default_rng(seed)
    idx = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, end)]
    c = pd.DataFrame(1000 * np.exp(np.cumsum(rng.normal(0, .01, (len(idx), len(syms))), axis=0)), index=idx, columns=syms)
    o = c.shift(1).fillna(c)
    return {"close": c, "open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "volume": c * 0 + 1e5}


def _paths(tmp_path, monkeypatch, stocks):
    monkeypatch.setattr(ilcharts, "CSV", {f: tmp_path / f"tase_{f}.csv" for f in ilcharts.FIELDS})
    monkeypatch.setattr(ilcharts, "DERIVED", tmp_path / "ilcharts.json")
    cfg = tmp_path / "tase_all.json"
    cfg.write_text(json.dumps({"asof": "2026-11-27", "sectors": {"בנקים": {"g": "פיננסי", "l1": "בנקים"}},
                               "stocks": stocks}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ilcharts, "CONFIG", cfg)


def test_run_backfills_once_tries_alternatives_and_writes_site_files(tmp_path, monkeypatch):
    stocks = [{"y": "AAA.TA", "sym": "AAA", "name": "אאא", "en": "AAA", "sec": "בנקים", "id": 1, "f": "i"},
              {"y": "BBB.TA|BBX.TA", "sym": "BBB", "name": "בבב", "en": "BBB", "sec": "בנקים", "id": 2},
              {"y": "NONE.TA", "sym": "NONE", "name": "אין", "en": "NONE", "sec": "בנקים", "id": 3, "f": "m"}]
    _paths(tmp_path, monkeypatch, stocks)
    calls = []

    def fake(syms, start):
        calls.append((tuple(syms), start))
        known = [s for s in syms if s in ("AAA.TA", "BBX.TA")]          # Yahoo knows BBB only by its second symbol
        return _fake_bars(known, "2022-01-03", seed=len(calls)) if known else {}
    monkeypatch.setattr(ilcharts, "yf_ohlc", fake)
    monkeypatch.setattr(ilcharts, "today_utc", lambda: pd.Timestamp("2026-11-28").date())
    state, msg = ilcharts.run()
    assert calls[0] == (("AAA.TA", "BBB.TA", "NONE.TA"), ilcharts.HIST_FROM) and calls[1] == (("BBX.TA",), ilcharts.HIST_FROM)
    assert state["n"] == 2 and state["of"] == 3 and list(state["missing"]) == ["NONE"] and state["asof"] == "2026-11-27"
    st = ilcharts.read_ohlc()
    assert list(st["close"].columns) == ["AAA", "BBB"] and st["close"].index[0] == "2022-01-03"
    # the next run: only the last weeks of the known stocks; the missing one is retried a week later
    calls.clear()
    ilcharts.run()
    assert len(calls) == 2 and all(s != ilcharts.HIST_FROM for _, s in calls) and ("NONE.TA",) not in [c[0] for c in calls]
    files, idx = ilcharts.site_files()
    assert set(files) == {"AAA.json", "BBB.json"} and idx["n"] == 2 and idx["of"] == 3
    rec = files["AAA.json"]
    assert len(rec["t"]) == len(rec["c"]) == len(rec["v"]) and rec["t"] == sorted(rec["t"])
    row = next(r for r in idx["stocks"] if r["s"] == "AAA")
    assert row["file"] == "AAA.json" and row["f"] == "i" and row["d"] == "2026-11-27" and "dv" in row and row["rsi"] is not None
    assert "file" not in next(r for r in idx["stocks"] if r["s"] == "NONE")


def test_universe_config_is_consistent():
    cfg = json.loads((ROOT / "config" / "tase_all.json").read_text(encoding="utf-8"))
    syms = [s["sym"] for s in cfg["stocks"]]
    assert len(syms) == len(set(syms)) and len(syms) > 500
    for s in cfg["stocks"]:
        assert s["name"] and s["y"].split("|")[0] and s["sec"] in cfg["sectors"], s
        assert ilcharts.file_name(s["sym"]).endswith(".json")
    assert len({ilcharts.file_name(s) for s in syms}) == len(syms)      # no two stocks share a file
