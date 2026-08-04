import json
import struct
import wave
from base64 import b64decode

import httpx
import pytest

from assistant.server import create_app
from assistant.tts.base import AudioFormat
from assistant.voice_client import SoundDevicePlayer, VoiceClient, WavFilePlayer, default_player
from conftest import FakeAPI

TOKEN = "test-token"


# ------------------------------------------------------- engine.speak events


async def speak(engine, api: FakeAPI, deltas: list[str], session="s") -> list[dict]:
    api.queue_reply(deltas)
    return [e async for e in engine.speak(session, "hello")]


async def test_speak_announces_format_before_anything_else(engine, api: FakeAPI) -> None:
    events = await speak(engine, api, ["[neutral] Sixty-one and overcast."])

    assert events[0]["type"] == "start"
    assert events[0]["engine"] == "tone"
    # The client needs this to open its audio device before samples arrive.
    assert AudioFormat(**events[0]["format"]).sample_rate > 0


async def test_speak_emits_text_and_audio_then_done(engine, api: FakeAPI) -> None:
    events = await speak(engine, api, ["[bored] The dentist. Tuesday, ten in the morning."])
    kinds = [e["type"] for e in events]

    assert kinds[0] == "start"
    assert "tag" in kinds
    assert "text" in kinds and "audio" in kinds
    assert kinds[-1] == "done"


async def test_audio_follows_its_own_text_chunk(engine, api: FakeAPI) -> None:
    """Each chunk is spoken as it completes, not batched up at the end."""
    events = await speak(
        engine, api, ["[neutral] First sentence here. Second sentence follows."]
    )
    kinds = [e["type"] for e in events if e["type"] in ("text", "audio")]

    assert kinds[0] == "text", "text must precede its audio"
    assert "audio" in kinds[: kinds.index("text", 1)], (
        "the first chunk must be spoken before the second chunk's text arrives — "
        "otherwise synthesis was deferred to the end of the turn"
    )


async def test_spoken_text_reassembles_to_the_full_reply(engine, api: FakeAPI) -> None:
    events = await speak(
        engine, api, ["[flat] You have three unfinished ones. ", "I'm not going to stop you."]
    )
    spoken = " ".join(e["text"] for e in events if e["type"] == "text")
    assert spoken == "You have three unfinished ones. I'm not going to stop you."


async def test_tag_is_not_spoken(engine, api: FakeAPI) -> None:
    events = await speak(engine, api, ["[smug] Naturally."])
    assert all("[smug]" not in e["text"] for e in events if e["type"] == "text")


async def test_audio_is_well_formed_pcm(engine, api: FakeAPI) -> None:
    events = await speak(engine, api, ["[neutral] Sixty-one and overcast today."])
    pcm = b"".join(e["pcm"] for e in events if e["type"] == "audio")

    assert pcm and len(pcm) % 2 == 0
    fmt = AudioFormat(**events[0]["format"])
    assert fmt.duration(pcm) > 0.2


async def test_speak_surfaces_errors_and_stops(engine, api: FakeAPI) -> None:
    api.queue_status(500)
    events = [e async for e in engine.speak("s", "hello")]

    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "error"
    assert not any(e["type"] == "audio" for e in events)


async def test_speak_persists_history_like_a_text_turn(engine, api: FakeAPI) -> None:
    await speak(engine, api, ["[bored] The dentist."])
    assert [m["role"] for m in engine.history("s")] == ["user", "assistant"]


# ------------------------------------------------------------ voice endpoint


@pytest.fixture
async def app(engine):
    """Run the real lifespan — ASGITransport, unlike TestClient, does not."""
    application = create_app(token=TOKEN, engine=engine)
    async with application.router.lifespan_context(application):
        yield application


async def voice_events(app, api: FakeAPI, deltas: list[str]) -> list[dict]:
    api.queue_reply(deltas)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/chat/voice",
            json={"session_id": "s", "message": "hi"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            return [
                json.loads(line[6:])
                async for line in resp.aiter_lines()
                if line.startswith("data: ")
            ]


async def test_voice_endpoint_streams_base64_audio(app, api: FakeAPI) -> None:
    events = await voice_events(app, api, ["[bored] The dentist. Tuesday at ten."])

    audio = [e for e in events if e["type"] == "audio"]
    assert audio
    pcm = b"".join(b64decode(e["pcm"]) for e in audio)
    assert len(pcm) % 2 == 0
    peak = max(abs(s) for s in struct.unpack(f"<{len(pcm) // 2}h", pcm))
    assert peak > 1000


async def test_voice_endpoint_requires_auth(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat/voice", json={"session_id": "s", "message": "hi"})
    assert resp.status_code == 401


# -------------------------------------------------------------------- client


async def test_client_decodes_audio_and_drives_the_player(app, api: FakeAPI) -> None:
    api.queue_reply(["[bored] The dentist. Tuesday at ten in the morning."])
    player = WavFilePlayer()
    shown: list[str] = []

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        result = await VoiceClient("http://test", TOKEN).say(
            http, "s", "what was it", player, on_text=shown.append
        )

    assert result["type"] == "done"
    assert " ".join(shown) == "The dentist. Tuesday at ten in the morning."
    assert result["audio_note"], "should report where the audio went"


async def test_client_reports_a_rejected_request(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        result = await VoiceClient("http://test", "wrong-token").say(
            http, "s", "hi", WavFilePlayer()
        )
    assert result["type"] == "error"
    assert "401" in result["message"]


# -------------------------------------------------------------------- players


def test_wav_player_writes_a_playable_file(tmp_path) -> None:
    fmt = AudioFormat(sample_rate=22050)
    player = WavFilePlayer(tmp_path)
    player.start(fmt)
    player.write(b"\x01\x02" * 1000)
    player.write(b"\x03\x04" * 1000)
    note = player.stop()

    assert note
    written = list(tmp_path.glob("*.wav"))
    assert len(written) == 1
    with wave.open(str(written[0])) as w:
        assert w.getframerate() == 22050
        assert w.getnframes() == 2000


def test_wav_player_writes_nothing_when_silent(tmp_path) -> None:
    player = WavFilePlayer(tmp_path)
    player.start(AudioFormat(sample_rate=22050))
    assert player.stop() is None
    assert list(tmp_path.glob("*.wav")) == []


def test_wav_player_resets_between_turns(tmp_path) -> None:
    """Audio must not accumulate across turns and replay the whole session."""
    player = WavFilePlayer(tmp_path)
    for _ in range(2):
        player.start(AudioFormat(sample_rate=22050))
        player.write(b"\x01\x02" * 100)
        player.stop()

    for path in tmp_path.glob("*.wav"):
        with wave.open(str(path)) as w:
            assert w.getnframes() == 100


def test_default_player_falls_back_without_a_device(monkeypatch) -> None:
    """Must stay usable over SSH and in containers."""
    monkeypatch.setattr(SoundDevicePlayer, "available", staticmethod(lambda: False))
    player, note = default_player()
    assert isinstance(player, WavFilePlayer)
    assert note and "WAV" in note


def test_default_player_uses_speakers_when_present(monkeypatch) -> None:
    monkeypatch.setattr(SoundDevicePlayer, "available", staticmethod(lambda: True))
    player, note = default_player()
    assert isinstance(player, SoundDevicePlayer)
    assert note is None


def test_sounddevice_availability_never_raises() -> None:
    """Probing must not explode when PortAudio is missing entirely."""
    assert SoundDevicePlayer.available() in (True, False)
