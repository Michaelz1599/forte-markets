"""Shared helpers: series storage, HTTP, run status."""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SERIES_DIR = ROOT / "data" / "series"
PRICES_CSV = ROOT / "data" / "prices" / "close.csv"
STATE_DIR = ROOT / "state"
SITE_DIR = ROOT / "site"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")


def today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def cutoff_date() -> str:
    """Last date whose values are final: today only after 21:00 UTC (after the US close), else yesterday."""
    now = dt.datetime.now(dt.timezone.utc)
    d = now.date() if now.hour >= 21 else now.date() - dt.timedelta(days=1)
    return d.isoformat()


def iso(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]


# ---------------------------------------------------------------- series files
def read_series(sid: str) -> dict[str, float]:
    p = SERIES_DIR / f"{sid}.csv"
    if not p.exists():
        return {}
    out = {}
    with p.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                v = float(row["value"])
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                out[row["date"][:10]] = v
    return out


def write_series(sid: str, data: dict[str, float]) -> None:
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    rows = sorted((d, v) for d, v in data.items() if v is not None and math.isfinite(v))
    with (SERIES_DIR / f"{sid}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "value"])
        for d, v in rows:
            w.writerow([d, repr(round(v, 6)) if not float(v).is_integer() else int(v)])


def merge_series(sid: str, new: dict[str, float], replace_from: str | None = None) -> dict:
    """Merge new points into the stored series. Returns a small change report.

    replace_from: if given, stored points on/after this date that are missing from `new`
    are kept (we never delete history on a partial fetch)."""
    cur = read_series(sid)
    added = sum(1 for d in new if d not in cur)
    changed = sum(1 for d, v in new.items() if d in cur and abs(cur[d] - v) > 1e-9)
    cur.update({d: float(v) for d, v in new.items() if v is not None and math.isfinite(float(v))})
    write_series(sid, cur)
    return {"added": added, "changed": changed, "last": max(cur) if cur else None, "n": len(cur)}


# ---------------------------------------------------------------- HTTP
_session = None


def http() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        _session = s
    return _session


def get(url: str, *, params=None, headers=None, timeout=40, tries=3, expect_json=False):
    last = None
    for i in range(tries):
        try:
            r = http().get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json() if expect_json else r
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 403, 404, 418):
                break
        except Exception as e:  # network errors, JSON errors
            last = f"{type(e).__name__}: {e}"[:300]
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url[:120]} -> {last}")


# ---------------------------------------------------------------- run status
class Status:
    def __init__(self):
        self.started = dt.datetime.now(dt.timezone.utc)
        self.sources: list[dict] = []

    def add(self, key: str, name: str, ok: bool, as_of: str | None = None, msg: str = "", detail=None):
        self.sources.append({"key": key, "name": name, "ok": bool(ok), "asOf": as_of, "msg": msg[:400],
                             **({"detail": detail} if detail else {})})
        flag = "OK " if ok else "ERR"
        print(f"[{flag}] {name}: asOf={as_of} {msg}", flush=True)

    def to_dict(self) -> dict:
        ok = all(s["ok"] for s in self.sources)
        bad = [s["name"] for s in self.sources if not s["ok"]]
        return {
            "lastRun": self.started.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "finished": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "ok": ok,
            "failed": bad,
            "sources": self.sources,
        }


def save_probe(name: str, text: str) -> None:
    """Keep a sample of an unexpected response so the parser can be fixed later."""
    d = STATE_DIR / "probe"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.txt").write_text(text[:6000], encoding="utf-8")


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip() not in ("", "0", "false", "False")
