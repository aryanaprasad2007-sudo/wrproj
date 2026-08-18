"""
NightOwl Notion Command Center cache.

Same shape as calendar_cache.py: Claude queries the Command Center database
live via the Notion MCP connector (this script has no Notion credentials of
its own), hands the rows here, and this does the normalizing/sorting/capping
and writes the snapshot the Hub reads at build time.

    python notion_cache.py tasks.json

`tasks.json` is a plain list:
    [{"title": "...", "area": "School", "status": "To Do", "priority": "High",
      "due": "2026-08-07", "url": "https://..."}, ...]
"""

import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "notion.json")
MAX_TASKS = 12

PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2, None: 3}


def build(tasks, now=None):
    now = now or datetime.now()
    today = now.date()

    cleaned = []
    for t in tasks:
        title = (t.get("title") or "").strip()
        if not title or t.get("status") == "Done":
            continue
        due = t.get("due") or None
        due_date = None
        if due:
            try:
                due_date = datetime.fromisoformat(due[:10]).date()
            except ValueError:
                due_date = None
        cleaned.append({
            "title": title,
            "area": t.get("area"),
            "status": t.get("status") or "To Do",
            "priority": t.get("priority"),
            "due": due_date.isoformat() if due_date else None,
            "overdue": bool(due_date and due_date < today),
            "url": t.get("url"),
        })

    # Dated tasks first (soonest, and overdue ahead of everything), then
    # undated tasks after - not SQL's NULLS-FIRST default, which would bury
    # every real deadline under a pile of someday-tasks.
    def sort_key(t):
        has_due = t["due"] is not None
        due_val = t["due"] or "9999-99-99"
        return (0 if has_due else 1, due_val, PRIORITY_RANK.get(t["priority"], 3))

    cleaned.sort(key=sort_key)
    cleaned = cleaned[:MAX_TASKS]

    return {
        "fetchedAt": now.isoformat(),
        "fetchedAtLocal": now.strftime("%H:%M"),
        "tasks": cleaned,
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
    overdue = sum(1 for t in out["tasks"] if t["overdue"])
    print(f"notion cache -> {len(out['tasks'])} tasks ({overdue} overdue), synced {out['fetchedAtLocal']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
