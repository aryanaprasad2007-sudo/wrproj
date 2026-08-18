"""Fetch the weights and binaries the pipeline needs.

    py scripts/download_models.py --list
    py scripts/download_models.py --video ltx --controlnet --ipadapter
    py scripts/download_models.py --upscaler --rife

Nothing is downloaded implicitly. Everything here is 1-20 GB and the machine
this targets has ~117 GB free with 55 GB already spent on models, so the
decision of what to pull stays explicit.

Diffusers models go to the HuggingFace cache (shared with any other project on
this machine). The two ncnn binaries are self-contained zips that go under
`models/` in this project, because they are not Python packages and nothing
else will look for them.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

VIDEO_MODELS = {
    "ltx":  ("Lightricks/LTX-Video", "~9 GB", "default; fastest on 8 GB"),
    "wan":  ("Wan-AI/Wan2.1-I2V-14B-480P-Diffusers", "~32 GB",
             "best motion; heavy offload on 8 GB"),
    "wan-small": ("Wan-AI/Wan2.1-T2V-1.3B-Diffusers", "~7 GB",
                  "the Wan that actually fits"),
    "svd":  ("stabilityai/stable-video-diffusion-img2vid-xt", "~9 GB",
             "no text prompt; great natural drift"),
    "animatediff": ("guoyww/animatediff-motion-adapter-v1-5-3", "~1.8 GB",
                    "SD1.5 only; character LoRA applies to every frame"),
}

CONTROLNETS = {
    "sdxl": [
        "thibaud/controlnet-openpose-sdxl-1.0",
        "diffusers/controlnet-depth-sdxl-1.0-small",
        "diffusers/controlnet-canny-sdxl-1.0-small",
    ],
    "sd15": [
        "lllyasviel/control_v11p_sd15_openpose",
        "lllyasviel/control_v11f1p_sd15_depth",
        "lllyasviel/control_v11p_sd15_canny",
    ],
}

# Release zips. Pinned to a known-good tag rather than "latest" so a silent
# upstream rename cannot break setup months from now.
BINARIES = {
    "upscaler": (
        "realesrgan",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
        "realesrgan-ncnn-vulkan-20220424-windows.zip",
        "realesrgan-ncnn-vulkan.exe",
    ),
    "rife": (
        "rife",
        "https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/"
        "rife-ncnn-vulkan-20221029-windows.zip",
        "rife-ncnn-vulkan.exe",
    ),
}


def _hf(repo: str):
    from huggingface_hub import snapshot_download
    print(f"\n--- {repo}")
    # allow_patterns excludes the .bin duplicates that many repos ship
    # alongside safetensors; pulling both doubles the download for nothing.
    path = snapshot_download(
        repo_id=repo,
        ignore_patterns=["*.bin", "*.pth", "*.onnx", "*.msgpack", "*.h5"],
    )
    print(f"    -> {path}")
    return path


def _binary(key: str):
    import urllib.request
    name, url, exe = BINARIES[key]
    dest = ROOT / "models" / name
    if (dest / exe).exists():
        print(f"--- {name}: already present ({dest / exe})")
        return
    dest.mkdir(parents=True, exist_ok=True)
    zpath = dest / "download.zip"
    print(f"\n--- {name}\n    {url}")
    urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest)
    zpath.unlink()

    # These zips sometimes contain a single top-level folder and sometimes
    # not, depending on the release. Flatten so the path is predictable.
    if not (dest / exe).exists():
        for sub in dest.iterdir():
            if sub.is_dir() and (sub / exe).exists():
                for item in sub.iterdir():
                    shutil.move(str(item), str(dest / item.name))
                sub.rmdir()
                break
    print(f"    -> {dest / exe}")
    if not (dest / exe).exists():
        print(f"    ! {exe} not found after extraction -- check {dest}")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Download models for animation-studio")
    ap.add_argument("--list", action="store_true", help="show options and sizes")
    ap.add_argument("--video", choices=sorted(VIDEO_MODELS), help="video backend weights")
    ap.add_argument("--controlnet", choices=["sdxl", "sd15"], help="pose/depth/canny set")
    ap.add_argument("--ipadapter", action="store_true", help="IP-Adapter + CLIP vision")
    ap.add_argument("--base", choices=["sdxl", "sd15"], help="a base checkpoint, if you have none")
    ap.add_argument("--upscaler", action="store_true", help="realesrgan-ncnn-vulkan")
    ap.add_argument("--rife", action="store_true", help="rife-ncnn-vulkan")
    ap.add_argument("--all-post", action="store_true", help="both ncnn binaries")
    args = ap.parse_args(argv)

    if args.list or len(sys.argv) == 1:
        print("\nvideo backends (--video NAME)")
        for k, (repo, size, note) in VIDEO_MODELS.items():
            print(f"  {k:<12}{size:<9}{repo}\n              {note}")
        print("\nother")
        print("  --controlnet sdxl|sd15   ~2.5 GB   pose + depth + canny")
        print("  --ipadapter              ~2.5 GB   face/style reference conditioning")
        print("  --upscaler               ~25 MB    realesrgan-ncnn-vulkan.exe")
        print("  --rife                   ~40 MB    rife-ncnn-vulkan.exe")
        print("  --base sdxl|sd15         ~7 GB     only if you have no checkpoint\n")
        return 0

    if args.video:
        _hf(VIDEO_MODELS[args.video][0])
    if args.controlnet:
        for repo in CONTROLNETS[args.controlnet]:
            _hf(repo)
    if args.ipadapter:
        _hf("h94/IP-Adapter")
    if args.base == "sdxl":
        _hf("stabilityai/stable-diffusion-xl-base-1.0")
    elif args.base == "sd15":
        _hf("runwayml/stable-diffusion-v1-5")
    if args.upscaler or args.all_post:
        _binary("upscaler")
    if args.rife or args.all_post:
        _binary("rife")

    print("\ndone. Verify with: python scripts/doctor.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
