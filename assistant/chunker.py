"""Split a stream of text deltas into speakable chunks.

This is the main latency lever in the voice pipeline. Waiting for the model to
finish before synthesising anything costs a second or more of dead air; emitting
the first speakable fragment the moment it exists hides almost all of it.

The first chunk is cut aggressively short — time-to-first-sound dominates how
responsive she feels. Later chunks are allowed to grow, because a TTS engine
given a whole sentence produces better prosody than one fed clauses.
"""

from __future__ import annotations

import re

SENTENCE_END = ".!?…"
CLAUSE_END = ",;:—–"

# A period after one of these is an abbreviation, not a sentence boundary.
#
# Kept deliberately conservative, and excluding anything that is also a common
# word — "no." and "am." would swallow far more real sentence endings than the
# rare "No. 5" or "9 a.m." they'd catch. The asymmetry matters: a missed split
# only makes one chunk longer, while a wrong split makes her pause mid-sentence.
# ("a.m." is handled anyway — a single letter before the period reads as an
# initial, the same rule that protects "J. R. R.")
ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "vs",
    "etc", "eg", "ie", "approx", "dept", "est", "fig", "al",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
}

_WORD_BEFORE = re.compile(r"([A-Za-z]+)\.?$")


class SentenceChunker:
    def __init__(
        self,
        first_chunk_chars: int = 50,
        target_chars: int = 180,
        max_chars: int = 320,
        min_chars: int = 8,
    ) -> None:
        """
        first_chunk_chars: soft cap before the first chunk is forced out.
        target_chars:      soft cap for later chunks — beyond this, a comma will do.
        max_chars:         hard cap — cut at whitespace rather than run on forever.
        min_chars:         floor on chunk length. Runs of very short sentences
                           ("Yes. No. Fine.") are merged up to this rather than
                           sent one at a time, which would stutter.
        """
        self.first_chunk_chars = first_chunk_chars
        self.target_chars = target_chars
        self.max_chars = max_chars
        self.min_chars = min_chars
        self._buffer = ""
        self._emitted = 0

    @property
    def _soft_cap(self) -> int:
        return self.first_chunk_chars if self._emitted == 0 else self.target_chars

    def feed(self, text: str) -> list[str]:
        """Consume a delta; return zero or more chunks ready to synthesise."""
        self._buffer += text
        chunks: list[str] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            chunk, self._buffer = self._buffer[:cut].strip(), self._buffer[cut:].lstrip()
            if chunk:
                chunks.append(chunk)
                self._emitted += 1
        return chunks

    def flush(self) -> str | None:
        """Emit whatever is left at the end of the stream."""
        remaining, self._buffer = self._buffer.strip(), ""
        if remaining:
            self._emitted += 1
        return remaining or None

    # ------------------------------------------------------------------ cuts

    def _find_cut(self) -> int | None:
        buf = self._buffer

        # Preferred: a real sentence boundary at or past the minimum length.
        end = self._sentence_end(buf)
        if end is not None:
            return end

        # Long enough that waiting for a full stop would cost noticeable delay —
        # a clause boundary is a natural enough place for a breath.
        if len(buf) >= self._soft_cap:
            clause = self._clause_end(buf)
            if clause is not None and clause >= self.min_chars:
                return clause

        # Nothing punctuated in sight; cut at whitespace rather than run on.
        if len(buf) >= self.max_chars:
            space = buf.rfind(" ", self.min_chars, self.max_chars)
            return space + 1 if space > 0 else self.max_chars

        return None

    def _sentence_end(self, buf: str) -> int | None:
        """First sentence boundary whose cut lands at or past `min_chars`.

        Earlier boundaries are skipped rather than rejected, so a run of terse
        sentences merges into one chunk instead of being dropped on the floor.
        """
        for i, ch in enumerate(buf):
            if ch not in SENTENCE_END:
                continue
            # Consume runs ("...", "?!") and any closing quote or bracket.
            j = i
            while j + 1 < len(buf) and buf[j + 1] in SENTENCE_END:
                j += 1
            while j + 1 < len(buf) and buf[j + 1] in "\"')]}»”’":
                j += 1
            # Only a boundary once we've seen what follows — otherwise a period
            # arriving at the end of a delta looks like a sentence end when it
            # is really mid-word ("Dr" + ". Smith").
            if j + 1 >= len(buf):
                return None
            if not buf[j + 1].isspace():
                continue
            if ch == "." and self._is_abbreviation(buf[: i + 1]):
                continue
            cut = j + 2  # include the terminator and the space
            if cut < self.min_chars:
                continue  # too short to speak alone — merge with what follows
            return cut

        return None

    def _is_abbreviation(self, upto: str) -> bool:
        """True when the period ending `upto` is part of a word, not a sentence."""
        stem = upto[:-1]
        # Decimals and version numbers: 3.14, 1.2
        if stem and stem[-1].isdigit():
            return True
        match = _WORD_BEFORE.search(stem)
        if not match:
            return False
        word = match.group(1)
        # Single letters are initials — "J. R. R. Tolkien"
        return len(word) == 1 or word.lower() in ABBREVIATIONS

    def _clause_end(self, buf: str) -> int | None:
        limit = min(len(buf), self.max_chars)
        for i in range(limit - 1, self.min_chars - 1, -1):
            if buf[i] in CLAUSE_END and i + 1 < len(buf) and buf[i + 1].isspace():
                return i + 2
        return None
