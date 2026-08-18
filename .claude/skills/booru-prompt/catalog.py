"""Sweep every generated image into wrproj and build one catalogue of them all.

ComfyUI writes its API-format prompt into each PNG's tEXt chunks, so an image
carries its own model / seed / sampler / prompt even if nothing logged it at the
time. This reads that back, which is why images generated before any logging
existed can still be catalogued rather than being unlabelled orphans.

Idempotent: re-run it after any batch. Files already in wrproj are not
re-copied, and the catalogue is rebuilt from scratch each time.

    py -3.12 .claude/skills/booru-prompt/catalog.py

Writes:
    generated/CATALOG.csv     Notion-importable (one row per image)
    generated/CATALOG.json    same data, nested prompts intact
"""

import csv
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GEN_DIR = REPO_ROOT / "generated"
COMFY_OUTPUT = Path(
    r"C:\Users\aware\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output"
)

SAMPLERS = ("KSampler", "KSamplerAdvanced", "SamplerCustom")


def read_meta(path):
    """Pull ComfyUI's embedded prompt graph out of the PNG and flatten the bits
    worth putting in a table. Returns {} when the image has no metadata."""
    try:
        from PIL import Image
    except ImportError:
        return {}
    try:
        with Image.open(path) as im:
            info = dict(im.info)
            size = im.size
    except Exception:
        return {}

    out = {"width": size[0], "height": size[1]}
    raw = info.get("prompt")
    if not raw:
        return out
    try:
        graph = json.loads(raw)
    except (ValueError, TypeError):
        return out

    def node(ref):
        if isinstance(ref, list) and ref and str(ref[0]) in graph:
            return graph[str(ref[0])]
        return None

    sampler = None
    for n in graph.values():
        if isinstance(n, dict) and n.get("class_type") in SAMPLERS:
            sampler = n
            break

    for n in graph.values():
        if isinstance(n, dict) and n.get("class_type") == "CheckpointLoaderSimple":
            out["model"] = n["inputs"].get("ckpt_name")
            break

    if sampler:
        ins = sampler.get("inputs", {})
        for k in ("seed", "steps", "cfg", "sampler_name", "scheduler"):
            if k in ins and not isinstance(ins[k], list):
                out[k] = ins[k]
        pos, neg = node(ins.get("positive")), node(ins.get("negative"))
        if pos and "text" in pos.get("inputs", {}):
            t = pos["inputs"]["text"]
            if isinstance(t, str):
                out["positive"] = t
        if neg and "text" in neg.get("inputs", {}):
            t = neg["inputs"]["text"]
            if isinstance(t, str):
                out["negative"] = t
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=True)
    GEN_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Pull anything from ComfyUI's output dir that wrproj does not have.
    have = {p.name for p in GEN_DIR.rglob("*.png")}
    copied = 0
    if COMFY_OUTPUT.exists():
        for src in sorted(COMFY_OUTPUT.rglob("*.png")):
            if src.name in have:
                continue
            shutil.copy2(src, GEN_DIR / src.name)
            have.add(src.name)
            copied += 1

    # 2. Catalogue everything now under generated/.
    rows, rich = [], []
    for p in sorted(GEN_DIR.rglob("*.png")):
        meta = read_meta(p)
        rel = p.relative_to(REPO_ROOT).as_posix()
        pos = (meta.get("positive") or "").replace("\n", " ").strip()
        row = {
            "Name": p.stem,
            "File": p.name,
            "Path": rel,
            "Set": p.parent.name if p.parent != GEN_DIR else "singles",
            "Model": meta.get("model", ""),
            "Seed": meta.get("seed", ""),
            "Steps": meta.get("steps", ""),
            "CFG": meta.get("cfg", ""),
            "Sampler": meta.get("sampler_name", ""),
            "Scheduler": meta.get("scheduler", ""),
            "Width": meta.get("width", ""),
            "Height": meta.get("height", ""),
            "Prompt": pos[:1800],
            "SizeKB": round(p.stat().st_size / 1024),
        }
        rows.append(row)
        rich.append({**row, "positive_full": meta.get("positive", ""),
                     "negative_full": meta.get("negative", "")})

    if not rows:
        print("no images found under " + str(GEN_DIR))
        return 1

    csv_path = GEN_DIR / "CATALOG.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (GEN_DIR / "CATALOG.json").write_text(
        json.dumps(rich, indent=2), encoding="utf-8")

    with_meta = sum(1 for r in rows if r["Model"])
    print("copied in from ComfyUI : " + str(copied))
    print("catalogued             : " + str(len(rows)) + " images ("
          + str(with_meta) + " with embedded metadata)")
    print("csv                    : " + str(csv_path))
    print("json                   : " + str(GEN_DIR / "CATALOG.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
