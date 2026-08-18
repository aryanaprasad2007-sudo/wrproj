"""Wan 2.x image-to-video (1.3 B class). Best motion quality that fits 8 GB.

Slower than LTX by roughly 2-3x, and worth it for hero shots. The pattern this
enables is per-shot backend choice: draft the whole film on `ltx`, then set
`video_backend: wan` for the six shots the audience actually looks at.

Wan ships a separate CLIP image encoder for the I2V conditioning path, so peak
VRAM is higher than the parameter count suggests. On this card model offload is
not optional.
"""
from __future__ import annotations

import logging

from .base import VideoBackend
from .. import hardware

log = logging.getLogger(__name__)

DEFAULT_MODEL = "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"
SMALL_MODEL = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"


class WanBackend(VideoBackend):
    name = "wan"
    frame_multiple = 4
    frame_offset = 1        # 81 frames = ~5 s at 16 fps
    max_frames = 81
    min_frames = 9
    dim_multiple = 16
    uses_prompt = True
    native = (832, 480)

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import WanImageToVideoPipeline, AutoencoderKLWan

        model = self.cfg.video_model or DEFAULT_MODEL
        if "14B" in model and self.hw.usable_vram_gb < 10:
            log.warning(
                "Wan 14B on a %.1f GB card will offload heavily (expect 10+ min/shot). "
                "Set stages.video_model to %s for a usable speed.",
                self.hw.vram_gb, SMALL_MODEL,
            )
        log.info("loading Wan: %s", model)

        # Wan's VAE is numerically fragile in fp16 and produces black frames;
        # it must stay fp32 even when the transformer is bf16.
        vae = AutoencoderKLWan.from_pretrained(model, subfolder="vae", torch_dtype=torch.float32)
        pipe = WanImageToVideoPipeline.from_pretrained(
            model, vae=vae,
            torch_dtype=torch.bfloat16 if self.hw.cuda else torch.float32,
        )
        pipe.set_progress_bar_config(disable=True)
        hardware.apply_memory_policy(pipe, self.hw)
        self._pipe = pipe
        return pipe

    def generate(self, *, image, prompt, negative, width, height, num_frames,
                 steps, cfg_scale, seed, fps):
        pipe = self._load()
        w, h = self.quantise_dims(width, height)
        out = pipe(
            image=image.resize((w, h)),
            prompt=prompt,
            negative_prompt=negative or "static, blurry, low quality, watermark",
            width=w, height=h,
            num_frames=num_frames,
            num_inference_steps=int(steps),
            guidance_scale=float(cfg_scale),
            generator=self._generator(seed),
        )
        return list(out.frames[0])
