"""Stage C2: frame interpolation, generated fps -> delivery fps.

Why this stage exists at all: every backend here generates 12-16 fps because
frame count is the dominant cost in a video diffusion model. Interpolating
12 -> 24 afterwards is roughly free compared to generating 24 natively, and on
animation it looks better than you would expect, because interpolation error
hides in flat cel-shaded regions.

Two interpolators with genuinely different shapes, so the interface carries a
`mode` rather than pretending they are the same:

  rife    mode="frames"        dir of PNGs -> dir of PNGs. Learned, best quality.
                               Needs rife-ncnn-vulkan.exe (Vulkan, no CUDA
                               contention with torch).
  ffmpeg  mode="encode_filter"  no separate pass at all -- returns a filter
                               string that the single encode applies inline.
                               ffmpeg is already installed, so this always
                               works and costs zero extra disk I/O.

The ffmpeg path being a filter rather than a pass is the reason the fallback is
not slower than the "real" one; a naive implementation would encode, filter,
re-extract and re-encode.
"""
from __future__ import annotations

import logging
import math
import pathlib
import shutil
import subprocess

log = logging.getLogger(__name__)


class Interpolator:
    name = "none"
    mode = "none"          # frames | encode_filter | none

    def __init__(self, cfg, hw=None):
        self.cfg = cfg
        self.hw = hw

    def available(self) -> bool:
        return True

    def factor(self, src_fps: int, dst_fps: int) -> int:
        """RIFE doubles. 12 -> 24 is one pass, 12 -> 48 is two."""
        if dst_fps <= src_fps:
            return 1
        return max(1, 2 ** max(0, math.ceil(math.log2(dst_fps / src_fps))))

    def interpolate_dir(self, src_dir, dst_dir, src_fps: int, dst_fps: int):
        raise NotImplementedError

    def encode_filter(self, src_fps: int, dst_fps: int) -> str:
        raise NotImplementedError


class RifeNcnn(Interpolator):
    name = "rife"
    mode = "frames"

    def _binary(self):
        for cand in (
            (self.cfg.raw.get("stages", {}) or {}).get("rife_bin"),
            "rife-ncnn-vulkan",
            str(self.cfg.models_root / "rife" / "rife-ncnn-vulkan.exe"),
        ):
            if not cand:
                continue
            found = shutil.which(str(cand)) or (str(cand) if pathlib.Path(cand).exists() else None)
            if found:
                return found
        return None

    def available(self) -> bool:
        return self._binary() is not None

    def interpolate_dir(self, src_dir, dst_dir, src_fps: int, dst_fps: int):
        src_dir, dst_dir = pathlib.Path(src_dir), pathlib.Path(dst_dir)
        f = self.factor(src_fps, dst_fps)
        if f <= 1:
            return src_dir

        binary = self._binary()
        n_in = len(list(src_dir.glob("*.png")))
        cur = src_dir
        # RIFE ncnn only doubles, so 4x is two chained passes through temp dirs.
        for i in range(int(math.log2(f))):
            out = dst_dir if i == int(math.log2(f)) - 1 else dst_dir.with_name(dst_dir.name + f"_p{i}")
            out.mkdir(parents=True, exist_ok=True)
            # -n is the OUTPUT frame count. 2n-1 (not 2n) because interpolation
            # produces frames strictly between existing ones; asking for 2n
            # makes the binary duplicate the tail frame.
            target = (n_in * 2 ** (i + 1)) - 1
            cmd = [binary, "-i", str(cur), "-o", str(out), "-n", str(target), "-f", "%08d.png"]
            log.info("interpolate[rife] pass %d: %d -> %d frames", i + 1, n_in * 2 ** i, target)
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"rife-ncnn-vulkan failed: {proc.stderr.strip()[:400]}")
            cur = out
        return cur


class FfmpegMinterpolate(Interpolator):
    """Motion-compensated interpolation inside the encode. Always available."""

    name = "ffmpeg"
    mode = "encode_filter"

    def encode_filter(self, src_fps: int, dst_fps: int) -> str:
        if dst_fps <= src_fps:
            return ""
        # mci + aobmc + fps mode is the combination that handles the large
        # per-frame displacement typical of 12 fps generated video. The
        # default (bidir dup) ghosts badly on fast motion.
        return (
            f"minterpolate=fps={dst_fps}:mi_mode=mci:mc_mode=aobmc"
            f":me_mode=bidir:vsbmc=1"
        )


class NoInterpolation(Interpolator):
    name = "none"
    mode = "none"


def build(cfg, hw=None) -> Interpolator:
    want = (cfg.interpolator or "rife").lower()
    if want in ("none", "off"):
        return NoInterpolation(cfg, hw)
    if want == "ffmpeg":
        return FfmpegMinterpolate(cfg, hw)

    r = RifeNcnn(cfg, hw)
    if r.available():
        return r
    log.warning(
        "interpolator 'rife' requested but rife-ncnn-vulkan was not found -- "
        "using ffmpeg minterpolate instead (works, slightly softer on fast motion). "
        "Run scripts/download_models.py --rife to get RIFE."
    )
    return FfmpegMinterpolate(cfg, hw)
