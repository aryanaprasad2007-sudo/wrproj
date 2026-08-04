"""Recogniser registry. Mirrors assistant/tts — one adapter, one line here."""

from __future__ import annotations

from typing import Any, Callable

from .base import EchoEngine, STTEngine

__all__ = ["STTEngine", "EchoEngine", "from_config", "ENGINES"]


def _whisper(config: dict[str, Any]) -> STTEngine:
    from .whisper import DEFAULT_MODEL, WhisperEngine

    return WhisperEngine(
        model=config.get("model") or DEFAULT_MODEL,
        device=config.get("device") or "cpu",
        compute_type=config.get("compute_type") or "int8",
        language=config.get("language", "en"),
        model_dir=config.get("model_dir"),
    )


def _echo(config: dict[str, Any]) -> STTEngine:
    return EchoEngine(text=config.get("text") or "this is a test transcript")


ENGINES: dict[str, Callable[[dict[str, Any]], STTEngine]] = {
    "whisper": _whisper,
    "echo": _echo,
}


def from_config(stt: dict[str, Any] | None) -> STTEngine:
    """Build the engine named by a persona's `stt:` block.

    Defaults to whisper — unlike the voice, there is no useful placeholder for
    a recogniser, so the honest default is the real one plus a clear error if
    its model isn't there yet.
    """
    config = dict(stt or {})
    name = (config.get("engine") or "whisper").strip().lower()
    if name not in ENGINES:
        raise ValueError(
            f"unknown stt engine {name!r}; available: {', '.join(sorted(ENGINES))}"
        )
    return ENGINES[name](config)
