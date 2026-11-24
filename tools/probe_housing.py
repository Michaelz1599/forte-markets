"""One-off probe (temporary branch probe-housing only), round 4: run the new pipeline/housing.py against the live
Bank of Israel service and keep its output, so the site sections can be built and checked on real data."""
import json
import pathlib
import sys
import time

sys.path.insert(0, ".")
from pipeline import housing  # noqa: E402

OUT = pathlib.Path("state/probe_housing4")
OUT.mkdir(parents=True, exist_ok=True)
t0 = time.time()
out, msg = housing.update(force=True)
(OUT / "msg.txt").write_text(f"{msg}\nseconds={time.time() - t0:.0f}\n", encoding="utf-8")
(OUT / "mkt_housing.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
print(msg)
