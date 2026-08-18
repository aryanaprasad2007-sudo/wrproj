"""LTX-Video image-to-video. The default backend on 8 GB.

Chosen as default for one reason: it is the only backend here that produces a
usable 3-second clip at 768x512 in about two minutes on a 4060. The others are
better in some dimension but all cost 2-5x more wall time, and a short film is
dozens of shots -- iteration speed compounds.

Its temporal VAE compresses 8:1, hence frames of the form 8k+1. Asking for 96
frames instead of 97 truncates the last chunk, which reads on screen as the
final beat of every shot glitching.
"""
from __future__ import annotations

import logging

from .base import VideoBackend
from .. import hardware

log = logging.getLogger(__name__)

DEFAULT_MODEL = "Lightricks/LTX-Video"


class LTXBackend(VideoBackend):
    name = "ltx"
    frame_multiple = 8
    frame_offset = 1        # 9, 17, 25, ... 257
    max_frames = 257
    min_frames = 9
    dim_multiple = 32       # LTX is strict about this, unlike SD
    uses_prompt = True
    native = (768, 512)

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import LTXImageToVideoPipeline

        model = self.cfg.video_model or DEFAULT_MODEL
        log.info("loading LTX-Video: %s", model)
        pipe = LTXImageToVideoPipeline.from_pretrained(
            model, torch_dtype=torch.bfloat16 if self.hw.cuda else torch.float32
        )
        pipe.set_progress_bar_config(disable=True)
        hardware.apply_memory_policy(pipe, self.hw)
        self._pipe = pipe
        return pipe

    def generate(self, *, image, prompt, negative, width, height, num_frames,
                 steps, cfg_scale, seed, fps):
        pipe = self._load()
        w, h = self.quantise_dims(width, height)

        # LTX responds to *motion* description, not subject description. The
        # subject is already fixed by the keyframe, so a prompt that re-describes
        # the character wastes conditioning and can fight the input image.
        out = pipe(
            image=image.resize((w, h)),
            prompt=prompt,
            negative_prompt=negative or "worst quality, blurry, jittery, distorted",
            width=w,
            height=h,
            num_frames=num_frames,
            num_inference_steps=int(steps),
            guidance_scale=float(cfg_scale),
            generator=self._generator(seed),
        )
        return list(out.frames[0])
