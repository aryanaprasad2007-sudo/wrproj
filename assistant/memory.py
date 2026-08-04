"""Long-term memory: things she should still know next week.

Deliberately not a vector store. At personal scale the whole set fits in the
prompt, and injecting all of it beats retrieving some of it — no embedding
model, no similarity threshold to tune, no relevant fact quietly missed. If it
ever outgrows that, this is the file that changes.

Facts are written by her, through a tool, rather than extracted automatically
from transcripts. The model is good at judging what is worth keeping, and the
result is a short file a human can read and correct. A summariser produces
neither.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import read_json, write_json

# Bounds the prompt. Well past the point where a person would want to read it.
MAX_FACTS = 200
MAX_FACT_CHARS = 500


class MemoryStore:
    def __init__(self, path: Path | None = None, max_facts: int = MAX_FACTS) -> None:
        self.path = Path(path) if path else None
        self.max_facts = max_facts
        self._facts: list[dict[str, Any]] = read_json(self.path, [])
        self._next = max((int(f.get("id", 0)) for f in self._facts), default=0) + 1

    def all(self) -> list[dict[str, Any]]:
        return [dict(f) for f in self._facts]

    def add(self, text: str) -> dict[str, Any]:
        text = " ".join(text.split())[:MAX_FACT_CHARS]
        if not text:
            raise ValueError("a memory needs some text")

        # Re-remembering the same thing is common — she has no way to know what
        # she already wrote down. Refresh it rather than storing it twice.
        for fact in self._facts:
            if fact["text"].casefold() == text.casefold():
                fact["updated_at"] = _now()
                self._save()
                return dict(fact)

        fact = {"id": self._next, "text": text, "created_at": _now()}
        self._next += 1
        self._facts.append(fact)
        # Oldest out first. Anything still true tends to get restated.
        if len(self._facts) > self.max_facts:
            self._facts = self._facts[-self.max_facts :]
        self._save()
        return dict(fact)

    def remove(self, fact_id: int) -> dict[str, Any] | None:
        for i, fact in enumerate(self._facts):
            if int(fact["id"]) == int(fact_id):
                self._save_after(self._facts.pop(i))
                return fact
        return None

    def search(self, query: str) -> list[dict[str, Any]]:
        """Substring match. Adequate for a few hundred facts, and predictable."""
        needle = query.strip().casefold()
        if not needle:
            return self.all()
        return [dict(f) for f in self._facts if needle in f["text"].casefold()]

    def clear(self) -> None:
        self._facts = []
        self._save()

    def as_prompt(self) -> str:
        """Render for the system prompt. Empty string when there's nothing yet."""
        if not self._facts:
            return ""
        lines = [f"[{f['id']}] {f['text']}" for f in self._facts]
        return "\n".join(lines)

    # ------------------------------------------------------------------ inner

    def _save(self) -> None:
        write_json(self.path, self._facts)

    def _save_after(self, _removed: Any) -> None:
        self._save()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
