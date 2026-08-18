"""Train a character LoRA with ComfyUI's built-in trainer. No kohya required.

Graph: CheckpointLoaderSimple -> LoadImageTextDataSetFromFolder ->
       MakeTrainingDataset -> TrainLoraNode -> SaveLoRA

The defaults here are tuned for an 8 GB card, which is genuinely marginal for
SDXL LoRA training. Three flags do the heavy lifting and should not be turned
off on this rig:

    gradient_checkpointing  recompute activations instead of storing them
    offloading              keep idle weights in system RAM, not VRAM
    quantized_backward      lower-precision gradients

Even so, Ollama's qwen2.5:7b MUST be unloaded first -- it pins 4.78 GB and
training will stall exactly like the Animagine load did. `ollama stop qwen2.5:7b`.

Learning rate, rank and step count are CONVENTIONAL STARTING POINTS, not values
measured on this rig. The first run is a probe: check the loss trend and a test
generation before trusting them. Everything is recorded to
generated/aria_lora/training_config.json so a second run can be compared.

    py -3.12 .claude/skills/booru-prompt/train_lora.py --steps 1200
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COMFY = "http://127.0.0.1:8188"
REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = REPO_ROOT / "generated" / "aria_lora"


def _post(path, payload):
    req = urllib.request.Request(
        COMFY + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _get(path, timeout=60):
    with urllib.request.urlopen(COMFY + path, timeout=timeout) as r:
        return json.load(r)


def preflight():
    """Refuse to start a multi-hour run that is going to stall on VRAM."""
    problems = []
    try:
        stats = _get("/system_stats", timeout=15)
        free = stats["devices"][0]["vram_free"] / (1024 ** 3)
        if free < 5.5:
            problems.append(
                "Only {0:.1f} GB VRAM free. Run `ollama stop qwen2.5:7b` "
                "and close other GPU users first.".format(free))
    except urllib.error.URLError:
        problems.append("ComfyUI is not answering on " + COMFY)
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:11434/api/ps", timeout=5) as r:
            loaded = json.load(r).get("models") or []
        if loaded:
            problems.append(
                "Ollama still has loaded: "
                + ", ".join(m["name"] for m in loaded)
                + " -- run `ollama stop <name>`.")
    except Exception:
        pass  # Ollama not running at all is fine.
    return problems


def build(a):
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": a.model}},
        "2": {"class_type": "LoadImageTextDataSetFromFolder",
              "inputs": {"folder": a.folder}},
        "3": {"class_type": "MakeTrainingDataset",
              "inputs": {"images": ["2", 0], "vae": ["1", 2],
                         "clip": ["1", 1], "texts": ["2", 1]}},
        "4": {"class_type": "TrainLoraNode",
              "inputs": {
                  "model": ["1", 0],
                  "latents": ["3", 0],
                  "positive": ["3", 1],
                  "batch_size": a.batch_size,
                  "grad_accumulation_steps": a.grad_accum,
                  "steps": a.steps,
                  "learning_rate": a.lr,
                  "rank": a.rank,
                  "optimizer": a.optimizer,
                  "loss_function": a.loss,
                  "seed": a.seed,
                  "training_dtype": "bf16",
                  "lora_dtype": "bf16",
                  "quantized_backward": True,
                  "algorithm": "LoRA",
                  "gradient_checkpointing": True,
                  "checkpoint_depth": 1,
                  "offloading": True,
                  "existing_lora": "[None]",
                  "bucket_mode": a.bucket_mode,
                  "bypass_mode": False,
              }},
        "5": {"class_type": "SaveLoRA",
              "inputs": {"lora": ["4", 0], "prefix": a.prefix}},
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=True)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="animagine-xl-4.0.safetensors")
    p.add_argument("--folder", default="aria_lora")
    p.add_argument("--steps", type=int, default=1200)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=4)
    p.add_argument("--optimizer", default="AdamW")
    p.add_argument("--loss", default="MSE")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--bucket-mode", action="store_true")
    p.add_argument("--prefix", default="loras/aria_v1")
    p.add_argument("--timeout", type=int, default=4 * 60 * 60)
    p.add_argument("--force", action="store_true",
                   help="Skip the VRAM preflight.")
    a = p.parse_args()

    issues = preflight()
    if issues and not a.force:
        print("PREFLIGHT FAILED:")
        for i in issues:
            print("  - " + i)
        print("Re-run with --force to override.")
        return 1

    folders = _get("/object_info/LoadImageTextDataSetFromFolder")
    avail = folders["LoadImageTextDataSetFromFolder"]["input"]["required"]["folder"][0]
    if isinstance(avail, list) and a.folder not in avail:
        print("Training folder '" + a.folder + "' not visible to ComfyUI.")
        print("It sees: " + (", ".join(avail) if avail else "(none)"))
        print("Run prepare_dataset.py first.")
        return 1

    wf = build(a)
    cfg = {k: v for k, v in vars(a).items()}
    cfg["started"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    res = _post("/prompt", {"prompt": wf, "client_id": "aria-lora-train"})
    if res.get("node_errors"):
        print("Rejected by ComfyUI:")
        print(json.dumps(res["node_errors"], indent=2))
        cfg["result"] = "rejected"
        cfg["node_errors"] = res["node_errors"]
        (RUN_DIR / "training_config.json").write_text(
            json.dumps(cfg, indent=2), encoding="utf-8")
        return 1

    pid = res["prompt_id"]
    print("training queued " + pid)
    print("steps=" + str(a.steps) + " rank=" + str(a.rank)
          + " lr=" + str(a.lr) + " effective_batch="
          + str(a.batch_size * a.grad_accum))
    print("this is a long run -- progress shows in the ComfyUI window")

    start = time.time()
    last = 0.0
    while time.time() - start < a.timeout:
        try:
            hist = _get("/history/" + pid, timeout=30)
        except urllib.error.URLError:
            hist = {}
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {}).get("status_str", "unknown")
            elapsed = time.time() - start
            print("status=" + status + "  "
                  + format(elapsed / 60.0, ".1f") + " min")
            cfg["result"] = status
            cfg["elapsed_seconds"] = round(elapsed, 1)
            cfg["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if status != "success":
                cfg["messages"] = entry.get("status", {}).get("messages")
            (RUN_DIR / "training_config.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8")
            if status == "success":
                print("LoRA saved with prefix: " + a.prefix)
                print("-> ComfyUI-Shared/models/" + a.prefix + "*.safetensors")
            return 0 if status == "success" else 1
        now = time.time() - start
        if now - last > 300:
            print("  ... still training, "
                  + format(now / 60.0, ".0f") + " min elapsed")
            last = now
        time.sleep(15)

    print("TIMEOUT after " + str(a.timeout) + "s -- job may still be running.")
    cfg["result"] = "timeout"
    (RUN_DIR / "training_config.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
