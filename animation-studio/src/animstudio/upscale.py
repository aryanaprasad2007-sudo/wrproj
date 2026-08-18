"""Stage C1: upscale generated frames to delivery resolution.

Deliberately does NOT use the `realesrgan` pip package. That package depends on
`basicsr`, which imports `torchvision.transforms.functional_tensor` -- removed
in torchvision 0.17. On this machine (torchvision 0.27) it fails on import, and
the error names torchvision rather than basicsr, so it reads as a torch problem.

Three implementations, tried in order, all behind one interface:

  1. realesrgan-ncnn-vulkan  a standalone .exe, Vulkan not CUDA. No Python
                             dependency at all, and because it does not use the
                             CUDA context it can run while torch still holds
                             VRAM -- no unload dance between stages.
  2. torch RRDBNet           pure-diffusers-stack weights, no basicsr. Used if
                             the binary is absent but weights are present.
  3. Lanczos                 always available. Not "upscaling" in the learned
                             sense, but honest, instant, and good enough for
                             draft renders.

Swapping the upscaler is `stages.upscaler` in project.yaml.
"""
from __future__ import annotations

import logging
import pathlib
import shutil
import subprocess

log = logging.getLogger(__name__)

# Anime-trained weights. The general x4plus model sharpens line art into
# ringing artefacts; the anime_6B variant is smaller *and* better for this
# project's style, which is an unusual case of both.
NCNN_MODELS = {
    "RealESRGAN_x4plus_anime_6B": "realesrgan-x4plus-anime",
    "RealESRGAN_x4plus": "realesrgan-x4plus",
    "realesr-animevideov3": "realesr-animevideov3",
}


class Upscaler:
    """Base interface. `scale_dir` maps a frame directory to a new one."""

    name = "none"

    def __init__(self, cfg, hw=None):
        self.cfg = cfg
        self.hw = hw

    def available(self) -> bool:
        return True

    def scale_dir(self, src_dir, dst_dir, target_height: int) -> pathlib.Path:
        raise NotImplementedError

    def unload(self):
        pass


class LanczosUpscaler(Upscaler):
    """Always-works fallback. Sharp, fast, adds no detail."""

    name = "lanczos"

    def scale_dir(self, src_dir, dst_dir, target_height: int) -> pathlib.Path:
        from PIL import Image
        src_dir, dst_dir = pathlib.Path(src_dir), pathlib.Path(dst_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)
        frames = sorted(src_dir.glob("*.png"))
        for f in frames:
            im = Image.open(f)
            if im.height >= target_height:
                shutil.copy2(f, dst_dir / f.name)
                continue
            ratio = target_height / im.height
            w = int(round(im.width * ratio / 2)) * 2   # keep even for h264
            im.resize((w, target_height), Image.LANCZOS).save(dst_dir / f.name)
        log.info("upscale[lanczos]: %d frames -> %dp", len(frames), target_height)
        return dst_dir


class NcnnUpscaler(Upscaler):
    """realesrgan-ncnn-vulkan. The recommended path on Windows."""

    name = "realesrgan"

    def _binary(self):
        for cand in (
            self.cfg.raw.get("stages", {}).get("realesrgan_bin"),
            "realesrgan-ncnn-vulkan",
            str(self.cfg.models_root / "realesrgan" / "realesrgan-ncnn-vulkan.exe"),
        ):
            if not cand:
                continue
            found = shutil.which(str(cand)) or (str(cand) if pathlib.Path(cand).exists() else None)
            if found:
                return found
        return None

    def available(self) -> bool:
        return self._binary() is not None

    def scale_dir(self, src_dir, dst_dir, target_height: int) -> pathlib.Path:
        from PIL import Image
        binary = self._binary()
        src_dir, dst_dir = pathlib.Path(src_dir), pathlib.Path(dst_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)

        model = NCNN_MODELS.get(self.cfg.upscale_model, "realesrgan-x4plus-anime")
        # The binary only does fixed integer scales, so run x4 then resize
        # down to the exact target. Upscaling past the target and coming back
        # is also what keeps line art clean -- a direct x2 to 1080p is softer.
        cmd = [binary, "-i", str(src_dir), "-o", str(dst_dir), "-n", model, "-s", "4", "-f", "png"]
        log.info("upscale[realesrgan-ncnn]: %s", model)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"realesrgan-ncnn-vulkan failed: {proc.stderr.strip()[:400]}")

        for f in sorted(dst_dir.glob("*.png")):
            im = Image.open(f)
            if im.height != target_height:
                ratio = target_height / im.height
                w = int(round(im.width * ratio / 2)) * 2
                im.resize((w, target_height), Image.LANCZOS).save(f)
        return dst_dir


