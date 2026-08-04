import asyncio
import threading

import httpx
import pytest

from assistant.audio.vad import Segmenter, SegmenterConfig
from assistant.conversation import Conversation
from assistant.server import create_app
from assistant.stt.base import EchoEngine
from assistant.tts.base import AudioFormat
from assistant.voice_client import VoiceClient
from conftest import FakeAPI, PERSONA

TOKEN = "test-token"
CFG = SegmenterConfig(
    sample_rate=16000, frame_ms=30, start_frames=3,
    end_silence_ms=300, pre_roll_ms=150, min_utterance_ms=0,
)


class ScriptedVAD:
    def __init__(self, script: str) -> None:
        self.script, self.i = script, 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        ch = self.script[self.i] if self.i < len(self.script) else "."
        self.i += 1
        return ch == "S"


class FakeMic:
    """Frames on demand. What each frame *is* comes from the scripted VAD."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.started = self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self.queue.put_nowait(None)

    async def frames(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    def push(self, count: int) -> None:
        for _ in range(count):
            self.queue.put_nowait(b"\x00" * CFG.frame_bytes)


class RecordingPlayer:
    """Captures calls; optionally blocks on write to mimic real-time playback."""

    def __init__(self, block: bool = False) -> None:
        self.calls: list[str] = []
        self.pcm = bytearray()
        self.first_write = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()

    def start(self, fmt: AudioFormat) -> None:
        self.calls.append("start")
        self.fmt = fmt

    def write(self, pcm: bytes) -> None:
        self.calls.append("write")
        self.pcm += pcm
        self.first_write.set()
        self.release.wait(timeout=5)

    def stop(self) -> str | None:
        self.calls.append("stop")
        return None

    def cancel(self) -> None:
        self.calls.append("cancel")
        self.pcm = bytearray()
        self.release.set()


@pytest.fixture
async def app(api: FakeAPI, store):
    from assistant.engine import Assistant

    engine = Assistant(
        PERSONA, store=store, client=api.client(), stt=EchoEngine("what was that reminder")
    )
    application = create_app(token=TOKEN, engine=engine)
    async with application.router.lifespan_context(application):
        yield application


async def drive(app, mic, segmenter, player, events, barge_in=True, avatar=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        convo = Conversation(
            VoiceClient("http://test", TOKEN),
            mic,
            segmenter,
            player,
            barge_in=barge_in,
            avatar=avatar,
        )
        await convo.run(http, on_event=events.append)


# ------------------------------------------------------------- ordinary turn


async def test_an_utterance_produces_a_transcript_and_a_spoken_reply(
    app, api: FakeAPI
) -> None:
    api.queue_reply(["[bored] The dentist. Tuesday at ten."])
    mic, player, events = FakeMic(), RecordingPlayer(), []
    segmenter = Segmenter(ScriptedVAD("..SSSSSS" + "." * 12), CFG)

    mic.push(20)
    mic.stop()
    await drive(app, mic, segmenter, player, events)

    kinds = [e["type"] for e in events]
    assert "transcript" in kinds and "text" in kinds and "audio" in kinds
    transcript = next(e for e in events if e["type"] == "transcript")
    assert transcript["text"] == "what was that reminder"
    assert player.calls[0] == "start" and "write" in player.calls
    assert player.pcm


async def test_silence_never_reaches_the_model(app, api: FakeAPI) -> None:
    mic, player, events = FakeMic(), RecordingPlayer(), []
    segmenter = Segmenter(ScriptedVAD("." * 30), CFG)

    mic.push(30)
    mic.stop()
    await drive(app, mic, segmenter, player, events)

    assert events == []
    assert api.requests == [], "a silent room must not cost an API call"


async def test_an_unrecognised_noise_is_skipped(app, api: FakeAPI, store) -> None:
    """Empty transcript means don't answer — replying to noise is worse."""
    from assistant.engine import Assistant

    engine = Assistant(PERSONA, store=store, client=api.client(), stt=EchoEngine(""))
    application = create_app(token=TOKEN, engine=engine)

    mic, player, events = FakeMic(), RecordingPlayer(), []
    segmenter = Segmenter(ScriptedVAD("..SSSSSS" + "." * 12), CFG)
    mic.push(20)
    mic.stop()

    async with application.router.lifespan_context(application):
        await drive(application, mic, segmenter, player, events)

    assert any(e.get("skipped") for e in events)
    assert api.requests == []
    assert "start" not in player.calls


async def test_two_turns_in_one_session(app, api: FakeAPI) -> None:
    api.queue_reply(["[neutral] First."])
    api.queue_reply(["[neutral] Second."])
    mic, player, events = FakeMic(), RecordingPlayer(), []
    segmenter = Segmenter(
        ScriptedVAD("..SSSSSS" + "." * 12 + "SSSSSS" + "." * 12), CFG
    )

    mic.push(40)
    mic.stop()
    await drive(app, mic, segmenter, player, events)

    assert [e["type"] for e in events].count("transcript") == 2
    assert len(api.requests) == 2


# ------------------------------------------------------------------ barge-in


