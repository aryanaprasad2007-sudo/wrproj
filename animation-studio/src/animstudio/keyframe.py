"""Stage A: one still keyframe per shot.

This is where character identity is enforced, and it is a still image on
purpose. Every consistency tool worth having -- character LoRAs, IP-Adapter,
ControlNet pose/depth -- is mature for still diffusion and effectively absent
for the small video models that fit in 8 GB. So the pipeline spends its
consistency budget here, then asks the video stage only to *move* the result.

Consequence worth internalising: if a character looks wrong in the finished
clip, the fix is almost always in this file's output, not in the video stage.
Render keyframes alone (`--stage keyframe`) and judge those first.

VRAM notes for the 8 GB target:
  - pipelines are built lazily and shared via `from_pipe`, which rebinds the
    same weights into a different pipeline class with no extra allocation.
    Constructing SDXL text2img *and* img2img the naive way costs ~5 GB twice.
  - ControlNet is only loaded when a shot actually asks for it (+1.4 GB).
  - LoRAs are fully unloaded between shots. diffusers accumulates adapters
    otherwise, so shot 12 would silently carry shot 3's character.
"""
from __future__ import annotations

import logging
import pathlib

from . import hardware

log = logging.getLogger(__name__)

# SDXL was trained at 1024px and degrades below ~640 (anatomy collapses,
# faces smear). 768 is the practical floor on this card; draft mode runs 512
# knowing it looks worse, because draft is judging staging, not faces.
_SDXL_SOFT_MIN = 640

_CONTROLNET_REPOS = {
    "sdxl": {
        "pose":  "thibaud/controlnet-openpose-sdxl-1.0",
        "depth": "diffusers/controlnet-depth-sdxl-1.0-small",
        "canny": "diffusers/controlnet-canny-sdxl-1.0-small",
    },
    "sd15": {
        "pose":  "lllyasviel/control_v11p_sd15_openpose",
        "depth": "lllyasviel/control_v11f1p_sd15_depth",
        "canny": "lllyasviel/control_v11p_sd15_canny",
    },
}

_IPADAPTER = {
    "sdxl": ("h94/IP-Adapter", "sdxl_models", "ip-adapter-plus_sdxl_vit-h.safetensors"),
    "sd15": ("h94/IP-Adapter", "models", "ip-adapter-plus_sd15.safetensors"),
}


