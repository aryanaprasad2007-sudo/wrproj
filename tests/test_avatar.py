"""The face feed: the mouth curve, the bus, the link, and the endpoints."""

from __future__ import annotations

import asyncio
import json
import math
import struct
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from assistant.avatar import AvatarBus, AvatarLink, EnvelopeConfig, MouthEnvelope
from assistant.engine import Assistant
from assistant.server import create_app
from assistant.tts.base import AudioFormat
from conftest import PERSONA, FakeAPI

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
FMT = AudioFormat(sample_rate=16000)


def tone(seconds: float, amplitude: float = 0.5, fmt: AudioFormat = FMT) -> bytes:
    count = int(seconds * fmt.sample_rate)
    return b"".join(
        struct.pack("<h", int(math.sin(2 * math.pi * 220 * i / fmt.sample_rate)
                              * amplitude * 32767))
        for i in range(count)
    )


def silence(seconds: float, fmt: AudioFormat = FMT) -> bytes:
    return b"\x00\x00" * int(seconds * fmt.sample_rate)


# ------------------------------------------------------------ mouth envelope


def test_one_value_per_frame_of_audio() -> None:
    envelope = MouthEnvelope(FMT)
    # 40ms frames: half a second is twelve whole ones and a remainder.
    assert len(envelope.feed(tone(0.5))) == 12


def test_frames_survive_being_split_across_writes() -> None:
    """Audio arrives in TTS-sized chunks, not in frame-sized ones."""
    whole = MouthEnvelope(FMT).feed(tone(0.4))

    piecemeal = MouthEnvelope(FMT)
    pcm = tone(0.4)
    split: list[float] = []
    for start in range(0, len(pcm), 333):  # deliberately not a frame boundary
        split += piecemeal.feed(pcm[start : start + 333])

    assert split == whole


def test_silence_keeps_her_mouth_shut() -> None:
    assert set(MouthEnvelope(FMT).feed(silence(0.5))) == {0.0}


def test_speech_opens_it() -> None:
    frames = MouthEnvelope(FMT).feed(tone(0.5))
    assert max(frames) > 0.5


def test_openness_is_relative_to_how_loud_she_has_been() -> None:
    """TTS engines differ by tens of dB. What matters is loud *for her*."""
    envelope = MouthEnvelope(FMT)
    envelope.feed(tone(0.5, amplitude=0.9))
    # Skip the opening frames: those are her mouth closing from the loud part.
    after_a_shout = max(envelope.feed(tone(0.6, amplitude=0.05))[6:])
    on_its_own = max(MouthEnvelope(FMT).feed(tone(0.6, amplitude=0.05)))

    assert after_a_shout < 0.6, "a mumble after a shout must not read as a shout"
    assert on_its_own > after_a_shout + 0.2, "the same audio, judged against itself"


def test_a_quiet_engine_still_opens_the_mouth() -> None:
    """The same clip, an engine 20dB down: it must not just sit there closed."""
    assert max(MouthEnvelope(FMT).feed(tone(0.6, amplitude=0.05))) > 0.5


def test_flush_closes_the_mouth() -> None:
    envelope = MouthEnvelope(FMT)
    envelope.feed(tone(0.5))
    # Without the explicit zero she's left frozen on whatever vowel came last.
    assert envelope.flush()[-1] == 0.0


def test_flush_drains_a_partial_frame() -> None:
    envelope = MouthEnvelope(FMT)
    assert envelope.feed(tone(0.03)) == []  # less than one frame
    assert len(envelope.flush()) == 2  # the partial, then closed


def test_the_mouth_closes_more_slowly_than_it_opens() -> None:
    """Symmetric rates read as chattering, not talking."""
    config = EnvelopeConfig()
    assert config.release < config.attack


def test_sixteen_bit_is_required() -> None:
    with pytest.raises(ValueError):
        MouthEnvelope(AudioFormat(sample_rate=16000, sample_width=4))


# ---------------------------------------------------------------------- bus


