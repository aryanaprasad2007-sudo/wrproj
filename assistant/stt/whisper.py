"""Local speech recognition via faster-whisper.

Offline, free, CPU-only, and good enough that transcription stops being the
weak link. The model downloads once on first use — which needs network access
that a locked-down environment may not have, so the failure is made explicit
rather than surfacing as a stack trace from deep inside the library.

Transcription is blocking and CPU-bound, so it runs on a worker thread.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import STTEngine

DEFAULT_MODEL = "base.en"


class WhisperEngine(STTEngine):
    name = "whisper"
    sample_rate = 16000

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "en",
        model_dir: str | None = None,
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.model_dir = model_dir
        self._model: Any = None
        self._lock = asyncio.Lock()

    def _load(self) -> Any:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Install it with:\n"
                "    pip install faster-whisper"
            ) from exc

        try:
            return WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.model_dir,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not load Whisper model {self.model_name!r}: {exc}\n"
                "The model downloads from Hugging Face on first use, so this "
                "usually means no network access or a blocked host. Pre-fetch it "
                "on a machine that can reach it, or set stt.model_dir to a "
                "directory holding an already-downloaded model."
            ) from exc

    async def _ensure_loaded(self) -> Any:
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)
        return self._model

    async def transcribe(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        model = await self._ensure_loaded()

        def run() -> str:
            import numpy as np

            # faster-whisper wants float32 in [-1, 1]; we carry 16-bit PCM.
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = model.transcribe(audio, language=self.language)
            return " ".join(segment.text.strip() for segment in segments).strip()

        return await asyncio.to_thread(run)

    async def aclose(self) -> None:
        self._model = None
