import pytest

from assistant.stt import ENGINES, EchoEngine, from_config
from assistant.stt.base import STTEngine


def test_defaults_to_the_real_engine() -> None:
    """No useful placeholder exists for a recogniser, so the default is real."""
    assert from_config(None).name == "whisper"
    assert from_config({}).name == "whisper"


def test_selects_by_name() -> None:
    assert from_config({"engine": "echo"}).name == "echo"
    assert from_config({"engine": " ECHO "}).name == "echo"


def test_unknown_engine_names_the_alternatives() -> None:
    with pytest.raises(ValueError, match="unknown stt engine"):
        from_config({"engine": "deepgram"})


def test_registry_holds_both() -> None:
    assert set(ENGINES) == {"whisper", "echo"}


def test_engines_satisfy_the_protocol() -> None:
    engine = from_config({"engine": "echo"})
    assert isinstance(engine, STTEngine)
    assert engine.sample_rate == 16000


async def test_echo_returns_its_text_and_records_audio() -> None:
    engine = EchoEngine("what was that reminder")
    assert await engine.transcribe(b"\x01\x02" * 100) == "what was that reminder"
    assert len(engine.calls) == 1


async def test_echo_returns_nothing_for_empty_audio() -> None:
    assert await EchoEngine().transcribe(b"") == ""


def test_whisper_config_is_read_from_the_persona_block() -> None:
    from assistant.stt.whisper import WhisperEngine

    engine = from_config({"engine": "whisper", "model": "small.en", "language": "fr"})
    assert isinstance(engine, WhisperEngine)
    assert engine.model_name == "small.en"
    assert engine.language == "fr"


async def test_whisper_skips_the_model_entirely_for_empty_audio() -> None:
    """Must not pay to load a model to transcribe nothing."""
    from assistant.stt.whisper import WhisperEngine

    engine = WhisperEngine(model="does-not-exist")
    assert await engine.transcribe(b"") == ""


async def test_whisper_load_failure_explains_the_cause(monkeypatch) -> None:
    """The likeliest failure is a blocked or offline model download."""
    from assistant.stt.whisper import WhisperEngine

    engine = WhisperEngine(model="definitely-not-a-real-model-name")
    with pytest.raises(RuntimeError) as excinfo:
        await engine.transcribe(b"\x00" * 3200)

    message = str(excinfo.value)
    assert "Hugging Face" in message or "network" in message
    assert "model_dir" in message
