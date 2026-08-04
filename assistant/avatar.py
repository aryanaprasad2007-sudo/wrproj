"""What a face needs to know, and how it finds out.

The character itself is still open, so nothing here draws anything. This is the
feed a face subscribes to: which expression she's wearing, whether she's
speaking, what she's saying, and how far her mouth is open at each moment.

Two decisions worth spelling out, because they're the ones that constrain what
can be plugged in later.

*Amplitude, not visemes.* Phoneme-accurate mouth shapes need forced alignment
against the audio and a phoneme set that depends on both the TTS engine and the
rig — neither of which is chosen yet. An openness curve drives the one parameter
every rig already has (Live2D's ParamMouthOpenY, VRM's `A` blendshape, VTube
Studio's MouthOpen), so any of them can be wired up now and upgraded to real
visemes later without touching the transport.

*The mouth is published by whoever plays the audio*, never by whoever
synthesises it. Synthesis runs far ahead of playback — that's the whole point of
streaming it — so publishing at the source would put her mouth seconds ahead of
her voice. Expression and state come from the engine instead, where being a few
hundred milliseconds early is invisible.
"""

from __future__ import annotations

import array
import asyncio
import math
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from .tts.base import AudioFormat

Event = dict[str, Any]

# 25fps. Matches ordinary render rates, and is already finer than a jaw moves.
FRAME_MS = 40

_FULL_SCALE = 32768.0


@dataclass(frozen=True)
class EnvelopeConfig:
    frame_ms: int = FRAME_MS
    # Below this, treat the frame as silence and shut the mouth. Low enough to
    # keep engine hiss and room tone out without clipping quiet consonants.
    floor_db: float = -48.0
    # Assumed speech-to-floor range before we've heard anything loud.
    initial_span_db: float = 24.0
    # How fast the loudness ceiling falls, per voiced frame.
    decay_db: float = 0.25
    # A jaw opens faster than it closes; equal rates read as chattering.
    attack: float = 0.7
    release: float = 0.3


class MouthEnvelope:
    """Turns streamed PCM into a mouth-openness curve, one value per frame.

    Levels are normalised against a decaying ceiling rather than against full
    scale, because TTS engines differ by tens of dB and the same absolute level
    can be a shout from one and a mumble from the next. What matters visually is
    loud *relative to how loud she's been*, which is what this measures.
    """

    def __init__(self, fmt: AudioFormat, config: EnvelopeConfig | None = None) -> None:
        if fmt.sample_width != 2:
            raise ValueError("mouth envelope expects 16-bit PCM")
        self.format = fmt
        self.config = config or EnvelopeConfig()
        self.frame_bytes = (
            max(1, round(fmt.sample_rate * self.config.frame_ms / 1000))
            * fmt.sample_width
            * fmt.channels
        )
        self._buffer = bytearray()
        self._ceiling = self.config.floor_db + self.config.initial_span_db
        self._open = 0.0

    @property
    def frame_ms(self) -> int:
        return self.config.frame_ms

    def feed(self, pcm: bytes) -> list[float]:
        """Consume audio; return openness for every *whole* frame it completed."""
        self._buffer += pcm
        out: list[float] = []
        while len(self._buffer) >= self.frame_bytes:
            frame = bytes(self._buffer[: self.frame_bytes])
            del self._buffer[: self.frame_bytes]
            out.append(self._step(_rms(frame)))
        return out

    def flush(self) -> list[float]:
        """End of utterance: drain the partial frame, then close the mouth.

        The explicit zero matters — without it she's left frozen mid-vowel on
        whatever the last frame happened to be.
        """
        out: list[float] = []
        if len(self._buffer) >= self.frame_bytes // 2:
            out.append(self._step(_rms(bytes(self._buffer))))
        self._buffer.clear()
        self._open = 0.0
        out.append(0.0)
        return out

    def reset(self) -> None:
        self._buffer.clear()
        self._ceiling = self.config.floor_db + self.config.initial_span_db
        self._open = 0.0

    def _step(self, rms: float) -> float:
        config = self.config
        level = rms / _FULL_SCALE
        db = 20.0 * math.log10(level) if level > 1e-6 else -120.0

        if db <= config.floor_db:
            target = 0.0
        else:
            # Only voiced frames move the ceiling. Decaying through silence
            # would collapse it, and the first word back would read as a shout.
            self._ceiling = max(db, self._ceiling - config.decay_db)
            span = max(self._ceiling - config.floor_db, 6.0)
            target = min((db - config.floor_db) / span, 1.0)

        rate = config.attack if target > self._open else config.release
        self._open += (target - self._open) * rate
        return round(self._open, 3)


