"""Create the project venv with a CUDA-capable torch.

    py -3.12 scripts/setup_env.py

Two deliberate choices worth knowing about:

1. The venv is created OUTSIDE OneDrive (default `~/.venvs/animstudio`).
   This project lives under `OneDrive\\Desktop\\wrproj`, and a venv with a
   CUDA torch is 6-8 GB of files that change on every package operation.
   OneDrive will try to sync all of it, which is slow, burns quota, and can
   lock files mid-install.

2. It does NOT touch the system `py -3.12` environment. That interpreter runs
   the lifestyle tracker (ultralytics + a CPU torch); installing a CUDA torch
   over it would silently change the tracker's runtime. Isolation is the point.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys

DEFAULT_VENV = pathlib.Path.home() / ".venvs" / "animstudio"

# cu126 wheels are the widest-compatibility CUDA build for a 40-series card on
# a current driver. cu121 also works; cu128+ needs a very recent driver.
TORCH_INDEX = "https://download.pytorch.org/whl/cu126"
TORCH_PKGS = ["torch", "torchvision"]

CORE = [
    "diffusers>=0.32",
    "transformers>=4.44",
    "accelerate>=0.34",
    "peft>=0.13",
    "safetensors",
    "sentencepiece",
    "protobuf",
    "pillow",
    "numpy",
    "pyyaml",
    "imageio",
    "imageio-ffmpeg",
    "psutil",
    "tqdm",
]


def run(cmd, **kw):
    print(f"\n$ {' '.join(str(c) for c in cmd)}\n", flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create the animation-studio venv")
    ap.add_argument("--venv", default=str(DEFAULT_VENV))
    ap.add_argument("--cpu", action="store_true",
                    help="install the CPU torch build (no GPU on this machine)")
    ap.add_argument("--skip-torch", action="store_true")
    args = ap.parse_args(argv)

    venv = pathlib.Path(args.venv).expanduser()
    if "OneDrive" in str(venv):
        print("REFUSING: that venv path is inside OneDrive. Multi-GB venvs and "
              "file sync do not mix. Pass --venv with a path outside OneDrive.")
        return 2

    if not venv.exists():
        print(f"creating venv at {venv}")
        run([sys.executable, "-m", "venv", str(venv)])
    else:
        print(f"reusing existing venv at {venv}")

    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([py, "-m", "pip", "install", "--upgrade", "pip", "wheel"])

    if not args.skip_torch:
        if args.cpu:
            run([py, "-m", "pip", "install", *TORCH_PKGS])
        else:
            run([py, "-m", "pip", "install", *TORCH_PKGS, "--index-url", TORCH_INDEX])

    run([py, "-m", "pip", "install", *CORE])

    # bitsandbytes only matters for training and has patchy Windows wheels;
    # a failure here must not fail the whole setup.
    try:
        run([py, "-m", "pip", "install", "bitsandbytes"])
    except subprocess.CalledProcessError:
        print("\nnote: bitsandbytes did not install (optional). Training will "
              "use plain AdamW and about 0.3 GB more VRAM.")

    print("\n" + "=" * 66)
    print(" done. Use this interpreter for everything in this project:\n")
    print(f"   {py}\n")
    print(" verify with:")
    print(f"   {py} scripts/doctor.py")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
