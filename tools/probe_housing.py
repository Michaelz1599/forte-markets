"""One-off probe (temporary branch probe-housing only), round 3: walk the CBS series catalog under subject 44 (construction
and real estate) to find the series of new apartments sold and remaining for sale, and fetch their data."""
import json
import pathlib
import sys
import traceback

sys.path.insert(0, ".")
from pipeline.common import get  # noqa: E402

OUT = pathlib.Path("state/probe_housing3")
OUT.mkdir(parents=True, exist_ok=True)
HOST = "https://apis.cbs.gov.il"
lines, calls = [], [0]


def save(name, text):
    (OUT / f"{name}.txt").write_text(text[:900_000], encoding="utf-8")


def level(lvl, subject):
    calls[0] += 1
    return get(f"{HOST}/series/catalog/level", params={"id": lvl, "subject": subject, "format": "json", "download": "false"},
               timeout=60, tries=2, expect_json=True)


def entries(js):
    c = (js or {}).get("catalogs") or {}
    return c.get("catalog") or []


def walk(path, lvl):
    if lvl > 6 or calls[0] > 220:
        return
    subj = ",".join(str(p) for p in path)
    try:
        js = level(lvl, subj)
    except Exception as e:
        lines.append(f"{'  ' * lvl}L{lvl} {subj} ERROR {e}")
        return
    es = entries(js)
    if not es:
        lines.append(f"{'  ' * lvl}L{lvl} {subj} (empty) {json.dumps(js, ensure_ascii=False)[:300]}")
    for e in es:
        lines.append(f"{'  ' * lvl}L{lvl} {json.dumps(e, ensure_ascii=False)[:400]}")
        p = e.get("path") or []
        nm = e.get("name") or ""
        if p and len(p) == lvl and (lvl < 3 or any(w in nm for w in ("דירות", "מכיר", "בנייה", "בניה", "מלאי", "היצע"))):
            walk(p, lvl + 1)


try:
    walk([44], 2)
except Exception:
    lines.append(traceback.format_exc())
save("cbs_walk44", "\n".join(lines))

# fetch data for leaf series whose names mention apartments for sale / sold
ids = []
for ln in lines:
    if "מכיר" in ln or "למכירה" in ln or "נמכרו" in ln:
        try:
            e = json.loads(ln.split(" ", 1)[1] if ln.strip().startswith("L") else ln)
        except Exception:
            s = ln.strip()
            try:
                e = json.loads(s[s.index("{"):])
            except Exception:
                continue
        for k in ("id", "code", "seriesId"):
            if e.get(k):
                ids.append(e[k])
out = []
for sid in ids[:25]:
    try:
        js = get(f"{HOST}/series/data/list", params={"id": sid, "startPeriod": "01-2023", "endPeriod": "12-2026", "format": "json", "download": "false"},
                 timeout=60, tries=2, expect_json=True)
        out.append(f"== {sid}\n" + json.dumps(js, ensure_ascii=False)[:6000])
    except Exception as e:
        out.append(f"== {sid} ERROR {e}")
save("cbs_series_data", "\n\n".join(out) or "(no ids found)")
print("done", calls[0])