def _rms(frame: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class AvatarBus:
    """Fan-out to whatever faces are watching. Usually none, sometimes one.

    `publish` never blocks and never raises. A face that can't keep up loses
    frames; it must not be able to stall the voice, and a rendering bug on the
    other end of a socket must not take a conversation down.
    """

    def __init__(self, maxsize: int = 64) -> None:
        self.maxsize = maxsize
        self.dropped = 0
        self._queues: set[asyncio.Queue[Event]] = set()

    @property
    def listeners(self) -> int:
        return len(self._queues)

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self.maxsize)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    def publish(self, event: Event) -> None:
        for queue in tuple(self._queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the oldest: a stale mouth frame is worse than no frame.
                self.dropped += 1
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


# Merged mouth batches are capped here: ~16 seconds of curve, which is longer
# than any single reply's backlog and keeps a stalled sender's memory bounded.
MAX_MERGED_FRAMES = 400


class AvatarLink:
    """Client-side half: reports playback to the service, which fans it out.

    Sends are buffered and drained by a background task, so a slow or dead
    service can never stutter the audio. Every method here is synchronous and
    safe to call from the playback path.

    When the buffer backs up, consecutive mouth batches are *merged* rather than
    dropped. They describe contiguous audio, so merging costs a little latency
    while dropping would tear a hole in the middle of a sentence — and the hole
    is what you'd see.
    """

    def __init__(
        self,
        server_url: str,
        token: str,
        http: httpx.AsyncClient,
        maxsize: int = 32,
    ) -> None:
        self.url = f"{server_url.rstrip('/')}/avatar/publish"
        self.token = token
        self.http = http
        self.maxsize = maxsize
        self._pending: deque[Event] = deque()
        self._wake = asyncio.Event()
        self._flushed = asyncio.Event()
        self._flushed.set()
        self._task: asyncio.Task[None] | None = None
        self._envelope: MouthEnvelope | None = None
        # How many faces the service last said were watching. Starts optimistic
        # on purpose: the count is only learned from a reply, and assuming zero
        # would leave the first utterance after a face connects unanimated. A
        # couple of wasted posts to loopback is the cheaper mistake.
        self._listeners = 1

    async def __aenter__(self) -> AvatarLink:
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._task is not None:
            # The last thing queued is almost always the `idle` that puts her
            # face back. Nothing awaits between `stop()` and here, so cancelling
            # straight away drops it and leaves her mid-word until the viewer's
            # watchdog notices.
            try:
                await asyncio.wait_for(self._flushed.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    # ----------------------------------------------------------- playback

    def start(self, fmt: AudioFormat) -> None:
        try:
            self._envelope = MouthEnvelope(fmt)
        except ValueError:
            self._envelope = None  # not 16-bit; expression still works
        self._send({"type": "state", "state": "speaking"})

    def feed(self, pcm: bytes) -> None:
        """Call immediately *before* handing this audio to the device.

        Playing a chunk blocks for its own duration, so the moment before the
        write is the moment playback of that chunk begins — which is exactly
        when the face should start animating it.
        """
        if self._envelope is None:
            return
        # Always analysed, even with nobody watching: the envelope carries a
        # partial frame between calls, so skipping the work would shorten the
        # curve and she'd stop moving her mouth before she stopped talking.
        # Only the sending is skipped, which is where the cost actually is.
        frames = self._envelope.feed(pcm)
        if frames and self._listeners:
            self._mouth(frames)

    def stop(self) -> None:
        if self._envelope is not None:
            frames = self._envelope.flush()
            if self._listeners:
                self._mouth(frames)
            self._envelope.reset()
        self._send({"type": "state", "state": "idle"})

    def cancel(self) -> None:
        """Barge-in: shut her mouth now, don't play out what's queued."""
        if self._envelope is not None:
            self._envelope.reset()
        if self._listeners:
            self._mouth([0.0])
        self._send({"type": "state", "state": "idle"})

    # ------------------------------------------------------------ plumbing

    def _mouth(self, frames: list[float]) -> None:
        self._send(
            {
                "type": "mouth",
                "frame_ms": self._envelope.frame_ms if self._envelope else FRAME_MS,
                "open": frames,
            }
        )

    def _send(self, event: Event) -> None:
        if event["type"] == "mouth" and self._merge(event):
            return
        self._pending.append(event)
        while len(self._pending) > self.maxsize:
            self._pending.popleft()
        self._flushed.clear()
        self._wake.set()

    def _merge(self, event: Event) -> bool:
        """Fold a mouth batch into the one already waiting, if there is one."""
        if not self._pending:
            return False
        last = self._pending[-1]
        if last["type"] != "mouth" or last["frame_ms"] != event["frame_ms"]:
            return False
        if len(last["open"]) + len(event["open"]) > MAX_MERGED_FRAMES:
            return False
        last["open"].extend(event["open"])
        self._flushed.clear()
        self._wake.set()
        return True

    async def _run(self) -> None:
        headers = {"Authorization": f"Bearer {self.token}"}
        while True:
            if not self._pending:
                self._flushed.set()
                self._wake.clear()
                await self._wake.wait()
                continue
            event = self._pending.popleft()
            try:
                response = await self.http.post(
                    self.url, json=event, headers=headers, timeout=2.0
                )
                if response.status_code == 200:
                    self._listeners = response.json().get("listeners", 0)
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError):
                pass  # the face is optional; the conversation is not
