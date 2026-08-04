"""Voice activity detection and utterance segmentation.

The segmenter is a pure state machine over fixed-size frames: no microphone, no
threads, no I/O. That keeps the part with actual judgement in it — when has
someone started talking, when have they stopped — testable without hardware.

Two details matter more than the detector itself:

*Pre-roll.* Speech is only confirmed a few frames after it starts, so the buffer
keeps a rolling window of audio from before that point. Without it the first
syllable is missing from every utterance, which reads as a bad transcript rather
than a bad capture.

*End-of-speech silence.* This is the single biggest latency lever in the whole
pipeline — it is dead time added to every turn, after the user has stopped
speaking and before anything starts happening. Too short and it cuts people off
mid-sentence; too long and she feels slow.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

# webrtcvad accepts only 10, 20 or 30ms frames at 8/16/32/48 kHz.
SUPPORTED_RATES = (8000, 16000, 32000, 48000)
SUPPORTED_FRAME_MS = (10, 20, 30)


class VAD(Protocol):
    """A per-frame speech detector. Swappable — Silero would drop in here."""

    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


class WebrtcVAD(VAD):
    """WebRTC's detector: tiny, fast, no model download, CPU-only.

    Aggressiveness 0-3, higher rejects more non-speech. 2 is a reasonable
    default for a quiet room; raise it if background noise keeps triggering her.
    """

    def __init__(self, aggressiveness: int = 2) -> None:
        import webrtcvad

        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return bool(self._vad.is_speech(frame, sample_rate))


@dataclass
class SegmenterConfig:
    sample_rate: int = 16000
    frame_ms: int = 30
    # Consecutive speech frames before we believe it. Debounces keyboard
    # clicks and door bumps, which trip a single frame but never several.
    start_frames: int = 3
    # Silence that ends an utterance. Dead time on every turn — tune it here.
    end_silence_ms: int = 600
    # Audio retained from before speech was confirmed, so the first syllable
    # survives. Must exceed start_frames * frame_ms or you clip every word.
    pre_roll_ms: int = 300
    # Anything shorter is a cough or a chair, not a sentence.
    min_utterance_ms: int = 250
    max_utterance_ms: int = 30_000

    def __post_init__(self) -> None:
        if self.sample_rate not in SUPPORTED_RATES:
            raise ValueError(f"sample_rate must be one of {SUPPORTED_RATES}")
        if self.frame_ms not in SUPPORTED_FRAME_MS:
            raise ValueError(f"frame_ms must be one of {SUPPORTED_FRAME_MS}")
        if self.pre_roll_ms < self.start_frames * self.frame_ms:
            raise ValueError(
                "pre_roll_ms must cover start_frames or the first syllable is lost"
            )

    @property
    def frame_bytes(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000) * 2  # 16-bit mono

    @property
    def pre_roll_frames(self) -> int:
        return max(1, self.pre_roll_ms // self.frame_ms)

    @property
    def end_silence_frames(self) -> int:
        return max(1, self.end_silence_ms // self.frame_ms)

    @property
    def max_frames(self) -> int:
        return max(1, self.max_utterance_ms // self.frame_ms)


class Segmenter:
    """Frames in, utterances out.

    Emits `speech_start` the moment speech is confirmed — that is the barge-in
    signal, and it has to fire while the user is still talking, not when they
    finish. Then `utterance` with the captured audio once they stop.
    """

    def __init__(self, vad: VAD, config: SegmenterConfig | None = None) -> None:
        self.vad = vad
        self.config = config or SegmenterConfig()
        self._pre_roll: deque[bytes] = deque(maxlen=self.config.pre_roll_frames)
        self._frames: list[bytes] = []
        self._speech_run = 0
        self._silence_run = 0
        self._active = False

    @property
    def active(self) -> bool:
        """True while the user is mid-utterance."""
        return self._active

    def reset(self) -> None:
        self._pre_roll.clear()
        self._frames.clear()
        self._speech_run = self._silence_run = 0
        self._active = False

    def feed(self, frame: bytes) -> list[dict[str, Any]]:
        cfg = self.config
        if len(frame) != cfg.frame_bytes:
            raise ValueError(
                f"expected {cfg.frame_bytes}-byte frames "
                f"({cfg.frame_ms}ms @ {cfg.sample_rate}Hz), got {len(frame)}"
            )

        speech = self.vad.is_speech(frame, cfg.sample_rate)
        events: list[dict[str, Any]] = []

        if not self._active:
            self._pre_roll.append(frame)
            self._speech_run = self._speech_run + 1 if speech else 0
            if self._speech_run >= cfg.start_frames:
                self._active = True
                self._silence_run = 0
                # Seed from the rolling window, not from this frame, so the
                # attack of the first word is included.
                self._frames = list(self._pre_roll)
                self._pre_roll.clear()
                events.append({"type": "speech_start"})
            return events

        self._frames.append(frame)
        self._silence_run = 0 if speech else self._silence_run + 1

        if self._silence_run >= cfg.end_silence_frames:
            events.append(self._finish(trim_silence=True))
        elif len(self._frames) >= cfg.max_frames:
            events.append(self._finish(trim_silence=False, reason="max_length"))

        return [e for e in events if e]

    def flush(self) -> dict[str, Any] | None:
        """End an in-progress utterance — used when the stream stops."""
        return self._finish(trim_silence=True) if self._active else None

    # ------------------------------------------------------------------ inner

    def _finish(self, trim_silence: bool, reason: str = "silence") -> dict[str, Any] | None:
        cfg = self.config
        frames = self._frames
        if trim_silence and self._silence_run > 1:
            # Leave one frame of silence: a hard cut on the final consonant
            # sounds clipped to the recogniser as well as to a listener.
            frames = frames[: len(frames) - self._silence_run + 1]

        pcm = b"".join(frames)
        duration_ms = len(frames) * cfg.frame_ms

        self._frames = []
        self._speech_run = self._silence_run = 0
        self._active = False
        self._pre_roll.clear()

        if duration_ms < cfg.min_utterance_ms:
            return None  # a cough, not a sentence
        return {"type": "utterance", "pcm": pcm, "ms": duration_ms, "reason": reason}


def frames_of(pcm: bytes, frame_bytes: int) -> list[bytes]:
    """Split PCM into whole frames, discarding any trailing partial frame."""
    count = len(pcm) // frame_bytes
    return [pcm[i * frame_bytes : (i + 1) * frame_bytes] for i in range(count)]
