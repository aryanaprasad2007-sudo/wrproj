import struct

import pytest

from assistant.tts import ENGINES, ToneEngine, from_config
from assistant.tts.base import AudioFormat, wav_header


# ------------------------------------------------------------------- format


def test_format_arithmetic() -> None:
    fmt = AudioFormat(sample_rate=22050, sample_width=2, channels=1)
    assert fmt.bytes_per_second == 44100
    assert fmt.duration(b"\x00" * 44100) == pytest.approx(1.0)
    assert fmt.as_dict() == {"sample_rate": 22050, "sample_width": 2, "channels": 1}


def test_format_roundtrips_through_the_wire_shape() -> None:
    """The server sends as_dict() and the client rebuilds with AudioFormat(**d)."""
    fmt = AudioFormat(sample_rate=16000, sample_width=2, channels=1)
    assert AudioFormat(**fmt.as_dict()) == fmt


def test_wav_header_is_valid_riff() -> None:
    fmt = AudioFormat(sample_rate=22050)
    header = wav_header(fmt, 1000)

    assert len(header) == 44
    assert header[:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
    assert header[36:40] == b"data"
    assert struct.unpack("<I", header[4:8])[0] == 1036  # 36 + payload
    assert struct.unpack("<I", header[40:44])[0] == 1000
    assert struct.unpack("<H", header[22:24])[0] == 1  # mono
    assert struct.unpack("<I", header[24:28])[0] == 22050
    assert struct.unpack("<H", header[34:36])[0] == 16  # bit depth


def test_wav_header_reads_back_with_the_stdlib() -> None:
    import io
    import wave

    fmt = AudioFormat(sample_rate=22050)
    pcm = b"\x01\x02" * 500
    buf = io.BytesIO(wav_header(fmt, len(pcm)) + pcm)

    with wave.open(buf) as w:
        assert w.getframerate() == 22050
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.readframes(w.getnframes()) == pcm


# --------------------------------------------------------------- tone engine


async def collect(engine, text: str) -> bytes:
    return b"".join([chunk async for chunk in engine.synthesize(text)])


async def test_tone_engine_produces_audible_pcm() -> None:
    pcm = await collect(ToneEngine(), "Sixty-one and overcast.")

    assert len(pcm) % 2 == 0, "16-bit samples must not be truncated"
    peak = max(abs(s) for s in struct.unpack(f"<{len(pcm) // 2}h", pcm))
    assert peak > 1000, "must actually be audible — silence would hide bugs"


async def test_tone_length_tracks_text_length() -> None:
    engine = ToneEngine()
    short = await collect(engine, "Fine.")
    long = await collect(engine, "Fine. " * 30)
    assert len(long) > len(short) * 3


async def test_tone_streams_in_frames() -> None:
    """Callers must exercise the streaming path, not get one big buffer."""
    engine = ToneEngine()
    frames = [c async for c in engine.synthesize("A reasonably long sentence to speak.")]
    assert len(frames) > 1


async def test_tone_edges_are_faded() -> None:
    """Unfaded chunk boundaries click audibly when played back to back."""
    pcm = await collect(ToneEngine(), "Testing the envelope.")
    first, last = struct.unpack("<h", pcm[:2])[0], struct.unpack("<h", pcm[-2:])[0]
    assert abs(first) < 500 and abs(last) < 500


async def test_speed_shortens_output() -> None:
    text = "The same sentence at two speeds."
    assert len(await collect(ToneEngine(speed=2.0), text)) < len(
        await collect(ToneEngine(speed=1.0), text)
    )


async def test_empty_text_still_yields_valid_audio() -> None:
    pcm = await collect(ToneEngine(), "")
    assert len(pcm) % 2 == 0


# ------------------------------------------------------------------ registry


def test_defaults_to_tone_so_a_fresh_clone_makes_sound() -> None:
    assert from_config(None).name == "tone"
    assert from_config({}).name == "tone"


def test_selects_by_name() -> None:
    assert from_config({"engine": "tone"}).name == "tone"
    assert from_config({"engine": "  TONE  "}).name == "tone"


def test_unknown_engine_names_the_alternatives() -> None:
    with pytest.raises(ValueError, match="unknown voice engine"):
        from_config({"engine": "elevenlabs"})


def test_speed_is_read_from_the_persona_voice_block() -> None:
    assert from_config({"engine": "tone", "speed": 1.5}).speed == 1.5


def test_piper_is_registered_but_not_imported_eagerly() -> None:
    """Selecting tone must not require piper to be installed."""
    assert "piper" in ENGINES


def test_every_engine_satisfies_the_protocol() -> None:
    from assistant.tts.base import TTSEngine

    engine = from_config({"engine": "tone"})
    assert isinstance(engine, TTSEngine)
    assert isinstance(engine.format, AudioFormat)


# -------------------------------------------------------------------- piper


def test_piper_reports_a_format_without_the_model_present(tmp_path) -> None:
    """The server announces the format before the ONNX is loaded."""
    from assistant.tts.piper import PiperEngine

    engine = PiperEngine(voice="en_US-lessac-medium", model_dir=tmp_path)
    assert engine.format.sample_rate == 22050


def test_piper_reads_the_rate_from_the_voice_config(tmp_path) -> None:
    import json

    (tmp_path / "custom.onnx.json").write_text(json.dumps({"audio": {"sample_rate": 16000}}))
    from assistant.tts.piper import PiperEngine

    assert PiperEngine(voice="custom", model_dir=tmp_path).format.sample_rate == 16000


async def test_piper_missing_model_explains_how_to_fix_it(tmp_path) -> None:
    """The likeliest first-run failure must say the exact command to run."""
    from assistant.tts.piper import PiperEngine

    engine = PiperEngine(voice="en_US-lessac-medium", model_dir=tmp_path)
    with pytest.raises(RuntimeError) as excinfo:
        await collect(engine, "hello")

    message = str(excinfo.value)
    assert "piper.download_voices" in message
    assert "en_US-lessac-medium" in message
    assert "tone" in message  # and the way to proceed without downloading
