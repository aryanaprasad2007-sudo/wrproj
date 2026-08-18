"""Check the install and say exactly what to run to fix what is broken.

Written to be useful *before* the venv works, so it imports nothing that is
not either stdlib or explicitly guarded. The failure this exists for is the
one already present on this machine: a working RTX 4060 with a CPU-only torch
build, which reports as "no GPU" everywhere else and reads as a driver problem.

    py -3.12 scripts/doctor.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

OK, WARN, BAD = "[ ok ]", "[warn]", "[FAIL]"


def _v(mod):
    try:
        m = __import__(mod)
        return getattr(m, "__version__", "?")
    except Exception:
        return None


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    problems, warnings = [], []
    print("=" * 66)
    print(" animation-studio doctor")
    print("=" * 66)

    # --- interpreter ----------------------------------------------------
    print(f"\npython      {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < (3, 10):
        problems.append("Python 3.10+ required")

    # --- GPU, independent of torch --------------------------------------
    smi = shutil.which("nvidia-smi")
    driver_gpu = None
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10).stdout.strip()
            driver_gpu = out
            print(f"driver      {out}")
        except Exception as exc:
            print(f"driver      {WARN} nvidia-smi failed: {exc}")
    else:
        print(f"driver      {WARN} nvidia-smi not on PATH")

    # --- torch ----------------------------------------------------------
    tv = _v("torch")
    if tv is None:
        print(f"torch       {BAD} not installed")
        problems.append("torch is missing -- run scripts/setup_env.py")
    else:
        import torch
        cuda_ok = torch.cuda.is_available()
        tag = OK if cuda_ok else BAD
        print(f"torch       {tag} {tv}  cuda_available={cuda_ok}")
        if not cuda_ok:
            if "+cpu" in tv or "+cu" not in tv:
                print("\n" + "!" * 66)
                print(" This is the CPU-ONLY torch build. The GPU is fine; the")
                print(" wheel is wrong. Nothing will use the 4060 until this is")
                print(" replaced. Fix, inside this project's venv:")
                print("\n   pip uninstall -y torch torchvision")
                print("   pip install torch torchvision --index-url \\")
                print("       https://download.pytorch.org/whl/cu126")
                print("!" * 66 + "\n")
                problems.append("torch is the CPU-only build")
            elif driver_gpu:
                problems.append("torch has CUDA support but cannot see the GPU "
                                "(driver/runtime mismatch)")
        else:
            props = torch.cuda.get_device_properties(0)
            gb = props.total_memory / 1024 ** 3
            print(f"gpu         {OK} {props.name}  {gb:.1f} GB")
            if gb < 7.5:
                warnings.append(f"{gb:.1f} GB VRAM -- use preset 'draft' and 512px")

    # --- python deps ----------------------------------------------------
    print()
    required = {
        "diffusers": "core generation",
        "transformers": "text encoders",
        "accelerate": "cpu offload",
        "safetensors": "checkpoint loading",
        "PIL": "image io (pillow)",
        "numpy": "arrays",
        "yaml": "config (pyyaml)",
    }
    optional = {
        "peft": "LoRA training + loading",
        "bitsandbytes": "8-bit optimiser, ~0.3 GB less VRAM when training",
        "imageio": "video writing fallback",
        "psutil": "accurate RAM reporting",
    }
    for mod, why in required.items():
        ver = _v(mod)
        if ver is None:
            print(f"  {BAD} {mod:<16}{why}")
            problems.append(f"missing required package: {mod}")
        else:
            print(f"  {OK} {mod:<16}{ver}")
    for mod, why in optional.items():
        ver = _v(mod)
        print(f"  {OK if ver else WARN} {mod:<16}{ver or 'not installed -- ' + why}")

    # --- external binaries ----------------------------------------------
    print()
    for exe, why, hard in (
        ("ffmpeg", "encoding + assembly", True),
        ("ffprobe", "clip durations", True),
        ("realesrgan-ncnn-vulkan", "upscaling (falls back to Lanczos)", False),
        ("rife-ncnn-vulkan", "interpolation (falls back to ffmpeg)", False),
    ):
        found = shutil.which(exe)
        if found:
            print(f"  {OK} {exe:<24}{found}")
        elif hard:
            print(f"  {BAD} {exe:<24}{why}")
            problems.append(f"{exe} not on PATH")
        else:
            print(f"  {WARN} {exe:<24}{why}")

    # --- project config -------------------------------------------------
    root = pathlib.Path(__file__).resolve().parents[1]
    print()
    cfg_path = root / "config" / "project.yaml"
    if not cfg_path.exists():
        print(f"  {WARN} config/project.yaml missing "
              "(copy config/project.example.yaml)")
        warnings.append("no project.yaml yet")
    elif importlib.util.find_spec("yaml"):
        try:
            from animstudio import config as cfgmod
            cfg = cfgmod.ProjectConfig.load(cfg_path)
            ck = pathlib.Path(cfg.base_checkpoint)
            print(f"  {OK if ck.exists() else BAD} base checkpoint  {ck}")
            if not ck.exists():
                problems.append(f"base_checkpoint does not exist: {ck}")
            print(f"  {OK} video backend    {cfg.video_backend}")
            print(f"  {OK} work root        {cfg.work_root}")
            cast = root / "characters"
            chars = [d.name for d in cast.iterdir()
                     if d.is_dir() and (d / "character.yaml").exists()] if cast.is_dir() else []
            print(f"  {OK if chars else WARN} characters       "
                  f"{', '.join(chars) if chars else 'none defined yet'}")
        except Exception as exc:
            print(f"  {BAD} project.yaml: {exc}")
            problems.append(f"project.yaml invalid: {exc}")

    # --- hardware policy ------------------------------------------------
    try:
        from animstudio import hardware
        hw = hardware.detect()
        print(f"\npolicy      {hw.describe()}")
        print(f"            model_offload={hw.model_offload} "
              f"vae_tiling={hw.vae_tiling} native<={hw.max_native_px}px")
    except Exception:
        pass

    print("\n" + "=" * 66)
    if problems:
        print(f" {len(problems)} problem(s) must be fixed:")
        for p in problems:
            print(f"   - {p}")
    if warnings:
        print(f" {len(warnings)} warning(s):")
        for w in warnings:
            print(f"   - {w}")
    if not problems:
        print(" ready to render.")
    print("=" * 66)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
