"""Marketing tab: price stats, the Tel Bond spread parser, headline relevance and the site payload."""
import json

import numpy as np
import pandas as pd

from pipeline import marketing as m


def test_stats_periods():
    idx = pd.bdate_range("2025-10-01", "2026-11-10")
    s = pd.Series(np.linspace(100, 150, len(idx)), index=idx.strftime("%Y-%m-%d"))
    st = m.stats(s)
    assert st["date"] == "2026-11-10"
    base_y = s[s.index < "2026-01-01"].iloc[-1]
    assert abs(st["ytd"] - (150 / base_y - 1)) < 1e-3
    base_m = s[s.index < "2026-11-01"].iloc[-1]
    assert abs(st["mtd"] - (150 / base_m - 1)) < 1e-3
    assert st["d1"] > 0 and st["dd52"] == 0


def test_tel_bond_spread_weighted(monkeypatch):
    rows = "".join(f"<tr><td>אג {i}</td><td>{w}</td><td>3</td><td>2</td><td>{s}</td></tr>" for i, (w, s) in enumerate([(2, 1.0), (1, 2.5), (1, 0.5), (3, 1.2), (3, 0.8)]))
    html = ("<div>נכון ל: 14/09/2026</div><table><thead><tr><th>שם הנייר</th><th>משקל ב-%</th><th>תשואה ברוטו</th><th>מח\"ם</th>"
            f"<th>מרווח מהממשלתי</th></tr></thead><tbody>{rows}</tbody></table>")
    monkeypatch.setattr(m, "get", lambda *a, **k: type("R", (), {"text": html})())
    d, v = m.tel_bond_spread("x")
    assert d == "2026-09-14" and v["n"] == 5
    assert abs(v["spread"] - (2 * 1.0 + 2.5 + 0.5 + 3 * 1.2 + 3 * 0.8) / 10) < 1e-3


def test_relevance_uses_whole_words():
    iss = m.issuers()
    assert m._relevant({"t": "בנק לאומי מגייס חוב"}, iss["leumi"])
    assert not m._relevant({"t": "הבנקים בירידות"}, iss["leumi"])
    assert not m._relevant({"t": "מותגי ביגוד בירידה"}, iss["big"])
    assert m._relevant({"t": "Nvidia shares fall"}, iss["NVDA"])


def test_holdings_link_to_profiles_and_payload_builds():
    hold = json.loads((m.MK / "holdings.json").read_text(encoding="utf-8"))["holdings"]
    iss = m.issuers()
    assert hold and all(h["i"] in iss for h in hold)
    assert all("שווי" not in json.dumps(h, ensure_ascii=False) for h in hold)
    p = m.build_payload()
    assert p["issuers"] and p["holdings"] and "spreads" in p
