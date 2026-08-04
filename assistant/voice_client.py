"""Desktop voice client.

Phase 2, so input is still typed — the microphone arrives in phase 3. What this
proves out is the half that's harder to get right: audio arriving in pieces
while the model is still writing, and playing continuously without gaps.

Playback falls back to a WAV file when there's no audio device, which keeps the
client usable over SSH and in containers, and is genuinely the easier way to
debug how a chunk actually sounds.
"""

from __future__ import annotations

import asyncio
import json
from base64 import b64decode, b64encode
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

import httpx

from .tts.base import AudioFormat, wav_header


class Player(Protocol):
    def start(self, fmt: AudioFormat) -> None: ...
    def write(self, pcm: bytes) -> None: ...
    def stop(self) -> str | None:
        """Finish playback; returns a note to show the user, if any."""
        ...

    def cancel(self) -> None:
        """Stop immediately, discarding audio already queued.

        Barge-in needs this: stopping the *feed* isn't enough when a second of
        speech is already sitting in the device buffer. She has to go quiet the
        moment you start talking, not when the buffer drains.
        """
        ...


class SoundDevicePlayer:
    """Streams to the speakers. Blocking writes, so drive it from a thread."""

    def __init__(self) -> None:
        self._stream: Any = None

    @staticmethod
    def available() -> bool:
        try:
            import sounddevice

            return bool(sounddevice.query_devices(kind="output"))
        except Exception:
            return False

    def start(self, fmt: AudioFormat) -> None:
        import sounddevice

        self._stream = sounddevice.RawOutputStream(
            samplerate=fmt.sample_rate, channels=fmt.channels, dtype="int16"
        )
        self._stream.start()

    def write(self, pcm: bytes) -> None:
        if self._stream is not None:
            self._stream.write(pcm)

    def stop(self) -> str | None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        return None

    def cancel(self) -> None:
        # abort() drops the buffered audio; stop() would play it out first.
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None


class WavFilePlayer:
    """Collects audio and writes a WAV file. Used when there's no output device."""

    def __init__(self, directory: str | Path = "audio") -> None:
        self.directory = Path(directory)
        self._fmt: AudioFormat | None = None
        self._pcm = bytearray()

    def start(self, fmt: AudioFormat) -> None:
        self._fmt = fmt
        self._pcm = bytearray()

    def write(self, pcm: bytes) -> None:
        self._pcm += pcm

    def stop(self) -> str | None:
        if not self._pcm or self._fmt is None:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{datetime.now():%Y%m%d-%H%M%S}.wav"
        path.write_bytes(wav_header(self._fmt, len(self._pcm)) + bytes(self._pcm))
        seconds = self._fmt.duration(bytes(self._pcm))
        self._pcm = bytearray()
        return f"{path} ({seconds:.1f}s)"

    def cancel(self) -> None:
        self._pcm = bytearray()


def default_player() -> tuple[Player, str | None]:
    """Speakers when there are any, a WAV file otherwise."""
    if SoundDevicePlayer.available():
        return SoundDevicePlayer(), None
    return (
        WavFilePlayer(),
        "no audio output device — writing WAV files to audio/ instead",
    )


class VoiceClient:
    def __init__(self, server_url: str, token: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.token = token

    async def stream_turn(
        self, client: httpx.AsyncClient, session_id: str, message: str, regenerate: bool = False
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded events for one turn; `audio` events carry raw PCM."""
        async with client.stream(
            "POST",
            f"{self.server_url}/chat/voice",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"session_id": session_id, "message": message, "regenerate": regenerate},
            timeout=httpx.Timeout(300.0, connect=10.0),
        ) as response:
            if response.status_code != 200:
                await response.aread()
                yield {
                    "type": "error",
                    "message": f"server returned {response.status_code}",
                }
                return

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") == "audio":
                    event = {"type": "audio", "pcm": b64decode(event["pcm"])}
                yield event

    async def stream_converse(
        self, client: httpx.AsyncClient, session_id: str, pcm: bytes
    ) -> AsyncIterator[dict[str, Any]]:
        """Send a captured utterance; yield transcript, then the spoken reply."""
        async with client.stream(
            "POST",
            f"{self.server_url}/converse",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"session_id": session_id, "audio": b64encode(pcm).decode()},
            timeout=httpx.Timeout(300.0, connect=10.0),
        ) as response:
            if response.status_code != 200:
                await response.aread()
                yield {"type": "error", "message": f"server returned {response.status_code}"}
                return

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") == "audio":
                    event = {"type": "audio", "pcm": b64decode(event["pcm"])}
                yield event

    async def say(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        message: str,
        player: Player,
        on_text: Any = None,
        regenerate: bool = False,
    ) -> dict[str, Any]:
        """Run one turn: play the audio, surface the text. Returns the last event."""
        started = False
        last: dict[str, Any] = {"type": "error", "message": "no response"}

        try:
            async for event in self.stream_turn(client, session_id, message, regenerate):
                kind = event["type"]
                if kind == "start":
                    player.start(AudioFormat(**event["format"]))
                    started = True
                elif kind == "audio":
                    # Blocking write — off the loop so events keep arriving.
                    await asyncio.to_thread(player.write, event["pcm"])
                elif kind == "text" and on_text:
                    on_text(event["text"])
                elif kind in ("done", "error"):
                    last = event
        finally:
            if started:
                note = await asyncio.to_thread(player.stop)
                if note:
                    last = {**last, "audio_note": note}
        return last
