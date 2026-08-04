"""Conversation storage, keyed by session id.

Deliberately small. A JSON file is enough for one user and a handful of
sessions, and it means restarting the service doesn't drop the thread you were
in the middle of. This is also where the phase-4 memory layer will hang off.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

Message = dict[str, Any]


def read_json(path: Path | None, default: Any) -> Any:
    """Load JSON, tolerating a missing or corrupt file.

    A damaged store costs one lost conversation; refusing to start costs the
    assistant entirely. The former is the better failure.
    """
    if not path or not path.exists():
        return default
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    return loaded if isinstance(loaded, type(default)) else default


def write_json(path: Path | None, data: Any) -> None:
    """Write via a temp file in the same directory, so a crash can't truncate."""
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


class ConversationStore:
    def __init__(self, path: Path | None = None, max_turns: int = 40) -> None:
        """`max_turns` counts messages, not exchanges — 40 is 20 back-and-forths."""
        self.path = Path(path) if path else None
        self.max_turns = max_turns
        self._data: dict[str, list[Message]] = {}
        self._load()

    def get(self, session_id: str) -> list[Message]:
        return list(self._data.get(session_id, []))

    def set(self, session_id: str, messages: list[Message]) -> None:
        self._data[session_id] = _trim(messages, self.max_turns)
        self._save()

    def clear(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self._save()

    def sessions(self) -> list[str]:
        return list(self._data)

    # ------------------------------------------------------------------ disk

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._data = loaded
        except (json.JSONDecodeError, OSError):
            # A corrupt store shouldn't stop the assistant from starting; the
            # cost is one lost conversation, and refusing to boot is worse.
            self._data = {}

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temp file in the same directory so a crash mid-write
        # can't leave a half-written store behind.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise


def _trim(messages: list[Message], max_turns: int) -> list[Message]:
    """Keep the most recent turns, starting on a user message.

    The API requires the first message to be `user`, and few-shot examples are
    prepended ahead of this, so a history starting with an assistant turn would
    produce two assistant messages in a row.
    """
    if len(messages) <= max_turns:
        trimmed = list(messages)
    else:
        trimmed = messages[-max_turns:]
    while trimmed and trimmed[0]["role"] != "user":
        trimmed.pop(0)
    return trimmed
