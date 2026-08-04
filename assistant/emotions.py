"""Emotion-tag handling.

Every response opens with `[tag] `. The tag is stripped before the text is shown
(and, later, before it reaches the TTS engine) and is surfaced separately so the
avatar layer in phase 5 has an expression signal without a rewrite.
"""

from __future__ import annotations

# If we've buffered this many characters without closing a bracket, whatever is
# there isn't a tag — stop holding output back.
_MAX_TAG_LEN = 32


def split_emotion(text: str) -> tuple[str | None, str]:
    """Split a complete response into (tag, spoken text)."""
    stripped = text.lstrip()
    if stripped.startswith("[") and "]" in stripped[:_MAX_TAG_LEN]:
        close = stripped.index("]")
        return stripped[1:close].strip().lower(), stripped[close + 1 :].lstrip()
    return None, text


class EmotionStripper:
    """Incremental version of `split_emotion` for streamed responses.

    Buffers only the leading few characters — just enough to decide whether a
    tag is present — then passes everything through untouched.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._resolved = False
        # Set when a tag closed on a chunk boundary, leaving no text to strip
        # yet — the space after `]` then arrives in the *next* delta.
        self._pending_lstrip = False
        self.tag: str | None = None

    def feed(self, chunk: str) -> str:
        """Consume a stream delta; return the text that should be displayed."""
        if self._resolved:
            if self._pending_lstrip:
                chunk = chunk.lstrip()
                if chunk:
                    self._pending_lstrip = False
            return chunk

        self._buffer += chunk
        stripped = self._buffer.lstrip()

        if not stripped:
            return ""

        if not stripped.startswith("["):
            return self._resolve(self._buffer)

        if "]" in stripped:
            close = stripped.index("]")
            self.tag = stripped[1:close].strip().lower()
            remainder = stripped[close + 1 :].lstrip()
            self._pending_lstrip = not remainder
            return self._resolve(remainder)

        if len(stripped) > _MAX_TAG_LEN:
            return self._resolve(self._buffer)

        return ""

    def flush(self) -> str:
        """Emit anything still buffered at the end of the stream."""
        return "" if self._resolved else self._resolve(self._buffer)

    def _resolve(self, text: str) -> str:
        self._resolved = True
        self._buffer = ""
        return text
