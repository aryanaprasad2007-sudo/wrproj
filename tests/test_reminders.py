from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from assistant.reminders import ReminderStore, parse_time

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
SOON = (NOW + timedelta(minutes=5)).isoformat()
PAST = (NOW - timedelta(minutes=5)).isoformat()


def test_add_and_list_pending(tmp_path: Path) -> None:
    r = ReminderStore(tmp_path / "r.json")
    item = r.add("s", "call the dentist", SOON)
    assert item["id"] == 1
    assert [x["text"] for x in r.pending("s")] == ["call the dentist"]


def test_pending_is_ordered_by_due_time(tmp_path: Path) -> None:
    r = ReminderStore(tmp_path / "r.json")
    r.add("s", "later", (NOW + timedelta(hours=2)).isoformat())
    r.add("s", "sooner", (NOW + timedelta(minutes=1)).isoformat())
    assert [x["text"] for x in r.pending("s")] == ["sooner", "later"]


def test_sessions_are_isolated(tmp_path: Path) -> None:
    """A reminder set from the phone must not surface on someone else's."""
    r = ReminderStore(tmp_path / "r.json")
    r.add("telegram:1", "mine", SOON)
    r.add("telegram:2", "theirs", SOON)
    assert [x["text"] for x in r.pending("telegram:1")] == ["mine"]
    assert len(r.pending()) == 2


def test_only_past_reminders_are_due(tmp_path: Path) -> None:
    r = ReminderStore(tmp_path / "r.json")
    r.add("s", "not yet", SOON)
    r.add("s", "overdue", PAST)
    assert [x["text"] for x in r.due("s", now=NOW)] == ["overdue"]


def test_delivery_happens_once(tmp_path: Path) -> None:
    """Two pollers must not both fire the same reminder."""
    r = ReminderStore(tmp_path / "r.json")
    item = r.add("s", "once only", PAST)
    assert r.mark_delivered(item["id"]) is True
    assert r.mark_delivered(item["id"]) is False
    assert r.due("s", now=NOW) == []


def test_delivered_reminders_leave_pending(tmp_path: Path) -> None:
    r = ReminderStore(tmp_path / "r.json")
    item = r.add("s", "done", PAST)
    r.mark_delivered(item["id"])
    assert r.pending("s") == []


def test_cancel(tmp_path: Path) -> None:
    r = ReminderStore(tmp_path / "r.json")
    item = r.add("s", "never mind", SOON)
    assert r.cancel(item["id"])["text"] == "never mind"
    assert r.pending("s") == []
    assert r.cancel(item["id"]) is None


def test_cannot_cancel_something_already_delivered(tmp_path: Path) -> None:
    r = ReminderStore(tmp_path / "r.json")
    item = r.add("s", "gone", PAST)
    r.mark_delivered(item["id"])
    assert r.cancel(item["id"]) is None


def test_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    ReminderStore(path).add("s", "persisted", SOON)
    reopened = ReminderStore(path)
    assert len(reopened.pending("s")) == 1
    assert reopened.add("s", "next", SOON)["id"] == 2


def test_empty_text_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ReminderStore(tmp_path / "r.json").add("s", "  ", SOON)


def test_bad_time_is_rejected_with_an_example(tmp_path: Path) -> None:
    """The message goes back to her as a tool error, so it has to be actionable."""
    with pytest.raises(ValueError, match="ISO 8601"):
        ReminderStore(tmp_path / "r.json").add("s", "x", "next tuesday")


# ------------------------------------------------------------- time parsing


def test_parses_utc_and_offsets() -> None:
    assert parse_time("2026-08-04T12:00:00Z") == NOW
    assert parse_time("2026-08-04T14:00:00+02:00") == NOW


def test_naive_times_are_assumed_utc() -> None:
    """Comparing naive and aware datetimes raises, and a reminder that raises
    on comparison never fires."""
    parsed = parse_time("2026-08-04T12:00:00")
    assert parsed.tzinfo is not None
    assert parsed == NOW


def test_a_naive_reminder_still_becomes_due(tmp_path: Path) -> None:
    r = ReminderStore(tmp_path / "r.json")
    r.add("s", "naive", "2026-08-04T11:00:00")
    assert len(r.due("s", now=NOW)) == 1
