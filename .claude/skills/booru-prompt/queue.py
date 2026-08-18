"""Send a booru-tag prompt to the local ComfyUI and return the generated PNG.

Project-local by design: lives in wrproj/.claude/skills/booru-prompt/ so the
skill, its data, and its outputs all sit inside the repo rather than in AppData.
See SKILL.md "Where this lives and why" and "Rebuilding this skill".

Stdlib only (urllib/json/argparse) — no pip install, no venv. Run it with the
house interpreter:

    py -3.12 .claude/skills/booru-prompt/queue.py --positive "1girl, solo, ..."

ComfyUI owns the model and writes the PNG into its own output directory; this
script then copies it into wrproj/generated/ so the artifact lives with the
project. Both paths are printed.
"""

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COMFY = "http://127.0.0.1:8188"

# wrproj/.claude/skills/booru-prompt/queue.py -> wrproj
REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "generated"

# ComfyUI Desktop's shared output dir (where SaveImage actually writes).
COMFY_OUTPUT = Path(
    r"C:\Users\aware\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output"
)

# Defaults are Animagine XL 4.0's published settings, not base SDXL's.
# Anime fine-tunes are far more prompt-adherent, so high cfg oversaturates
# rather than improving accuracy. See SKILL.md "Measured on this rig".
DEFAULTS = {
    "model": "animagine-xl-4.0.safetensors",
    "vae": "sdxl_vae_fp16fix.safetensors",
    "cfg": 5.0,
    "steps": 28,
    "sampler": "euler_ancestral",
    "scheduler": "normal",
    "width": 1024,
    "height": 1024,
}

QUALITY_SUFFIX = "masterpiece, high score, great score, absurdres"

NEGATIVE = (
    "lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, "
    "fewer digits, cropped, worst quality, low quality, low score, bad score, "
    "average score, signature, watermark, username, blurry, greyscale, "
    "monochrome, multiple views"
)


def _post(path, payload):
    req = urllib.request.Request(
        COMFY + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _get(path):
    with urllib.request.urlopen(COMFY + path, timeout=30) as r:
        return json.load(r)


def available_checkpoints():
    info = _get("/object_info/CheckpointLoaderSimple")
    return info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]


def build_workflow(a, positive):
    """API-format graph. Node ids are referenced by output parsing below --
    if you renumber, update the SaveImage id in wait_for() too."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": a.model}},
        "2": {"class_type": "VAELoader",
              "inputs": {"vae_name": a.vae}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": positive, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": a.negative, "clip": ["1", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": a.width, "height": a.height,
                         "batch_size": a.batch}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": a.seed, "steps": a.steps, "cfg": a.cfg,
                         "sampler_name": a.sampler, "scheduler": a.scheduler,
                         "denoise": 1.0, "model": ["1", 0],
                         "positive": ["3", 0], "negative": ["4", 0],
                         "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["2", 0]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": a.prefix, "images": ["7", 0]}},
    }


def wait_for(prompt_id, timeout=600):
    started = time.time()
    while time.time() - started < timeout:
        try:
            hist = _get("/history/" + prompt_id)
        except urllib.error.URLError:
            hist = {}
        if prompt_id in hist:
            entry = hist[prompt_id]
            status = entry.get("status", {}).get("status_str", "unknown")
            images = entry.get("outputs", {}).get("8", {}).get("images", [])
            return status, images, time.time() - started
        time.sleep(2)
    return "timeout", [], time.time() - started


def main():
    # line_buffering so progress reaches a caller that captured stdout to a
    # file/pipe. Without it Python block-buffers when stdout is not a TTY and a
    # 3-minute generation looks indistinguishable from a hang.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=True)

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--positive", required=True,
                   help="Booru tags, comma-separated. Lead with 1girl/1boy + solo.")
    p.add_argument("--negative", default=NEGATIVE)
    p.add_argument("--model", default=DEFAULTS["model"])
    p.add_argument("--vae", default=DEFAULTS["vae"])
    p.add_argument("--seed", type=int, default=0,
                   help="0 = time-derived. Lock it to hold a face across runs.")
    p.add_argument("--steps", type=int, default=DEFAULTS["steps"])
    p.add_argument("--cfg", type=float, default=DEFAULTS["cfg"])
    p.add_argument("--sampler", default=DEFAULTS["sampler"])
    p.add_argument("--scheduler", default=DEFAULTS["scheduler"])
    p.add_argument("--width", type=int, default=DEFAULTS["width"])
    p.add_argument("--height", type=int, default=DEFAULTS["height"])
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--prefix", default="booru")
    p.add_argument("--no-quality", action="store_true",
                   help="Skip the auto-appended quality suffix.")
    a = p.parse_args()

    if a.seed == 0:
        a.seed = int(time.time()) % 2_147_483_647

    try:
        ckpts = available_checkpoints()
    except urllib.error.URLError:
        print("ComfyUI is not answering on " + COMFY)
        print("Start the Comfy Desktop app, then retry.")
        return 1

    if a.model not in ckpts:
        print("Checkpoint not found: " + a.model)
        print("ComfyUI currently sees: " + ", ".join(ckpts))
        print("(A model added while ComfyUI is open needs a refresh -- press R.)")
        return 1

    positive = a.positive
    if not a.no_quality and "masterpiece" not in positive:
        positive = positive.rstrip(", ") + ", " + QUALITY_SUFFIX

    wf = build_workflow(a, positive)
    res = _post("/prompt", {"prompt": wf, "client_id": "booru-prompt-skill"})

    if res.get("node_errors"):
        print("Rejected by ComfyUI:")
        print(json.dumps(res["node_errors"], indent=2))
        return 1

    prompt_id = res["prompt_id"]
    print("queued " + prompt_id + "  seed=" + str(a.seed))

    status, images, elapsed = wait_for(prompt_id)
    print("status=" + status + "  " + format(elapsed, ".1f") + "s")
    if status != "success":
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for img in images:
        src = COMFY_OUTPUT / img.get("subfolder", "") / img["filename"]
        print("  comfy : " + str(src))
        if src.exists():
            dst = OUT_DIR / img["filename"]
            shutil.copy2(src, dst)
            print("  wrproj: " + str(dst))
        else:
            print("  (not found on disk -- ComfyUI output dir may have moved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
