"""Reminders.

There is no scheduler. A reminder is a row with a due time, and delivery is a
client asking "anything due?" — the Telegram bot is already sitting in a polling
loop, so it costs nothing to ask. A background timer would add a thread, a
restart-recovery story, and a way to silently lose reminders across a crash.
Asking a store is none of those things.

Delivery is recorded so a reminder fires once, even if two clients poll.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import read_json, write_json

MAX_REMINDER_CHARS = 500


class ReminderStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._items: list[dict[str, Any]] = read_json(self.path, [])
        self._next = max((int(r.get("id", 0)) for r in self._items), default=0) + 1

    def add(self, session_id: str, text: str, due_at: str) -> dict[str, Any]:
        due = parse_time(due_at)
        text = " ".join(text.split())[:MAX_REMINDER_CHARS]
        if not text:
            raise ValueError("a reminder needs some text")

        item = {
            "id": self._next,
            "session_id": session_id,
            "text": text,
            "due_at": due.isoformat(timespec="seconds"),
            "created_at": _now().isoformat(timespec="seconds"),
            "delivered_at": None,
        }
        self._next += 1
        self._items.append(item)
        self._save()
        return dict(item)

    def pending(self, session_id: str | None = None) -> list[dict[str, Any]]:
        items = [
            dict(r)
            for r in self._items
            if r["delivered_at"] is None
            and (session_id is None or r["session_id"] == session_id)
        ]
        return sorted(items, key=lambda r: r["due_at"])

    def due(self, session_id: str | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
        moment = now or _now()
        return [
            r for r in self.pending(session_id) if parse_time(r["due_at"]) <= moment
        ]

    def cancel(self, reminder_id: int) -> dict[str, Any] | None:
        for i, item in enumerate(self._items):
            if int(item["id"]) == int(reminder_id) and item["delivered_at"] is None:
                self._items.pop(i)
                self._save()
                return item
        return None

    def mark_delivered(self, reminder_id: int) -> bool:
        """Idempotent: a second caller for the same id gets False, not a repeat."""
        for item in self._items:
            if int(item["id"]) == int(reminder_id) and item["delivered_at"] is None:
                item["delivered_at"] = _now().isoformat(timespec="seconds")
                self._save()
                return True
        return False

    def _save(self) -> None:
        write_json(self.path, self._items)


def parse_time(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, assuming UTC when no zone is given.

    Naive and aware datetimes cannot be compared, and a reminder that raises on
    comparison never fires — so everything is normalised on the way in.
    """
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(
                f"{value!r} is not an ISO 8601 time (e.g. 2026-08-04T17:30:00Z)"
            ) from exc
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _now() -> datetime:
    return datetime.now(timezone.utc)
