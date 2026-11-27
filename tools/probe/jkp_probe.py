"""Temporary probe: what JKP (jkpfactors.com) publishes for Israel. Saves raw files under probe_out/."""
import io, json, time, zipfile, pathlib, requests
OUT = pathlib.Path("probe_out"); OUT.mkdir(exist_ok=True)
BASE = "https://jkpfactors-data.s3.amazonaws.com/public/"
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (forte-markets probe)"
log = []
def note(*a):
    s = " ".join(str(x) for x in a); print(s); log.append(s)
r = S.get(BASE + "availability.json", timeout=60)
note("availability", r.status_code, len(r.content), r.headers.get("Last-Modified"))
(OUT / "availability.json").write_bytes(r.content)
av = r.json()
note("top keys", list(av.keys()))
for ds in ("factors", "portfolios", "industry"):
    regs = av.get(ds, {})
    note(ds, "regions:", len(regs), "isr" in regs, sorted(k for k in regs if len(k) != 3 or k in ("isr", "usa"))[:40])
    if "isr" in regs:
        note(ds, "isr selectors:", len(regs["isr"]), regs["isr"][:200])
note("monthly_only isr:", (av.get("factors_monthly_only") or {}).get("isr"))
b = lambda x: "%5B" + x + "%5D"
for sel, freq, w, keep in [("all_themes", "monthly", "vw_cap", True), ("all_factors", "monthly", "vw_cap", True), ("mkt", "monthly", "vw_cap", True),
                           ("all_themes", "daily", "vw_cap", True), ("mkt", "daily", "vw_cap", True), ("all_themes", "monthly", "ew", False)]:
    url = BASE + f"{b('isr')}_{b(sel)}_{b(freq)}_{b(w)}.zip"
    t = time.time()
    try:
        r = S.get(url, timeout=180)
    except Exception as e:
        note("FAIL", sel, freq, w, e); continue
    note(sel, freq, w, r.status_code, len(r.content), "bytes", r.headers.get("Last-Modified"), f"{time.time()-t:.1f}s")
    if r.status_code != 200:
        note(r.text[:300]); continue
    z = zipfile.ZipFile(io.BytesIO(r.content))
    for n in z.namelist():
        data = z.read(n)
        lines = data.decode("utf-8", "replace").splitlines()
        note("  file", n, len(data), "bytes", len(lines), "lines")
        for l in lines[:4]: note("   ", l[:300])
        for l in lines[-3:]: note("   ", l[:300])
        if keep and n.lower().endswith(".csv"):
            (OUT / f"isr_{sel}_{freq}_{w}.csv").write_bytes(data)
(OUT / "log.txt").write_text("\n".join(log), encoding="utf-8")