class KeyframeRenderer:
    """Builds and caches the SDXL/SD1.5 stack, renders one keyframe per call."""

    def __init__(self, cfg, hw=None):
        self.cfg = cfg
        self.hw = hw or hardware.detect()
        self._txt2img = None
        self._img2img = None
        self._controlnet_pipes = {}     # kind -> pipeline
        self._ip_loaded = False
        self._active_loras = []

    # ------------------------------------------------------------- loading
    def _dtype(self):
        import torch
        return torch.float16 if self.hw.cuda else torch.float32

    def _load_base(self):
        """Load the base checkpoint once. Everything else reuses its weights."""
        if self._txt2img is not None:
            return self._txt2img

        from diffusers import (AutoPipelineForText2Image, StableDiffusionXLPipeline,
                               StableDiffusionPipeline, AutoencoderKL)

        ckpt = self.cfg.base_checkpoint
        if not ckpt:
            raise RuntimeError("models.base_checkpoint is not set in project.yaml")
        path = pathlib.Path(ckpt)
        dtype = self._dtype()

        log.info("loading base checkpoint (%s): %s", self.cfg.base_kind, ckpt)
        if path.suffix == ".safetensors" and path.exists():
            # Single-file checkpoints are what people actually download from
            # Civitai; from_pretrained cannot read them.
            cls = StableDiffusionXLPipeline if self.cfg.base_kind == "sdxl" else StableDiffusionPipeline
            pipe = cls.from_single_file(str(path), torch_dtype=dtype, use_safetensors=True)
        else:
            pipe = AutoPipelineForText2Image.from_pretrained(
                ckpt, torch_dtype=dtype, use_safetensors=True, variant="fp16"
                if self.hw.cuda else None,
            )

        if self.cfg.vae:
            vp = pathlib.Path(self.cfg.vae)
            log.info("loading external VAE: %s", vp.name)
            # The baked SDXL 1.0 VAE produces NaNs in fp16 on some cards; the
            # fp16-fix VAE is the standard remedy and is already on this box.
            pipe.vae = (AutoencoderKL.from_single_file(str(vp), torch_dtype=dtype)
                        if vp.suffix == ".safetensors"
                        else AutoencoderKL.from_pretrained(self.cfg.vae, torch_dtype=dtype))

        pipe.set_progress_bar_config(disable=True)
        hardware.apply_memory_policy(pipe, self.hw)
        self._txt2img = pipe
        return pipe

    def _get_img2img(self):
        """img2img sharing the base weights -- used for carryover shots."""
        if self._img2img is None:
            from diffusers import AutoPipelineForImage2Image
            base = self._load_base()
            # from_pipe rebinds the SAME module objects. No second copy of the
            # unet, which is the whole reason carryover is affordable here.
            self._img2img = AutoPipelineForImage2Image.from_pipe(base)
            self._img2img.set_progress_bar_config(disable=True)
        return self._img2img

    def _get_controlnet(self, kind: str):
        if kind in self._controlnet_pipes:
            return self._controlnet_pipes[kind]

        from diffusers import ControlNetModel, AutoPipelineForText2Image
        repo = _CONTROLNET_REPOS[self.cfg.base_kind].get(kind)
        if not repo:
            raise RuntimeError(f"no ControlNet mapping for {self.cfg.base_kind}/{kind}")

        log.info("loading ControlNet %s: %s", kind, repo)
        cn = ControlNetModel.from_pretrained(repo, torch_dtype=self._dtype(),
                                             use_safetensors=True)
        base = self._load_base()
        pipe = AutoPipelineForText2Image.from_pipe(base, controlnet=cn)
        pipe.set_progress_bar_config(disable=True)
        hardware.apply_memory_policy(pipe, self.hw)
        self._controlnet_pipes[kind] = pipe
        return pipe

    def _ensure_ipadapter(self, pipe):
        if self._ip_loaded:
            return True
        repo, subfolder, weight = _IPADAPTER[self.cfg.base_kind]
        try:
            pipe.load_ip_adapter(repo, subfolder=subfolder, weight_name=weight)
            self._ip_loaded = True
            log.info("IP-Adapter loaded (%s)", weight)
            return True
        except Exception as exc:
            # Non-fatal by design: losing IP-Adapter degrades consistency but
            # the LoRA and trigger token still work, and a half-rendered short
            # is worse than a slightly less consistent one.
            log.warning("IP-Adapter unavailable, continuing without it: %s", exc)
            return False

    def _apply_loras(self, pipe, loras):
        """Swap character LoRAs, unloading whatever was there before.

        diffusers keeps adapters resident across calls. Without the unload,
        rendering Mira then Kettle gives you Kettle-with-Mira's-face -- and it
        looks like a prompt problem, not a state-leak problem, so it costs
        hours to find.
        """
        if self._active_loras == loras:
            return
        try:
            pipe.unload_lora_weights()
        except Exception:
            pass
        self._active_loras = []
        if not loras:
            return

        names = []
        for i, (path, weight) in enumerate(loras):
            p = pathlib.Path(path)
            adapter = f"char{i}"
            pipe.load_lora_weights(str(p.parent), weight_name=p.name, adapter_name=adapter)
            names.append(adapter)
        pipe.set_adapters(names, adapter_weights=[w for _, w in loras])
        self._active_loras = list(loras)
        log.info("LoRA: %s", ", ".join(f"{pathlib.Path(p).stem}@{w:.2f}" for p, w in loras))

    # -------------------------------------------------------------- render
    def render(self, *, prompt, negative, width, height, steps, cfg_scale, seed,
               loras=None, ip_images=None, ip_weight=0.0,
               control=None, control_scale=0.65,
               init_image=None, strength=0.55, out_path=None):
        """Render one keyframe. Returns a PIL image (and writes it if asked)."""
        import torch
        from PIL import Image

        if self.cfg.base_kind == "sdxl" and min(width, height) < _SDXL_SOFT_MIN:
            log.debug("SDXL below %dpx (%dx%d) -- expect soft faces; fine for draft",
                      _SDXL_SOFT_MIN, width, height)

        control = control or {}
        control_kind = next(iter(control), None)

        # Pipeline selection. Carryover (init_image) wins over ControlNet
        # because they cannot be combined without a controlnet-img2img class,
        # and carrying the previous frame is the stronger continuity signal.
        if init_image is not None:
            pipe = self._get_img2img()
            mode = "img2img"
        elif control_kind:
            pipe = self._get_controlnet(control_kind)
            mode = f"controlnet:{control_kind}"
        else:
            pipe = self._load_base()
            mode = "txt2img"

        self._apply_loras(pipe, loras or [])

        kw = dict(
            prompt=prompt,
            negative_prompt=negative or None,
            num_inference_steps=int(steps),
            guidance_scale=float(cfg_scale),
            generator=torch.Generator(device="cpu").manual_seed(int(seed)),
        )

        if ip_images and ip_weight > 0 and self._ensure_ipadapter(pipe):
            pipe.set_ip_adapter_scale(float(ip_weight))
            kw["ip_adapter_image"] = [Image.open(p).convert("RGB") for p in ip_images]
        elif self._ip_loaded:
            # Shots with no character must not inherit the last one's face.
            pipe.set_ip_adapter_scale(0.0)

        if mode == "img2img":
            kw["image"] = init_image.resize((width, height))
            kw["strength"] = float(strength)
        elif mode.startswith("controlnet"):
            kw["image"] = Image.open(control[control_kind]).convert("RGB").resize((width, height))
            kw["controlnet_conditioning_scale"] = float(control_scale)
            kw["width"], kw["height"] = width, height
        else:
            kw["width"], kw["height"] = width, height

        log.info("keyframe [%s] %dx%d steps=%d cfg=%.1f seed=%d",
                 mode, width, height, steps, cfg_scale, seed)
        image = pipe(**kw).images[0]

        if out_path:
            out_path = pathlib.Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(out_path)
        return image

    def unload(self):
        """Release everything. Called before the video stage takes the GPU."""
        self._txt2img = self._img2img = None
        self._controlnet_pipes.clear()
        self._ip_loaded = False
        self._active_loras = []
        hardware.free_vram()
