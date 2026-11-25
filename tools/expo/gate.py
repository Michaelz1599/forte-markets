#!/usr/bin/env python3
"""Should expo-daily build now? (standard library only, runs before anything is installed)

expo-daily is started after every run of the main pipeline and by a few backup slots, because GitHub starts scheduled
runs hours late. This gate lets a run through only when data/expo/market.json is not yet as of the last finished US
session: the last weekday whose 16:20 New York time has passed. It also stops once a build ran after that close
without reaching it (a US holiday), so a holiday does not rebuild on every trigger.
Prints skip=true|false (append it to $GITHUB_OUTPUT).
"""
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
CLOSE = dt.time(16, 20)


def last_session(now_ny: dt.datetime) -> dt.date:
    d = now_ny.date()
    if now_ny.weekday() >= 5 or now_ny.time() < CLOSE:
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def decide(market: dict, now_utc: dt.datetime) -> tuple[bool, str]:
    exp = last_session(now_utc.astimezone(NY))
    asof = market.get("asof") or ""
    if asof >= exp.isoformat():
        return True, f"up to date: asof {asof}, last US session {exp}"
    built = market.get("built") or ""
    try:
        b = dt.datetime.strptime(built, "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return False, f"no build time; asof {asof}, last US session {exp}"
    if b >= dt.datetime.combine(exp, CLOSE, NY):
        return True, f"built {built} after the {exp} close without data for it (holiday?)"
    return False, f"stale: asof {asof}, last US session {exp}"


if __name__ == "__main__":
    p = Path(sys.argv[1] if len(sys.argv) > 1 else "data/expo/market.json")
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        m = {}
    skip, why = decide(m, dt.datetime.now(dt.timezone.utc))
    print(why, file=sys.stderr)
    print(f"skip={'true' if skip else 'false'}")
