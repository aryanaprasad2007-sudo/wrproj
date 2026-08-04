"""The swappable box.

The character voice hasn't been chosen, so nothing above this layer is allowed
to know which engine is in use. Engines emit raw little-endian PCM; the server
announces the format once and streams bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    sample_width: int = 2  # bytes per sample; 2 == 16-bit
    channels: int = 1

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.sample_width * self.channels

    def duration(self, pcm: bytes) -> float:
        return len(pcm) / self.bytes_per_second

    def as_dict(self) -> dict[str, int]:
        return {
            "sample_rate": self.sample_rate,
            "sample_width": self.sample_width,
            "channels": self.channels,
        }


@runtime_checkable
class TTSEngine(Protocol):
    name: str

    @property
    def format(self) -> AudioFormat:
        """Format of the PCM this engine emits. Stable for the engine's lifetime."""
        ...

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield raw PCM for one speakable chunk."""
        ...

    async def aclose(self) -> None: ...


def wav_header(fmt: AudioFormat, data_bytes: int) -> bytes:
    """A RIFF header, for writing finished audio to a file.

    Streaming responses send bare PCM instead — a WAV header needs the total
    length up front, which we don't have until she's stopped talking.
    """
    import struct

    byte_rate = fmt.sample_rate * fmt.channels * fmt.sample_width
    block_align = fmt.channels * fmt.sample_width
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_bytes)
        + b"WAVEfmt "
        + struct.pack(
            "<IHHIIHH",
            16,
            1,  # PCM
            fmt.channels,
            fmt.sample_rate,
            byte_rate,
            block_align,
            fmt.sample_width * 8,
        )
        + b"data"
        + struct.pack("<I", data_bytes)
    )
