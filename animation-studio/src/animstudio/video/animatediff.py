"""AnimateDiff (SD1.5 + motion adapter).

The one backend where the consistency stack reaches *into* the video stage.
AnimateDiff animates a normal SD1.5 unet, so your character LoRA and
IP-Adapter apply to every generated frame rather than only to the keyframe.
For a two-character short that is a real advantage: identity is re-asserted
16 times instead of once and then tracked.

The cost is that it is SD1.5, so it needs `models.base_kind: sd15` and a
SD1.5-trained character LoRA. That is a genuine fork in the project, not a
toggle -- an SDXL LoRA will not load here. Documented in the README under
"Choosing a video backend".

512x512 and 16 frames is the trained configuration. Pushing past ~24 frames
without a context scheduler produces a visible loop seam.
"""
from __future__ import annotations

import logging
import pathlib

from .base import VideoBackend
from .. import hardware

log = logging.getLogger(__name__)

DEFAULT_ADAPTER = "guoyww/animatediff-motion-adapter-v1-5-3"


class AnimateDiffBackend(VideoBackend):
    name = "animatediff"
    frame_multiple = 1
    max_frames = 32
    min_frames = 8
    dim_multiple = 8
    uses_prompt = True
    native = (512, 512)

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import (AnimateDiffPipeline, MotionAdapter,
                               StableDiffusionPipeline, DDIMScheduler)

        if self.cfg.base_kind != "sd15":
            raise RuntimeError(
                "the animatediff backend requires models.base_kind: sd15 "
                f"(project.yaml currently says '{self.cfg.base_kind}'). "
                "Either switch the base checkpoint to an SD1.5 one, or use the "
                "ltx / wan / svd backends with your SDXL checkpoint."
            )

        dtype = torch.float16 if self.hw.cuda else torch.float32
        adapter_id = self.cfg.video_model or DEFAULT_ADAPTER
        log.info("loading motion adapter: %s", adapter_id)
        adapter = MotionAdapter.from_pretrained(adapter_id, torch_dtype=dtype)

        ckpt = pathlib.Path(self.cfg.base_checkpoint)
        if ckpt.suffix == ".safetensors" and ckpt.exists():
            base = StableDiffusionPipeline.from_single_file(str(ckpt), torch_dtype=dtype)
            pipe = AnimateDiffPipeline(
                vae=base.vae, text_encoder=base.text_encoder, tokenizer=base.tokenizer,
                unet=base.unet, motion_adapter=adapter, scheduler=base.scheduler,
                feature_extractor=getattr(base, "feature_extractor", None),
                image_encoder=getattr(base, "image_encoder", None),
            )
        else:
            pipe = AnimateDiffPipeline.from_pretrained(
                self.cfg.base_checkpoint, motion_adapter=adapter, torch_dtype=dtype
            )

        # AnimateDiff was trained with the linear beta schedule and needs
        # clip_sample off; the default SD1.5 scheduler config produces washed
        # out, low-contrast frames that people usually blame on the checkpoint.
        pipe.scheduler = DDIMScheduler.from_config(
            pipe.scheduler.config, clip_sample=False, timestep_spacing="linspace",
            beta_schedule="linear", steps_offset=1,
        )
        pipe.set_progress_bar_config(disable=True)
        hardware.apply_memory_policy(pipe, self.hw)
        self._pipe = pipe
        return pipe

    def generate(self, *, image, prompt, negative, width, height, num_frames,
                 steps, cfg_scale, seed, fps):
        pipe = self._load()
        w, h = self.quantise_dims(width, height)

        kw = dict(
            prompt=prompt,
            negative_prompt=negative or "worst quality, low quality, watermark",
            width=w, height=h,
            num_frames=int(num_frames),
            num_inference_steps=int(steps),
            guidance_scale=float(cfg_scale),
            generator=self._generator(seed),
        )

        # AnimateDiff has no native image input. The keyframe is injected as an
        # IP-Adapter reference instead, which conditions every frame on it --
        # weaker than a true I2V first-frame lock, but it keeps the palette,
        # costume and framing of Stage A, which is what we actually need.
        if image is not None:
            try:
                pipe.load_ip_adapter("h94/IP-Adapter", subfolder="models",
                                     weight_name="ip-adapter-plus_sd15.safetensors")
                pipe.set_ip_adapter_scale(0.7)
                kw["ip_adapter_image"] = image.resize((w, h))
            except Exception as exc:
                log.warning("AnimateDiff keyframe conditioning unavailable (%s); "
                            "this shot will be text-only and may drift", exc)

        out = pipe(**kw)
        return list(out.frames[0])
