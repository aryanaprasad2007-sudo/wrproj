"""Engine registry.

Adding an engine means writing one adapter and adding one line here. Nothing
above this layer changes — that's the whole point of deferring the voice choice.
"""

from __future__ import annotations

from typing import Any, Callable

from .base import AudioFormat, TTSEngine, wav_header
from .tone import ToneEngine

__all__ = ["AudioFormat", "TTSEngine", "ToneEngine", "wav_header", "from_config", "ENGINES"]


def _piper(config: dict[str, Any]) -> TTSEngine:
    # Imported lazily so the piper dependency is only needed if it's selected.
    from .piper import DEFAULT_VOICE, PiperEngine

    return PiperEngine(
        voice=config.get("model") or DEFAULT_VOICE,
        model_dir=config.get("model_dir") or "voices",
        speed=float(config.get("speed") or 1.0),
    )


def _tone(config: dict[str, Any]) -> TTSEngine:
    return ToneEngine(speed=float(config.get("speed") or 1.0))


ENGINES: dict[str, Callable[[dict[str, Any]], TTSEngine]] = {
    "tone": _tone,
    "piper": _piper,
}


def from_config(voice: dict[str, Any] | None) -> TTSEngine:
    """Build the engine named by a persona's `voice:` block.

    Defaults to the tone engine so a fresh clone produces audio with no model
    download — you hear that the plumbing works, then choose a real voice.
    """
    config = dict(voice or {})
    name = (config.get("engine") or "tone").strip().lower()
    if name not in ENGINES:
        raise ValueError(
            f"unknown voice engine {name!r}; available: {', '.join(sorted(ENGINES))}"
        )
    return ENGINES[name](config)