async def test_every_face_gets_every_event() -> None:
    bus = AvatarBus()
    with bus.subscribe() as one, bus.subscribe() as two:
        bus.publish({"type": "tag", "tag": "bored"})
        assert one.get_nowait() == two.get_nowait() == {"type": "tag", "tag": "bored"}


async def test_leaving_unsubscribes() -> None:
    bus = AvatarBus()
    with bus.subscribe():
        assert bus.listeners == 1
    assert bus.listeners == 0


async def test_publishing_to_nobody_is_fine() -> None:
    AvatarBus().publish({"type": "state", "state": "idle"})


async def test_a_slow_face_loses_frames_rather_than_stalling_the_voice() -> None:
    bus = AvatarBus(maxsize=2)
    with bus.subscribe() as queue:
        for n in range(5):
            bus.publish({"type": "mouth", "n": n})

        assert queue.qsize() == 2
        # The newest survive: a stale mouth frame is worse than no frame.
        assert [queue.get_nowait()["n"], queue.get_nowait()["n"]] == [3, 4]
    assert bus.dropped == 3


# --------------------------------------------------------------------- link


class Recorder:
    """Stands in for the service, and counts the faces watching."""

    def __init__(self, listeners: int = 1) -> None:
        self.listeners = listeners
        self.posted: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.posted.append(json.loads(request.read()))
        return httpx.Response(200, json={"listeners": self.listeners})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def types(self) -> list[str]:
        return [event["type"] for event in self.posted]


async def drain(link: AvatarLink) -> None:
    """Let the background sender catch up, including the post in flight."""
    for _ in range(50):
        if not link._pending:
            break
        await asyncio.sleep(0)
    await asyncio.sleep(0.02)


async def test_the_link_reports_speaking_then_idle() -> None:
    recorder = Recorder()
    async with recorder.client() as http, AvatarLink("http://s", TOKEN, http) as link:
        link.start(FMT)
        await drain(link)
        link.stop()
        await drain(link)

    assert recorder.types()[0] == "state"
    assert recorder.posted[0]["state"] == "speaking"
    assert recorder.posted[-1] == {"type": "state", "state": "idle"}


async def test_mouth_frames_are_skipped_when_no_face_is_watching() -> None:
    """The common case. Analysing audio nobody is looking at is pure waste."""
    recorder = Recorder(listeners=0)
    async with recorder.client() as http, AvatarLink("http://s", TOKEN, http) as link:
        link.start(FMT)
        await drain(link)
        link.feed(tone(0.5))
        await drain(link)

    assert "mouth" not in recorder.types()


async def test_skipped_frames_still_advance_the_mouth_clock() -> None:
    """A face that isn't watching must not shift the timeline for one that is.

    Caught in end-to-end verification: skipping the *analysis* rather than just
    the send dropped a quarter of the curve, so she finished moving her mouth
    well before she finished talking.
    """
    audio = tone(0.41)  # ten whole frames and a remainder
    recorder = Recorder(listeners=0)
    async with recorder.client() as http, AvatarLink("http://s", TOKEN, http) as link:
        link.start(FMT)
        await drain(link)  # learns nobody is watching
        link.feed(audio)
        await drain(link)

        assert "mouth" not in recorder.types()
        reference = MouthEnvelope(FMT)
        reference.feed(audio)
        # Same audio consumed either way, so the same partial frame carries over.
        assert len(link._envelope.feed(tone(0.03))) == len(reference.feed(tone(0.03))) == 1


async def test_mouth_frames_flow_once_somebody_is() -> None:
    recorder = Recorder(listeners=1)
    async with recorder.client() as http, AvatarLink("http://s", TOKEN, http) as link:
        link.start(FMT)
        await drain(link)  # learns there's a listener from this response
        link.feed(tone(0.5))
        await drain(link)

    mouth = [e for e in recorder.posted if e["type"] == "mouth"]
    assert mouth and len(mouth[0]["open"]) == 12
    assert mouth[0]["frame_ms"] == 40


