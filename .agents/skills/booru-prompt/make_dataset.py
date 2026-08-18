"""Generate a character LoRA training set by varying everything EXCEPT identity.

The point of a character LoRA is to teach the model what is invariant about the
character. That only works if the training set holds the identity tags constant
while varying pose, framing, expression and BACKGROUND. Standardising the
background bakes it into the character -- see tags.json known_failure
"floating-decor-fights-flat-background", which is the specific reason this
script deliberately scatters backgrounds instead of using white for all of them.

Variation is index-derived, not random, so a given --count reproduces the same
set. Writes a manifest.json recording the exact prompt and seed per image; that
manifest is the local record and the source for any external catalogue.

    py -3.12 .claude/skills/booru-prompt/make_dataset.py --count 30
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
REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = REPO_ROOT / "generated" / "aria_lora"
DATASET_DIR = RUN_DIR / "dataset"

COMFY_OUTPUT = Path(
    r"C:\Users\aware\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output"
)
COMFY_INPUT = Path(
    r"C:\Users\aware\AppData\Local\Comfy-Desktop\ComfyUI-Shared\input"
)

# Held constant across every image -- this IS the concept being taught.
IDENTITY = (
    "1girl, solo, white hair, short hair, two side up, "
    "purple star hair ornament, blue eyes, white labcoat, black bowtie, "
    "black pleated skirt, purple star, star (symbol)"
)

# Varied deliberately so the LoRA does not bind them to the character.
POSES = [
    "standing", "sitting", "waving", "arms crossed", "hands on hips",
    "leaning forward", "arms behind back", "pointing at viewer",
    "holding clipboard", "hand on own cheek",
]
FRAMING = ["portrait", "upper body", "cowboy shot", "full body"]
EXPRESSIONS = [
    "open mouth, :d", "smile, closed mouth", "^_^",
    "surprised, open mouth", "smug", "one eye closed, ;d",
]
BACKGROUNDS = [
    "white background, simple background",
    "starry background, purple background",
    "gradient background",
    "simple background, blue background",
    "simple background, pink background",
]

NEGATIVE = (
    "lowres, bad anatomy, bad hands, extra digits, fewer digits, text, error, "
    "cropped, worst quality, low quality, low score, bad score, average score, "
    "signature, watermark, username, blurry, greyscale, monochrome, "
    "multiple views, multiple girls, 2girls"
)
QUALITY = "masterpiece, high score, great score, absurdres"


def _post(path, payload):
    req = urllib.request.Request(
        COMFY + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _get(path):
    with urllib.request.urlopen(COMFY + path, timeout=30) as r:
        return json.load(r)


def variant(i):
    """Index-derived so the set is reproducible. Coprime-ish strides keep the
    combinations from repeating early."""
    return {
        "pose": POSES[i % len(POSES)],
        "framing": FRAMING[(i // 2) % len(FRAMING)],
        "expression": EXPRESSIONS[(i // 3) % len(EXPRESSIONS)],
        "background": BACKGROUNDS[(i // 5) % len(BACKGROUNDS)],
    }


def build(prompt, negative, seed, w, h, model, vae, prefix):
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": model}},
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["1", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": 28, "cfg": 5.0,
                         "sampler_name": "euler_ancestral",
                         "scheduler": "normal", "denoise": 1.0,
                         "model": ["1", 0], "positive": ["3", 0],
                         "negative": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["2", 0]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": prefix, "images": ["7", 0]}},
    }


def wait(pid, timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        try:
            h = _get("/history/" + pid)
        except urllib.error.URLError:
            h = {}
        if pid in h:
            e = h[pid]
            return (e.get("status", {}).get("status_str", "unknown"),
                    e.get("outputs", {}).get("8", {}).get("images", []))
        time.sleep(2)
    return "timeout", []


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=True)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count", type=int, default=30)
    p.add_argument("--model", default="animagine-xl-4.0.safetensors")
    p.add_argument("--vae", default="sdxl_vae_fp16fix.safetensors")
    p.add_argument("--base-seed", type=int, default=770000)
    p.add_argument("--width", type=int, default=832)
    p.add_argument("--height", type=int, default=1216)
    a = p.parse_args()

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)

    manifest = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "purpose": "Aria character LoRA training candidates",
        "model": a.model,
        "identity_tags": IDENTITY,
        "negative": NEGATIVE,
        "settings": {"steps": 28, "cfg": 5.0, "sampler": "euler_ancestral",
                     "scheduler": "normal",
                     "width": a.width, "height": a.height},
        "variation_note": "Backgrounds varied ON PURPOSE. See tags.json "
                          "known_failure floating-decor-fights-flat-background.",
        "images": [],
    }

    ok = 0
    for i in range(a.count):
        v = variant(i)
        prompt = ", ".join([
            IDENTITY, v["framing"], v["pose"], v["expression"],
            v["background"], "looking at viewer", QUALITY,
        ])
        seed = a.base_seed + i
        wf = build(prompt, NEGATIVE, seed, a.width, a.height,
                   a.model, a.vae, "aria_ds")
        try:
            res = _post("/prompt", {"prompt": wf, "client_id": "aria-dataset"})
        except urllib.error.URLError as exc:
            print("[" + str(i) + "] submit failed: " + str(exc))
            continue
        if res.get("node_errors"):
            print("[" + str(i) + "] rejected: " + json.dumps(res["node_errors"]))
            continue

        status, images = wait(res["prompt_id"])
        if status != "success" or not images:
            print("[" + str(i) + "] " + status)
            continue

        for img in images:
            src = COMFY_OUTPUT / img.get("subfolder", "") / img["filename"]
            if not src.exists():
                print("[" + str(i) + "] missing on disk: " + str(src))
                continue
            dst = DATASET_DIR / img["filename"]
            shutil.copy2(src, dst)
            # LoadImage during training reads from ComfyUI's input dir.
            shutil.copy2(src, COMFY_INPUT / img["filename"])
            manifest["images"].append({
                "index": i, "filename": img["filename"], "seed": seed,
                "prompt": prompt, **v,
            })
            ok += 1
        print("[" + str(i + 1) + "/" + str(a.count) + "] " + v["framing"]
              + " / " + v["pose"] + " / " + v["background"])

    (RUN_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print("")
    print("generated " + str(ok) + " images -> " + str(DATASET_DIR))
    print("manifest  -> " + str(RUN_DIR / "manifest.json"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
