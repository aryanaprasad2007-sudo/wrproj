"""Local neural TTS via Piper.

Runs offline on CPU with no API key, which makes it the right first real engine:
you can hear the whole pipeline working before deciding what the character
should actually sound like. Quality is well short of a hosted cloning engine —
when the voice is chosen, this file is the template for that adapter.

Piper's synthesis is blocking and CPU-bound, so every call is pushed to a worker
thread; running it inline would stall the event loop and stop the server serving
anything else while she talks.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from .base import AudioFormat, TTSEngine

DEFAULT_VOICE = "en_US-lessac-medium"
DEFAULT_DIR = Path("voices")


class PiperEngine(TTSEngine):
    name = "piper"

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        model_dir: str | Path = DEFAULT_DIR,
        speed: float = 1.0,
    ) -> None:
        self.voice = voice
        self.model_dir = Path(model_dir)
        self.speed = max(0.25, speed)
        self.model_path = self.model_dir / f"{voice}.onnx"
        self.config_path = self.model_dir / f"{voice}.onnx.json"
        self._voice: Any = None
        self._lock = asyncio.Lock()
        self._format = AudioFormat(sample_rate=self._sample_rate_from_config())

    # ------------------------------------------------------------------ setup

    def _sample_rate_from_config(self) -> int:
        """Read the rate from the voice's JSON so `format` works before loading.

        The ONNX model is tens of megabytes and slow to load; the format has to
        be known up front so the server can announce it to the client.
        """
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            return int(config["audio"]["sample_rate"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return 22050  # every current Piper "medium" voice

    def _missing_model_error(self) -> RuntimeError:
        return RuntimeError(
            f"Piper voice {self.voice!r} not found in {self.model_dir}/.\n"
            f"Download it once with:\n"
            f"    python -m piper.download_voices {self.voice} --download-dir {self.model_dir}\n"
            f"Or set voice.engine to 'tone' in the persona file to run without a model."
        )

    def _load(self) -> Any:
        from piper import PiperVoice

        if not self.model_path.exists():
            raise self._missing_model_error()
        return PiperVoice.load(self.model_path, config_path=self.config_path)

    async def _ensure_loaded(self) -> Any:
        async with self._lock:
            if self._voice is None:
                self._voice = await asyncio.to_thread(self._load)
                # Trust the loaded model over the JSON if they disagree.
                rate = getattr(self._voice.config, "sample_rate", None)
                if rate:
                    self._format = AudioFormat(sample_rate=int(rate))
        return self._voice

    # --------------------------------------------------------------- synthesis

    @property
    def format(self) -> AudioFormat:
        return self._format

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        voice = await self._ensure_loaded()
        from piper import SynthesisConfig

        # Piper's length_scale is duration, so it runs inverse to speed.
        config = SynthesisConfig(length_scale=1.0 / self.speed)

        def run() -> list[bytes]:
            return [chunk.audio_int16_bytes for chunk in voice.synthesize(text, config)]

        # Chunks arriving here are already sentence-sized, so synthesising the
        # whole thing in one thread hop costs little and keeps this simple.
        for pcm in await asyncio.to_thread(run):
            yield pcm

    async def aclose(self) -> None:
        self._voice = None
