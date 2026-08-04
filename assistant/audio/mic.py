"""Microphone capture.

Yields fixed-size frames sized for the VAD. The sounddevice callback runs on a
PortAudio thread, so frames land in a plain queue and the async side pulls from
it — nothing touches the event loop from the audio thread.
"""

from __future__ import annotations

import asyncio
import queue
from typing import Any, AsyncIterator

_SENTINEL = object()


class Microphone:
    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        device: int | str | None = None,
        max_queued_frames: int = 100,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.device = device
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self.frame_bytes = self.frame_samples * 2  # 16-bit mono
        # Bounded: if the consumer stalls, drop the oldest audio rather than
        # grow without limit and then replay a backlog of stale speech.
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max_queued_frames)
        self._stream: Any = None
        self.dropped = 0

    @staticmethod
    def available() -> bool:
        try:
            import sounddevice

            return bool(sounddevice.query_devices(kind="input"))
        except Exception:
            return False

    def _callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            self.dropped += 1

    def start(self) -> None:
        import sounddevice

        self._stream = sounddevice.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_samples,
            channels=1,
            dtype="int16",
            callback=self._callback,
            device=self.device,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue.put_nowait(_SENTINEL)

    async def frames(self) -> AsyncIterator[bytes]:
        """Yield frames until `stop()` is called."""
        while True:
            item = await asyncio.to_thread(self._queue.get)
            if item is _SENTINEL:
                return
            yield item

    def __enter__(self) -> "Microphone":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