async def test_speaking_over_her_cuts_the_audio_immediately(app, api: FakeAPI) -> None:
    """The whole point of phase 3: she stops the moment you start talking."""
    api.queue_reply(["[bored] " + "A long reply that keeps going. " * 6])
    api.queue_reply(["[flat] Fine."])  # answers whatever cut her off
    mic, events = FakeMic(), []
    player = RecordingPlayer(block=True)
    segmenter = Segmenter(
        ScriptedVAD("..SSSSSS" + "." * 12 + "SSSSSSSSSS" + "." * 12), CFG
    )

    mic.push(20)  # first utterance

    async def interrupt() -> None:
        # Wait until audio is actually playing, then start talking over it.
        await asyncio.to_thread(player.first_write.wait, 5)
        mic.push(22)
        await asyncio.sleep(0.3)
        mic.stop()

    task = asyncio.create_task(interrupt())
    await drive(app, mic, segmenter, player, events)
    await task

    assert "cancel" in player.calls, "playback must be cancelled, not drained"
    assert any(e["type"] == "interrupted" for e in events)
    # Cancelling has to beat a normal finish, or she talked over the user.
    assert "stop" not in player.calls[: player.calls.index("cancel")]


async def test_cutting_her_off_shuts_the_face_too(app, api: FakeAPI) -> None:
    """Otherwise she goes silent while her mouth keeps moving."""

    class FakeLink:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def start(self, fmt) -> None:
            self.calls.append("start")

        def feed(self, pcm: bytes) -> None:
            self.calls.append("feed")

        def stop(self) -> None:
            self.calls.append("stop")

        def cancel(self) -> None:
            self.calls.append("cancel")

    api.queue_reply(["[bored] " + "A long reply that keeps going. " * 6])
    api.queue_reply(["[flat] Fine."])
    mic, events, link = FakeMic(), [], FakeLink()
    player = RecordingPlayer(block=True)
    segmenter = Segmenter(
        ScriptedVAD("..SSSSSS" + "." * 12 + "SSSSSSSSSS" + "." * 12), CFG
    )

    mic.push(20)

    async def interrupt() -> None:
        await asyncio.to_thread(player.first_write.wait, 5)
        mic.push(22)
        await asyncio.sleep(0.3)
        mic.stop()

    task = asyncio.create_task(interrupt())
    await drive(app, mic, segmenter, player, events, avatar=link)
    await task

    assert "cancel" in link.calls
    assert "stop" not in link.calls[: link.calls.index("cancel")]


async def test_barge_in_can_be_switched_off(app, api: FakeAPI) -> None:
    """Needed on speakers, where the mic hears her own voice."""
    api.queue_reply(["[bored] " + "A long reply that keeps going. " * 6])
    api.queue_reply(["[flat] Fine."])
    mic, events = FakeMic(), []
    player = RecordingPlayer(block=False)
    segmenter = Segmenter(
        ScriptedVAD("..SSSSSS" + "." * 12 + "SSSSSSSSSS" + "." * 12), CFG
    )

    mic.push(42)
    mic.stop()
    await drive(app, mic, segmenter, player, events, barge_in=False)

    assert "cancel" not in player.calls
    assert not any(e["type"] == "interrupted" for e in events)


async def test_the_interrupting_words_become_the_next_turn(app, api: FakeAPI) -> None:
    """Interrupting is not a special case — it's just the next thing you said."""
    api.queue_reply(["[bored] " + "A long reply that keeps going. " * 6])
    api.queue_reply(["[flat] Fine."])
    mic, events = FakeMic(), []
    player = RecordingPlayer(block=True)
    segmenter = Segmenter(
        ScriptedVAD("..SSSSSS" + "." * 12 + "SSSSSSSS" + "." * 12), CFG
    )

    mic.push(20)

    async def interrupt() -> None:
        await asyncio.to_thread(player.first_write.wait, 5)
        mic.push(20)  # speech, then silence — a complete second utterance
        await asyncio.sleep(0.3)
        mic.stop()

    task = asyncio.create_task(interrupt())
    await drive(app, mic, segmenter, player, events)
    await task

    assert [e["type"] for e in events].count("transcript") == 2, (
        "the utterance that interrupted her must be answered like any other"
    )


# -------------------------------------------------------------- housekeeping


async def test_the_microphone_is_always_released(app, api: FakeAPI) -> None:
    mic, player, events = FakeMic(), RecordingPlayer(), []
    segmenter = Segmenter(ScriptedVAD("." * 10), CFG)
    mic.push(10)
    mic.stop()
    await drive(app, mic, segmenter, player, events)
    assert mic.started and mic.stopped


async def test_a_server_error_does_not_kill_the_loop(app, api: FakeAPI) -> None:
    api.queue_status(500)
    api.queue_reply(["[neutral] Recovered."])
    mic, player, events = FakeMic(), RecordingPlayer(), []
    segmenter = Segmenter(
        ScriptedVAD("..SSSSSS" + "." * 12 + "SSSSSS" + "." * 12), CFG
    )

    mic.push(40)
    mic.stop()
    await drive(app, mic, segmenter, player, events)

    assert [e["type"] for e in events].count("transcript") == 2, (
        "one failed turn must not end the conversation"
    )