async def test_barge_in_shuts_her_mouth_immediately() -> None:
    recorder = Recorder(listeners=1)
    async with recorder.client() as http, AvatarLink("http://s", TOKEN, http) as link:
        link.start(FMT)
        await drain(link)
        link.feed(tone(0.5))
        await drain(link)
        link.cancel()
        await drain(link)

    assert recorder.posted[-2] == {"type": "mouth", "frame_ms": 40, "open": [0.0]}
    assert recorder.posted[-1] == {"type": "state", "state": "idle"}


async def test_closing_the_link_still_delivers_the_last_idle() -> None:
    """Caught in a browser: nothing awaits between the final `stop()` and the
    link closing, so cancelling straight away left her face mid-word."""
    recorder = Recorder()
    async with recorder.client() as http:
        async with AvatarLink("http://s", TOKEN, http) as link:
            link.start(FMT)
            link.feed(tone(0.2))
            link.stop()  # no await after this before the block exits

    assert recorder.posted[-1] == {"type": "state", "state": "idle"}


async def test_a_dead_service_does_not_break_playback() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as http:
        async with AvatarLink("http://s", TOKEN, http) as link:
            link.start(FMT)
            link.feed(tone(0.2))
            link.stop()
            await drain(link)  # must not raise


async def unstarted_link(http: httpx.AsyncClient, **kwargs: Any) -> AvatarLink:
    """A link with no background sender, so the buffer can be inspected."""
    return AvatarLink("http://s", TOKEN, http, **kwargs)


async def test_a_backed_up_buffer_merges_batches_instead_of_dropping() -> None:
    """Mouth batches describe contiguous audio. Dropping one tears a hole in
    the middle of a sentence; merging just delays it slightly."""
    recorder = Recorder()
    async with recorder.client() as http:
        link = await unstarted_link(http, maxsize=4)
        for _ in range(50):
            link._send({"type": "mouth", "frame_ms": 40, "open": [0.1, 0.2]})

        assert len(link._pending) == 1
        assert len(link._pending[0]["open"]) == 100, "not one frame lost"


async def test_merging_stops_at_a_cap_so_a_stall_cannot_eat_memory() -> None:
    recorder = Recorder()
    async with recorder.client() as http:
        link = await unstarted_link(http, maxsize=4)
        for _ in range(300):
            link._send({"type": "mouth", "frame_ms": 40, "open": [0.1, 0.2]})

        assert all(len(e["open"]) <= 400 for e in link._pending)
        assert sum(len(e["open"]) for e in link._pending) == 600


async def test_a_flood_of_state_events_stays_bounded() -> None:
    """Those aren't mergeable, so the buffer has to fall back to dropping."""
    recorder = Recorder()
    async with recorder.client() as http:
        link = await unstarted_link(http, maxsize=4)
        for _ in range(50):
            link._send({"type": "state", "state": "idle"})

        assert len(link._pending) == 4


# ------------------------------------------------------------------- engine


async def bus_events(engine: Assistant, coro: Any) -> list[dict[str, Any]]:
    with engine.avatar.subscribe() as queue:
        await coro
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
    return events


async def test_a_typed_turn_drives_the_face(engine: Assistant, api: FakeAPI) -> None:
    """Telegram animates the avatar too — the brain is the same one."""
    api.queue_reply(["[bored] The dentist."])
    events = await bus_events(engine, engine.send("s", "what was that"))

    assert [e["type"] for e in events] == ["state", "tag", "say", "state"]
    assert events[0]["state"] == "thinking"
    assert events[1]["tag"] == "bored"
    assert events[2]["text"] == "The dentist."
    assert events[-1]["state"] == "idle"


async def test_a_failed_turn_still_puts_her_face_back(
    engine: Assistant, api: FakeAPI
) -> None:
    api.queue_status(500)
    events = await bus_events(engine, engine.send("s", "hello"))
    assert events[-1] == {"type": "state", "state": "idle"}


async def test_a_reader_hanging_up_puts_her_face_back(
    engine: Assistant, api: FakeAPI
) -> None:
    """A phone that loses signal mid-reply must not leave her mid-thought."""
    api.queue_reply(["[flat] one two three four"])

    async def abandon() -> None:
        stream = engine.stream("s", "hi")
        await stream.__anext__()
        await stream.aclose()

    assert (await bus_events(engine, abandon()))[-1]["state"] == "idle"


