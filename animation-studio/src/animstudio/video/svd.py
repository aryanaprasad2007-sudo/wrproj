"""Stable Video Diffusion image-to-video.

Included because it is genuinely good at natural camera drift and cloth/hair
motion, and because it makes the trade-off in this pipeline explicit: SVD has
**no text conditioning at all**. `uses_prompt = False`, so the base class warns
when a shot supplies camera notes that cannot possibly be honoured.

That makes it right for exactly one job -- shots where you want the keyframe to
breathe and nothing else. Use `motion_bucket_id` (in `stages.svd`) rather than a
prompt to ask for more or less movement.
"""
from __future__ import annotations

import logging

from .base import VideoBackend
from .. import hardware

log = logging.getLogger(__name__)

DEFAULT_MODEL = "stabilityai/stable-video-diffusion-img2vid-xt"


class SVDBackend(VideoBackend):
    name = "svd"
    frame_multiple = 1
    max_frames = 25         # xt is trained for 25; asking for more degrades badly
    min_frames = 14
    dim_multiple = 64
    uses_prompt = False
    native = (1024, 576)

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import StableVideoDiffusionPipeline

        model = self.cfg.video_model or DEFAULT_MODEL
        log.info("loading SVD: %s", model)
        pipe = StableVideoDiffusionPipeline.from_pretrained(
            model,
            torch_dtype=torch.float16 if self.hw.cuda else torch.float32,
            variant="fp16" if self.hw.cuda else None,
        )
        pipe.set_progress_bar_config(disable=True)
        hardware.apply_memory_policy(pipe, self.hw)
        # SVD decodes all frames at once by default and will OOM on 8 GB well
        # before the unet does. Forcing one frame at a time through the VAE is
        # what makes it run here at all.
        if hasattr(pipe, "enable_vae_slicing"):
            pipe.enable_vae_slicing()
        self._pipe = pipe
        return pipe

    def generate(self, *, image, prompt, negative, width, height, num_frames,
                 steps, cfg_scale, seed, fps):
        self._warn_prompt_ignored(prompt)
        pipe = self._load()
        w, h = self.quantise_dims(width, height)

        opts = (self.cfg.raw.get("stages", {}) or {}).get("svd", {}) or {}
        out = pipe(
            image.resize((w, h)),
            height=h, width=w,
            num_frames=int(num_frames),
            num_inference_steps=int(steps),
            # How much the clip moves. 127 is the trained default; below ~80
            # it is nearly a still, above ~180 it tears.
            motion_bucket_id=int(opts.get("motion_bucket_id", 127)),
            # Synthetic sensor noise added to the conditioning frame. Higher =
            # more freedom to deviate from the keyframe, which for this project
            # means more character drift, so keep it low.
            noise_aug_strength=float(opts.get("noise_aug_strength", 0.02)),
            fps=int(fps),
            decode_chunk_size=int(opts.get("decode_chunk_size", 2)),
            generator=self._generator(seed),
        )
        return list(out.frames[0])
