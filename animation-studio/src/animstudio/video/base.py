"""The video-backend contract.

Stage B takes a keyframe and makes it move. Every backend here is
image-to-video, not text-to-video, because Stage A already decided what the
characters look like -- handing that decision to the video model would throw
away the LoRA and IP-Adapter work.

Backends differ in ways the pipeline must not have to know about:

  backend      params  native px     frames        prompt?  8 GB verdict
  -----------  ------  ------------  ------------  -------  ---------------------
  ltx           2 B    768x512       8k+1, <=257   yes      default; fastest
  wan           1.3 B  832x480       4k+1, <=81    yes      best motion quality
  svd           1.5 B  1024x576      25 fixed      NO       strong but uncontrolled
  animatediff   ~1.4 B 512x512       16 (ctx 32)   yes      most controllable

So the contract normalises three things -- frame-count quantisation, dimension
quantisation, and whether a text prompt is honoured -- and the pipeline asks
for *seconds*, letting the backend land on a legal frame count.

Adding a backend: subclass VideoBackend, implement `generate` and the three
class attributes, then register it in registry.py. Nothing else changes.
"""
from __future__ import annotations

import abc
import logging

log = logging.getLogger(__name__)


class VideoBackend(abc.ABC):
    """One image-to-video model."""

    name: str = "base"
    #: Frame counts must satisfy n % frame_multiple == frame_offset.
    frame_multiple: int = 1
    frame_offset: int = 0
    max_frames: int = 121
    min_frames: int = 9
    #: Width/height must be divisible by this.
    dim_multiple: int = 8
    #: Does this model read the text prompt at all?
    uses_prompt: bool = True
    #: Resolution the model was trained at; we stay near it.
    native: tuple = (768, 512)

    def __init__(self, cfg, hw):
        self.cfg = cfg
        self.hw = hw
        self._pipe = None

    # ------------------------------------------------------- normalisation
    def quantise_frames(self, seconds: float, fps: int) -> int:
        """Nearest legal frame count for `seconds` of footage.

        Every latent video model compresses time, so frame counts are not
        free: LTX and Wan both need (multiple*k + 1) or the temporal VAE
        produces a truncated or corrupted last chunk. Getting this wrong
        shows up as a garbled final half-second, which is easy to misread as
        a prompt problem.
        """
        want = max(1, round(seconds * fps))
        if self.frame_multiple > 1:
            k = round((want - self.frame_offset) / self.frame_multiple)
            want = max(1, k) * self.frame_multiple + self.frame_offset
        want = max(self.min_frames, min(self.max_frames, want))
        return int(want)

    def quantise_dims(self, width: int, height: int) -> tuple:
        m = self.dim_multiple
        w = max(m, int(round(width / m)) * m)
        h = max(m, int(round(height / m)) * m)
        return w, h

    def plan(self, seconds: float, fps: int, width: int, height: int) -> dict:
        """What this backend will actually do, before loading anything.

        Called by `--dry-run` so a shot list can be validated, and its true
        runtime estimated, without a single model download.
        """
        n = self.quantise_frames(seconds, fps)
        w, h = self.quantise_dims(width, height)
        return {
            "backend": self.name,
            "frames": n,
            "actual_seconds": round(n / fps, 3),
            "width": w,
            "height": h,
            "prompt_honoured": self.uses_prompt,
        }

    # ------------------------------------------------------------ generate
    @abc.abstractmethod
    def generate(self, *, image, prompt, negative, width, height, num_frames,
                 steps, cfg_scale, seed, fps):
        """Return a list of PIL frames. `image` is the Stage A keyframe."""

    def unload(self):
        self._pipe = None
        from .. import hardware
        hardware.free_vram()

    # --------------------------------------------------------------- utils
    def _generator(self, seed: int):
        import torch
        # CPU generator keeps seeds reproducible across offload configurations;
        # a CUDA generator gives different noise when offloading changes.
        return torch.Generator(device="cpu").manual_seed(int(seed))

    def _warn_prompt_ignored(self, prompt: str):
        if prompt and not self.uses_prompt:
            log.warning(
                "backend '%s' ignores text prompts -- shot motion comes only "
                "from the keyframe. Camera notes will have no effect.", self.name
            )