async def test_a_spoken_turn_leaves_the_state_to_whoever_plays_it(
    engine: Assistant, api: FakeAPI
) -> None:
    """The audio hasn't been heard yet when the model stops writing. Announcing
    idle here would shut her mouth before a word came out of the speakers."""
    api.queue_reply(["[smug] Obviously. It was in the calendar."])

    async def speak() -> None:
        async for _ in engine.speak("s", "hello"):
            pass

    events = await bus_events(engine, speak())
    kinds = [e["type"] for e in events]

    assert [e["state"] for e in events if e["type"] == "state"] == ["thinking"]
    assert "tag" in kinds
    assert [e["text"] for e in events if e["type"] == "say"], "subtitles per chunk"


async def test_the_tag_is_published_exactly_once_per_spoken_turn(
    engine: Assistant, api: FakeAPI
) -> None:
    api.queue_reply(["[amused] Ha."])

    async def speak() -> None:
        async for _ in engine.speak("s", "hello"):
            pass

    events = await bus_events(engine, speak())
    assert [e for e in events if e["type"] == "tag"] == [{"type": "tag", "tag": "amused"}]


# ---------------------------------------------------------------- endpoints


@pytest.fixture
def client(api: FakeAPI, store):
    engine = Assistant(PERSONA, store=store, client=api.client())
    with TestClient(create_app(token=TOKEN, engine=engine)) as c:
        yield c


def test_the_viewer_is_served(client) -> None:
    response = client.get("/avatar")
    assert response.status_code == 200
    # Unauthenticated on purpose: it holds no secret, it asks for one.
    assert "window.rig" in response.text


def test_publishing_needs_the_token(client) -> None:
    assert client.post("/avatar/publish", json={"type": "state", "state": "idle"}).status_code == 401
    assert client.post("/avatar/ticket").status_code == 401


def test_publish_reports_how_many_faces_are_watching(client) -> None:
    body = client.post(
        "/avatar/publish", json={"type": "state", "state": "speaking"}, headers=AUTH
    ).json()
    assert body == {"listeners": 0}


def test_a_client_cannot_publish_expressions(client) -> None:
    """Only the engine knows those. The player knows mouth and state, nothing else."""
    response = client.post("/avatar/publish", json={"type": "tag", "tag": "smug"}, headers=AUTH)
    assert response.status_code == 422


def test_a_ticket_works_once(client) -> None:
    ticket = client.post("/avatar/ticket", headers=AUTH).json()["ticket"]

    with client.websocket_connect(f"/avatar/events?ticket={ticket}") as socket:
        assert socket.receive_json()["type"] == "hello"

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/avatar/events?ticket={ticket}") as socket:
            socket.receive_json()


def test_the_socket_is_closed_without_credentials(client) -> None:
    for url in ("/avatar/events", "/avatar/events?ticket=made-up"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url) as socket:
                socket.receive_json()


def test_the_socket_accepts_a_bearer_header(client) -> None:
    """For anything that isn't a browser and can set one."""
    with client.websocket_connect("/avatar/events", headers=AUTH) as socket:
        assert socket.receive_json()["type"] == "hello"


def test_the_face_is_told_who_she_is_and_what_she_can_wear(client) -> None:
    with client.websocket_connect("/avatar/events", headers=AUTH) as socket:
        hello = socket.receive_json()

    assert hello["persona"]
    # The rig maps these to expressions, so it has to be told the real list.
    assert "neutral" in hello["emotions"]


def test_what_a_client_publishes_reaches_the_face(client) -> None:
    with client.websocket_connect("/avatar/events", headers=AUTH) as socket:
        socket.receive_json()  # hello

        posted = client.post(
            "/avatar/publish",
            json={"type": "mouth", "frame_ms": 40, "open": [0.0, 0.6, 0.2]},
            headers=AUTH,
        )
        assert posted.json() == {"listeners": 1}
        assert socket.receive_json() == {
            "type": "mouth",
            "frame_ms": 40,
            "open": [0.0, 0.6, 0.2],
        }
