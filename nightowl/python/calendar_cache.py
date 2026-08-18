"""
NightOwl calendar cache.

Claude Code pulls events live via the Google Calendar MCP connector (this
script has no Google credentials of its own - unattended Task Scheduler runs
can't do that pull, only an interactive Claude session can). This script just
takes whatever events Claude already fetched, normalizes and dedupes them, and
writes the snapshot the Hub reads at build time.

    python calendar_cache.py events.json

`events.json` is a plain list of simplified events:
    [{"title": "...", "start": "2026-08-03T13:00:00-07:00",
      "end": "2026-08-03T15:30:00-07:00", "allDay": false, "calendar": "School"}, ...]
"""

import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "calendar.json")
MAX_EVENTS = 14


def _parse(ts):
    # Handles both "...Z" and "...-07:00" offsets.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def build(events, now=None):
    now = now or datetime.now().astimezone()

    cleaned = []
    for e in events:
        if not e.get("start") or not e.get("end") or not e.get("title"):
            continue
        try:
            start = _parse(e["start"])
            end = _parse(e["end"])
        except ValueError:
            continue
        if end <= now:
            continue          # already finished - not useful on a forward-looking card
        cleaned.append({
            "title": e["title"],
            "start": e["start"],
            "end": e["end"],
            "allDay": bool(e.get("allDay", False)),
            "calendar": e.get("calendar", ""),
        })

    # Two calendars can carry the same block (e.g. a routine mirrored onto a
    # school calendar) - collapse exact start/end duplicates, first wins.
    seen = set()
    deduped = []
    for e in sorted(cleaned, key=lambda e: (e["start"], e["end"])):
        key = (e["start"], e["end"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    deduped = deduped[:MAX_EVENTS]

    return {
        "fetchedAt": now.isoformat(),
        "fetchedAtLocal": now.strftime("%H:%M"),
        "events": deduped,
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    with open(argv[1], "r", encoding="utf-8") as f:
        raw = json.load(f)

    out = build(raw)
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"calendar cache -> {len(out['events'])} events, synced {out['fetchedAtLocal']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
