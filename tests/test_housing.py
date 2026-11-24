"""Marketing tab, housing / banks / insurance: the Bank of Israel parsing, the derived series, the merge of the banks'
own reports into the Bank of Israel history, and the hand-kept files."""
import json

from pipeline import housing as h
from pipeline import marketing as m


def test_boi_csv_and_derived_series(monkeypatch):
    csv_text = "SERIES_CODE,TIME_PERIOD,OBS_VALUE\nX,2025-08,100\nX,2025-09,101\nX,2026-08,98.5\nX,2026-09,\n"
    monkeypatch.setattr(h, "get", lambda *a, **k: type("R", (), {"text": csv_text})())
    s = h.boi("REAL_ES_DF", "X")
    assert s == {"2025-08": 100.0, "2025-09": 101.0, "2026-08": 98.5}   # an empty observation is skipped
    assert h.yoy(s) == {"2026-08": -1.5}
    parts = {"60": {"2026-08": 30.0}, "75": {"2026-08": 50.0}, "90": {"2026-08": 20.0}}
    assert h.share(parts, ["75", "90"]) == {"2026-08": 70.0}
    assert h.ratio({"2026-08": 4.0}, {"2026-08": 673.0}) == {"2026-08": round(4 / 673 * 100, 3)}


def test_placeholder_zero_quarter_is_dropped():
    rec = {"ni": {"d": ["2025-Q4", "2026-Q1", "2026-Q2"], "v": [856.0, 0.0, 1203.0]},
           "llp": {"d": ["2025-Q4", "2026-Q1", "2026-Q2"], "v": [90.0, 0.0, 0.0]},
           "roe": {"d": ["2025-Q4", "2026-Q1"], "v": [11.0, 0.0]}}
    out = h.clean_bank(rec)
    assert out["ni"]["d"] == ["2025-Q4", "2026-Q2"]
    assert out["llp"]["d"] == ["2025-Q4", "2026-Q2"] and out["llp"]["v"][-1] == 0.0   # a real zero provision stays
    assert out["roe"]["d"] == ["2025-Q4"]


def test_report_quarter_extends_the_bank_of_israel_history():
    derived = {"leumi": {"ni": {"d": ["2026-Q1", "2026-Q2"], "v": [2346.0, 2832.0]}, "equity": {"d": ["2026-Q2"], "v": [70.6]}}}
    hand = {"leumi": {"period": "2026-Q3", "rep": "2026-11-17", "ni_q": 2986, "equity": 71.4, "roe_q": 16.9, "clx_q": 184, "sum": "x", "src": []},
            "poalim": {"period": "2026-Q3", "ni_q": 2364}}
    out = m.banks_payload(derived, hand)
    assert out["leumi"]["ni"]["d"][-1] == "2026-Q3" and out["leumi"]["ni"]["v"][-1] == 2986 and out["leumi"]["ni"]["rep"] == "2026-Q3"
    assert out["leumi"]["roe"]["d"] == ["2026-Q3"] and out["leumi"]["rep"]["clx_q"] == 184
    assert out["poalim"]["ni"]["v"] == [2364]                       # a bank with no Bank of Israel data yet
    derived["leumi"]["ni"] = {"d": ["2026-Q3"], "v": [2990.0]}      # once the Bank of Israel has the quarter, its value stays
    assert m.banks_payload(derived, hand)["leumi"]["ni"]["v"] == [2990.0]


def test_hand_kept_files_and_payload():
    held = {x["i"] for x in json.loads((m.MK / "holdings.json").read_text(encoding="utf-8"))["holdings"]}
    banks = json.loads((m.MK / "banks.json").read_text(encoding="utf-8"))["banks"]
    ins = json.loads((m.MK / "insurers.json").read_text(encoding="utf-8"))["items"]
    hous = json.loads((m.MK / "housing.json").read_text(encoding="utf-8"))
    assert set(banks) <= held and set(ins) <= held
    for b in banks.values():
        assert b["period"][:4].isdigit() and "-Q" in b["period"] and b["ni_q"] is not None
        assert all(s["u"].startswith("https://") for s in b["src"])
    for x in ins.values():
        assert x["period"] and x["rep"] and all(s["u"].startswith("https://") for s in x["src"])
    assert all(u["m"][:4].isdigit() and u["v"] > 0 for u in hous["unsold"])
    p = m.build_payload()
    assert {"housing", "banks", "insurers"} <= set(p)
    assert p["insurers"].keys() == ins.keys()
    assert "unsold" in p["housing"] and "_comment" not in p["housing"]
