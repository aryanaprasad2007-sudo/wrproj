"""An engine that makes sound without being speech.

Exists so the whole pipeline — chunking, streaming, playback — runs and can be
tested with no model download, no API key and no network. It emits soft tones
rather than words, deliberately: nobody should be able to mistake this for
working TTS, and a silent stub would hide bugs that a listener would catch.

It is also the default, so `git clone && python run_voice.py` produces audio.
"""

from __future__ import annotations

import math
import struct
from typing import AsyncIterator

from .base import AudioFormat, TTSEngine

# Roughly conversational pace, used to size each chunk's audio.
CHARS_PER_SECOND = 14.0
# A low, unobtrusive pair of pitches — audibly "not speech".
PITCHES = (196.0, 261.6)


class ToneEngine(TTSEngine):
    name = "tone"

    def __init__(self, sample_rate: int = 22050, speed: float = 1.0) -> None:
        self._format = AudioFormat(sample_rate=sample_rate)
        self.speed = max(0.25, speed)
        self._n = 0

    @property
    def format(self) -> AudioFormat:
        return self._format

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        seconds = max(0.25, len(text) / (CHARS_PER_SECOND * self.speed))
        pitch = PITCHES[self._n % len(PITCHES)]
        self._n += 1

        rate = self._format.sample_rate
        total = int(seconds * rate)
        # Yield in ~100ms frames so callers exercise the streaming path rather
        # than receiving one monolithic buffer.
        frame = max(1, rate // 10)

        for start in range(0, total, frame):
            count = min(frame, total - start)
            samples = bytearray()
            for i in range(start, start + count):
                # Fade the edges, otherwise each chunk starts and ends in a click.
                env = min(1.0, i / (rate * 0.02), (total - i) / (rate * 0.02))
                value = math.sin(2 * math.pi * pitch * (i / rate)) * 0.2 * env
                samples += struct.pack("<h", int(value * 32767))
            yield bytes(samples)

    async def aclose(self) -> None:
        return None
