"""AI compute pricing: Polymarket's implied price, the momentum signals and which alerts count as news."""
import datetime as dt
import json

import numpy as np

from pipeline import compute as c

P = {"fast": 7, "slow": 28, "band_min": 0.02, "band_k": 1.5, "surge": 0.10, "surge_k": 3.0, "pm_shift": 0.05, "alert_days": 3}
# the H100 December 2026 ladder as Polymarket showed it on 26.11.2026 (Polymarket's own PIRP: $3.03)
DEC = [(3.5, .105), (3.4, .125), (3.3, .215), (3.2, .325), (3.1, .445), (3.0, .555), (2.9, .635), (2.8, .765), (2.7, .865), (2.6, .895), (2.5, .915), (2.4, .925)]


def days(vals, start="2026-08-01"):
    d0 = dt.date.fromisoformat(start)
    return {(d0 + dt.timedelta(days=i)).isoformat(): float(v) for i, v in enumerate(vals)}


def test_implied_matches_polymarket_pirp():
    imp = c.implied(DEC)
    assert abs(imp["mean"] - 3.03) < 0.005
    assert abs(imp["med"] - 3.05) < 1e-6
    assert abs(imp["lo"] - 2.575) < 1e-6
    assert imp["hi"] is None and imp["kmax"] == 3.5   # the 90th percentile is above the ladder


def test_implied_smooths_crossed_quotes():
    imp = c.implied([(1, .9), (2, .4), (3, .45), (4, .1)])   # P(>3) quoted above P(>2): treated as P(>2)
    assert imp["med"] is not None and 1 < imp["med"] < 2


def test_momentum_turns_up_and_down():
    v = [10] * 40 + list(np.linspace(10, 13, 20)) + [13] * 20 + list(np.linspace(13, 10, 20))
    cur, ev = c.momentum(days(v), P)
    kinds = [e["kind"] for e in ev]
    assert "turn_down" in kinds and cur["reg"] == "down" and cur["state"] in ("down", "down_fading")
    assert kinds.index("surge") < kinds.index("turn_down")   # the first rise is a sharp week (+~10%)


def test_noise_does_not_flip_the_trend():
    rng = np.random.default_rng(7)
    v = 3 * (1 + rng.normal(0, 0.05, 150))   # a jumpy index (5% a day) with no trend
    cur, ev = c.momentum(days(v), P)
    turns = [e for e in ev if e["kind"].startswith("turn_")]
    assert len(turns) <= 2
    assert cur["band"] > P["band_min"]   # the threshold widens with the noise


def test_short_history_has_no_signal():
    cur, ev = c.momentum(days([2.9, 3.0, 3.1]), P)
    assert cur["state"] == "short" and ev == [] and cur["last"] == 3.1


def test_alerts_first_run_and_stale_are_not_news():
    now = "2026-11-27T09:10Z"
    a = [{"id": "gpu_h100:turn_up:2026-11-26", "gpu": "gpu_h100", "date": "2026-11-26"},
         {"id": "gpu_b200:turn_down:2026-11-10", "gpu": "gpu_b200", "date": "2026-11-10"}]
    first = c.merge_alerts([], a, now, {"gpu_h100": "2026-11-26", "gpu_b200": "2026-11-26"}, 3, True)
    assert all(x.get("old") for x in first)
    later = c.merge_alerts([], a, now, {"gpu_h100": "2026-11-26", "gpu_b200": "2026-11-26"}, 3, False)
    by = {x["id"]: x for x in later}
    assert by["gpu_h100:turn_up:2026-11-26"]["seen"] == now and not by["gpu_h100:turn_up:2026-11-26"].get("old")
    assert by["gpu_b200:turn_down:2026-11-10"].get("old")
    again = c.merge_alerts(later, a, "2026-11-28T09:10Z", {"gpu_h100": "2026-11-27"}, 3, False)
    assert {x["id"]: x["seen"] for x in again}["gpu_h100:turn_up:2026-11-26"] == now   # first-seen time is kept


def test_pm_month_parses_gamma(monkeypatch):
    slug = "h100-average-rental-price-in-december-2026"
    ev = [{"slug": slug, "closed": False, "endDate": "2027-01-01T04:59:00Z", "markets": [
        {"groupItemTitle": f"Above ${k:.2f}", "question": f"Will the average Ornn H100 rental price in December 2026 be above ${k:.2f}?",
         "outcomes": json.dumps(["Yes", "No"]), "outcomePrices": json.dumps([str(p), str(round(1 - p, 3))]), "volume": "1000", "closed": False}
        for k, p in DEC]}]
    monkeypatch.setattr(c, "get", lambda url, **kw: ev)
    r = c.pm_month("h100", 2026, 12)
    assert r["month"] == "2026-12" and r["n"] == 12 and r["vol"] == 12000 and abs(r["mean"] - 3.03) < 0.005


def test_pm_alert_on_weekly_shift():
    front = {"slug": "s", "month": "2026-12", "mean": 3.20, "vol": 50000}
    hist = {"s": {"2026-11-19": 3.00, "2026-11-25": 3.15}}
    a = c.pm_alerts({"name": "H100"}, front, hist, "2026-11-26", P)
    assert a and a[0]["kind"] == "pm_up" and abs(a[0]["chg"] - 0.0667) < 1e-3
    assert not c.pm_alerts({"name": "H100"}, {**front, "vol": 5000}, hist, "2026-11-26", P)   # too thin to alert
    assert "Polymarket" in c.alert_text({"name": "H100"}, a[0])