class TorchRRDBUpscaler(Upscaler):
    """Real-ESRGAN via a self-contained RRDBNet. No basicsr.

    Only used when the ncnn binary is missing but the .pth weights are on
    disk. Shares the GPU with the diffusion stages, so the caller must have
    freed VRAM first.
    """

    name = "realesrgan-torch"

    def _weights(self):
        p = self.cfg.models_root / "realesrgan" / f"{self.cfg.upscale_model}.pth"
        return p if p.exists() else None

    def available(self) -> bool:
        if self._weights() is None:
            return False
        try:
            import torch  # noqa: F401
            return True
        except ImportError:
            return False

    def scale_dir(self, src_dir, dst_dir, target_height: int) -> pathlib.Path:
        import numpy as np
        import torch
        from PIL import Image
        from .rrdbnet import RRDBNet

        src_dir, dst_dir = pathlib.Path(src_dir), pathlib.Path(dst_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)
        device = "cuda" if (self.hw and self.hw.cuda) else "cpu"

        # anime_6B has 6 blocks; the general model has 23. Reading the wrong
        # count gives a shape-mismatch error that names no file.
        nb = 6 if "6B" in self.cfg.upscale_model else 23
        net = RRDBNet(3, 3, 64, nb, gc=32, scale=4)
        sd = torch.load(self._weights(), map_location="cpu", weights_only=True)
        sd = sd.get("params_ema") or sd.get("params") or sd
        net.load_state_dict(sd, strict=True)
        net.eval().to(device)
        if device == "cuda":
            net.half()

        frames = sorted(src_dir.glob("*.png"))
        with torch.no_grad():
            for f in frames:
                arr = np.asarray(Image.open(f).convert("RGB"), dtype=np.float32) / 255.0
                t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device)
                if device == "cuda":
                    t = t.half()
                out = net(t).clamp(0, 1).float().squeeze(0).permute(1, 2, 0).cpu().numpy()
                im = Image.fromarray((out * 255).round().astype("uint8"))
                if im.height != target_height:
                    ratio = target_height / im.height
                    w = int(round(im.width * ratio / 2)) * 2
                    im = im.resize((w, target_height), Image.LANCZOS)
                im.save(dst_dir / f.name)
        del net
        from . import hardware
        hardware.free_vram()
        log.info("upscale[realesrgan-torch]: %d frames -> %dp", len(frames), target_height)
        return dst_dir


def build(cfg, hw=None) -> Upscaler:
    """Pick an upscaler, degrading loudly rather than silently."""
    want = (cfg.upscaler or "realesrgan").lower()
    if want in ("none", "off"):
        return LanczosUpscaler(cfg, hw)
    if want == "lanczos":
        return LanczosUpscaler(cfg, hw)

    for cls in (NcnnUpscaler, TorchRRDBUpscaler):
        u = cls(cfg, hw)
        if u.available():
            return u

    log.warning(
        "upscaler '%s' requested but neither realesrgan-ncnn-vulkan nor local "
        ".pth weights were found -- falling back to Lanczos. "
        "Run scripts/download_models.py --upscaler to fix.", want,
    )
    return LanczosUpscaler(cfg, hw)
