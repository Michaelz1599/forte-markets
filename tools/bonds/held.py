"""Refresh the held-series list of data/bonds/base.json from data/marketing/holdings.json (names only).
Bond names are matched to TASE ids through data/bonds/names.json (normalised Magma names of the dashboard's bonds)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def norm(s: str) -> str:
    s = str(s).replace("אגח", "").replace('אג"ח', "").replace("סד'", "").replace("סד ", "").replace("סדרה", "")
    return re.sub(r"[\"'׳״.\-\s]", "", s)


def main() -> None:
    bp = ROOT / "data/bonds/base.json"
    base = json.loads(bp.read_text(encoding="utf-8"))
    idx = json.loads((ROOT / "data/bonds/names.json").read_text(encoding="utf-8"))
    H = json.loads((ROOT / "data/marketing/holdings.json").read_text(encoding="utf-8"))
    bonds = [x for x in H["holdings"] if x.get("k") == "bond"]
    ids = sorted({i for x in bonds for i in idx.get(norm(x["n"]), []) if i in base["bonds"]})
    unmatched = sorted({x["n"] for x in bonds if not idx.get(norm(x["n"]))})
    old = base.get("held") or {}
    base["held"] = {"asof": H.get("asof"), "src": old.get("src", "holdings.json"), "ids": ids}
    bp.write_text(json.dumps(base, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"held: {len(ids)} series (was {len(old.get('ids', []))}); holdings asof {H.get('asof')}; "
          f"{len(unmatched)} bond names not in the dashboard universe")


if __name__ == "__main__":
    main()
