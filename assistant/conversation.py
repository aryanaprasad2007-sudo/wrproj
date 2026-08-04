"""The spoken conversation loop.

Listening never stops. A single task reads the microphone and feeds the
segmenter for the whole session, including while she is talking — that is what
makes barge-in possible. Speaking and listening are not modes.

When speech is detected mid-reply the loop cancels playback immediately and
drops the rest of the response. The interrupting utterance then arrives on the
same queue as any other and is answered normally, so interrupting her is not a
special case; it is just the next thing you said.

Voice activity detection stays on this side deliberately. Barge-in is judged in
tens of milliseconds and cannot afford a round trip to the service.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Protocol

import httpx

from .audio.vad import Segmenter
from .avatar import AvatarLink
from .tts.base import AudioFormat
from .voice_client import Player, VoiceClient

Event = dict[str, Any]
OnEvent = Callable[[Event], None]


class FrameSource(Protocol):
    """Anything that produces fixed-size PCM frames — a mic, or a test fixture."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def frames(self) -> AsyncIterator[bytes]: ...


class Conversation:
    def __init__(
        self,
        client: VoiceClient,
        source: FrameSource,
        segmenter: Segmenter,
        player: Player,
        session_id: str = "voice",
        barge_in: bool = True,
        avatar: AvatarLink | None = None,
    ) -> None:
        self.client = client
        self.source = source
        self.segmenter = segmenter
        self.player = player
        self.session_id = session_id
        self.barge_in = barge_in
        self.avatar = avatar

        self._events: asyncio.Queue[Event] = asyncio.Queue()
        self._interrupted = asyncio.Event()
        self._speaking = False
        self._stop = asyncio.Event()

    # ------------------------------------------------------------- listening

    async def _listen(self) -> None:
        """Read frames forever, turning them into segmenter events."""
        async for frame in self.source.frames():
            for event in self.segmenter.feed(frame):
                if event["type"] == "speech_start":
                    # Only meaningful while she's talking; otherwise it's just
                    # the normal start of a turn and the utterance says it all.
                    if self._speaking and self.barge_in:
                        self._interrupted.set()
                    continue
                await self._events.put(event)

        tail = self.segmenter.flush()
        if tail:
            await self._events.put(tail)
        self._stop.set()

    # -------------------------------------------------------------- speaking

    async def _play_reply(self, pcm: bytes, on_event: OnEvent | None) -> Event:
        """Stream one turn into the player. Cancelled on barge-in."""
        started = False
        last: Event = {"type": "error", "message": "no response"}
        try:
            async for event in self.client.stream_converse(
                self._http, self.session_id, pcm
            ):
                if on_event:
                    on_event(event)
                kind = event["type"]
                if kind == "start":
                    fmt = AudioFormat(**event["format"])
                    self.player.start(fmt)
                    if self.avatar:
                        self.avatar.start(fmt)
                    started = True
                elif kind == "audio":
                    if self.avatar:
                        self.avatar.feed(event["pcm"])
                    await asyncio.to_thread(self.player.write, event["pcm"])
                elif kind in ("done", "error"):
                    last = event
        finally:
            if started and not self._interrupted.is_set():
                note = await asyncio.to_thread(self.player.stop)
                if self.avatar:
                    self.avatar.stop()
                if note:
                    last = {**last, "audio_note": note}
        return last

    async def _respond(self, pcm: bytes, on_event: OnEvent | None) -> Event:
        self._speaking = True
        self._interrupted.clear()

        reply = asyncio.create_task(self._play_reply(pcm, on_event))
        watch = asyncio.create_task(self._interrupted.wait())
        try:
            done, _ = await asyncio.wait(
                {reply, watch}, return_when=asyncio.FIRST_COMPLETED
            )
            if watch in done:
                # Kill the audio first — the user is already talking over her,
                # and draining the device buffer would keep her going.
                await asyncio.to_thread(self.player.cancel)
                if self.avatar:
                    self.avatar.cancel()
                reply.cancel()
                try:
                    await reply
                except asyncio.CancelledError:
                    pass
                return {"type": "interrupted"}
            return reply.result()
        finally:
            watch.cancel()
            self._speaking = False

    # ------------------------------------------------------------------- run

    async def run(self, http: httpx.AsyncClient, on_event: OnEvent | None = None) -> None:
        self._http = http
        self.source.start()
        listener = asyncio.create_task(self._listen())
        try:
            while not self._stop.is_set() or not self._events.empty():
                getter = asyncio.create_task(self._events.get())
                stopper = asyncio.create_task(self._stop.wait())
                done, _ = await asyncio.wait(
                    {getter, stopper}, return_when=asyncio.FIRST_COMPLETED
                )
                stopper.cancel()
                if getter not in done:
                    getter.cancel()
                    if self._events.empty():
                        break
                    continue

                event = getter.result()
                if event["type"] != "utterance":
                    continue

                result = await self._respond(event["pcm"], on_event)
                if on_event:
                    on_event(result)
        finally:
            listener.cancel()
            self.source.stop()
            await asyncio.gather(listener, return_exceptions=True)
