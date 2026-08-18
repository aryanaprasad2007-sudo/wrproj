"""Hardware probe and memory policy.

Every stage asks this module what it is allowed to do rather than hardcoding
`enable_model_cpu_offload()` calls. The same code has to run on the 8 GB 4060
this project targets *and* survive being moved to a bigger card without a
rewrite, so the policy lives in one place and the stages read it.

The numbers below are budgets, not measurements: `usable_vram_gb` deliberately
under-reports, because Windows WDDM reserves a slice of VRAM for the desktop
compositor and a pipeline that plans for the full 8 GB will OOM mid-denoise.
"""
from __future__ import annotations

import dataclasses
import logging
import shutil
import subprocess

log = logging.getLogger(__name__)

# Windows keeps ~0.6-1.0 GB of an 8 GB card for the desktop compositor even
# with no apps open. Planning against nominal VRAM is how you get an OOM at
# step 27 of 30, which is the most expensive possible moment to fail.
_WDDM_RESERVE_GB = 0.9


@dataclasses.dataclass(frozen=True)
class Hardware:
    gpu_name: str
    vram_gb: float          # nominal, as reported by the driver
    usable_vram_gb: float   # what we actually plan against
    system_ram_gb: float
    cuda: bool

    # ---- policy: derived, not configured -------------------------------
    @property
    def tier(self) -> str:
        """Coarse capability bucket. Stages branch on this, not on raw GB."""
        if not self.cuda:
            return "cpu"
        if self.usable_vram_gb < 6:
            return "tight"     # 6 GB cards: sequential offload, 512px only
        if self.usable_vram_gb < 11:
            return "low"       # the 4060 lands here: model offload + tiling
        if self.usable_vram_gb < 20:
            return "mid"
        return "high"

    @property
    def sequential_offload(self) -> bool:
        """Move weights module-by-module. Correct under 6 GB, ruinous above.

        Sequential offload streams every submodule across PCIe on each forward
        pass, roughly 4-6x slower than model offload. Last resort, not default.
        """
        return self.tier == "tight"

    @property
    def model_offload(self) -> bool:
        """Keep one component on the GPU at a time (text encoder, unet, vae).

        Highest-value setting on an 8 GB card: SDXL's two text encoders are
        ~1.4 GB that sit idle for the entire denoise loop.
        """
        return self.tier in ("tight", "low")

    @property
    def vae_tiling(self) -> bool:
        """Decode latents in tiles.

        VAE decode is the memory spike of the whole run, not the denoise loop.
        Decoding video latents allocates a full-resolution float tensor per
        frame at once. Tiling trades a little speed for a ceiling that does
        not scale with frame count.
        """
        return self.tier in ("tight", "low", "mid")

    @property
    def attention_slicing(self) -> bool:
        return self.tier == "tight"

    @property
    def dtype(self) -> str:
        return "float16" if self.cuda else "float32"

    @property
    def max_native_px(self) -> int:
        """Longest edge we will generate natively, before upscaling."""
        return {"cpu": 384, "tight": 512, "low": 768, "mid": 1024}.get(self.tier, 1024)

    def describe(self) -> str:
        if not self.cuda:
            return f"CPU only ({self.system_ram_gb:.0f} GB RAM) - generation will be extremely slow"
        return (
            f"{self.gpu_name} | {self.vram_gb:.1f} GB VRAM "
            f"({self.usable_vram_gb:.1f} GB usable) | {self.system_ram_gb:.0f} GB RAM "
            f"| tier={self.tier}"
        )


def _nvidia_smi_vram_gb():
    """Read VRAM without importing torch.

    Used by `doctor` so it can report the GPU even when the venv is broken.
    The failure mode we most want a diagnostic for is "torch is the CPU
    build", and a probe that needs torch cannot report that.
    """
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip().splitlines()
        return int(out[0].strip()) / 1024.0
    except Exception:
        return None


def _system_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1024 ** 3
    except Exception:
        pass
    try:  # stdlib fallback, Windows-safe
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        st = _MS()
        st.dwLength = ctypes.sizeof(_MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return st.ullTotalPhys / 1024 ** 3
    except Exception:
        return 0.0


def detect() -> Hardware:
    """Probe the machine. Never raises: a bad probe degrades to CPU tier."""
    gpu_name, vram, cuda = "unknown", 0.0, False
    try:
        import torch
        if torch.cuda.is_available():
            cuda = True
            gpu_name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
    except Exception as exc:  # torch missing, or the CPU-only build
        log.debug("torch probe failed: %s", exc)

    if not cuda:
        smi = _nvidia_smi_vram_gb()
        if smi:
            # A GPU the driver can see but torch cannot means the wrong torch
            # build, the single most common setup failure on this machine.
            log.warning(
                "nvidia-smi reports a %.1f GB GPU but torch cannot use CUDA. "
                "This is almost always a CPU-only torch build. Run scripts/doctor.py",
                smi,
            )
            vram = smi

    return Hardware(
        gpu_name=gpu_name,
        vram_gb=vram,
        usable_vram_gb=max(0.0, vram - _WDDM_RESERVE_GB) if cuda else 0.0,
        system_ram_gb=_system_ram_gb(),
        cuda=cuda,
    )


def apply_memory_policy(pipe, hw: Hardware, allow_offload: bool = True) -> None:
    """Attach the memory policy to a diffusers pipeline.

    Order matters. `enable_model_cpu_offload` installs hooks that move modules
    to CUDA on demand; calling `.to("cuda")` afterwards defeats it, and calling
    both offload variants together raises. This is the only place allowed to
    touch device placement.
    """
    if not hw.cuda:
        return

    if allow_offload and hw.sequential_offload:
        pipe.enable_sequential_cpu_offload()
        log.info("memory: sequential CPU offload (slow, sub-6 GB card)")
    elif allow_offload and hw.model_offload:
        pipe.enable_model_cpu_offload()
        log.info("memory: model CPU offload")
    else:
        pipe.to("cuda")

    if hw.vae_tiling:
        for fn in ("enable_vae_tiling", "enable_vae_slicing"):
            if hasattr(pipe, fn):
                try:
                    getattr(pipe, fn)()
                except Exception:
                    pass
        log.info("memory: tiled + sliced VAE decode")

    if hw.attention_slicing and hasattr(pipe, "enable_attention_slicing"):
        pipe.enable_attention_slicing()

    # PyTorch 2.x routes to its own fused SDPA kernel (flash / mem-efficient)
    # automatically, so xformers is not a dependency. If it happens to be
    # installed the user put it there deliberately, so honour it.
    try:
        import xformers  # noqa: F401
        if hasattr(pipe, "enable_xformers_memory_efficient_attention"):
            pipe.enable_xformers_memory_efficient_attention()
            log.info("memory: xformers attention")
    except ImportError:
        pass


def free_vram() -> None:
    """Drop cached blocks between stages.

    Between Stage A (SDXL, ~7 GB peak) and Stage B (video model) the allocator
    still holds SDXL's arena. Without this the video model OOMs even though
    nothing references SDXL any more.
    """
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _hw = detect()
    print(_hw.describe())
    print(
        f"  model_offload={_hw.model_offload} vae_tiling={_hw.vae_tiling} "
        f"seq_offload={_hw.sequential_offload} native_px<={_hw.max_native_px}"
    )
