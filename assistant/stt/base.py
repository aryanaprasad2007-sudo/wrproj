"""Speech recognition interface.

Same shape as the TTS layer: one small protocol, adapters behind it, so the
recogniser can be swapped without anything above this file noticing.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class STTEngine(Protocol):
    name: str
    # PCM the engine expects: 16-bit mono at this rate.
    sample_rate: int

    async def transcribe(self, pcm: bytes) -> str:
        """Return the text of one utterance. Empty string when nothing was said."""
        ...

    async def aclose(self) -> None: ...


class EchoEngine(STTEngine):
    """Returns a fixed string. For tests and for exercising the plumbing.

    Not offered as a real option: unlike a placeholder voice, which is audibly
    a placeholder, a recogniser that ignores what you said is indistinguishable
    from one that is simply wrong.
    """

    name = "echo"
    sample_rate = 16000

    def __init__(self, text: str = "this is a test transcript") -> None:
        self.text = text
        self.calls: list[bytes] = []

    async def transcribe(self, pcm: bytes) -> str:
        self.calls.append(pcm)
        return self.text if pcm else ""

    async def aclose(self) -> None:
        return None
