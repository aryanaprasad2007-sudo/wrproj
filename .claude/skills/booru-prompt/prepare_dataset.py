"""Stage a generated candidate set for LoRA training, and catalogue it.

Reads generated/aria_lora/manifest.json and produces:

  <ComfyUI input>/aria_lora/*.png + *.txt   the training folder ComfyUI reads
  generated/aria_lora/catalog.csv           Notion-importable database
  generated/aria_lora/contact_sheet.html    visual curation grid
  generated/aria_lora/RUN_LOG.md            human-readable record

CAPTIONING STRATEGY -- this is the decision that makes or breaks a character
LoRA, so it is spelled out rather than buried:

    Caption what you want to be able to CHANGE at inference time.
    Omit what you want BAKED IN to the trigger word.

So each caption is "<trigger>, <framing>, <pose>, <expression>, <background>"
and deliberately OMITS the identity tags (white hair, star ornaments, labcoat,
floating stars). Those are never described, so the model has nowhere to attach
them except the trigger token itself. Caption the white hair and you get a LoRA
that needs "white hair" in every prompt and will happily drop it; omit it and
the trigger carries it.

The trigger is a rare token so it does not collide with anything the base model
already knows.

    py -3.12 .claude/skills/booru-prompt/prepare_dataset.py [--trigger ariakun]
"""

import argparse
import csv
import html
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = REPO_ROOT / "generated" / "aria_lora"
DATASET_DIR = RUN_DIR / "dataset"
COMFY_INPUT = Path(
    r"C:\Users\aware\AppData\Local\Comfy-Desktop\ComfyUI-Shared\input"
)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=True)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trigger", default="ariakun")
    p.add_argument("--folder", default="aria_lora")
    p.add_argument("--only", nargs="*", default=None,
                   help="Filenames to include. Default: everything in manifest.")
    a = p.parse_args()

    mpath = RUN_DIR / "manifest.json"
    if not mpath.exists():
        print("No manifest at " + str(mpath) + " -- run make_dataset.py first.")
        return 1
    manifest = json.loads(mpath.read_text(encoding="utf-8"))

    train_dir = COMFY_INPUT / a.folder
    if train_dir.exists():
        shutil.rmtree(train_dir)
    train_dir.mkdir(parents=True, exist_ok=True)

    rows, staged = [], 0
    for img in manifest["images"]:
        fn = img["filename"]
        if a.only and fn not in a.only:
            continue
        src = DATASET_DIR / fn
        if not src.exists():
            print("missing: " + fn)
            continue

        # Identity tags are deliberately absent -- see module docstring.
        caption = ", ".join([
            a.trigger, img["framing"], img["pose"],
            img["expression"], img["background"],
        ])

        shutil.copy2(src, train_dir / fn)
        (train_dir / (Path(fn).stem + ".txt")).write_text(
            caption, encoding="utf-8")
        staged += 1

        rows.append({
            "Name": Path(fn).stem,
            "File": fn,
            "Seed": img["seed"],
            "Framing": img["framing"],
            "Pose": img["pose"],
            "Expression": img["expression"],
            "Background": img["background"],
            "Caption": caption,
            "Status": "candidate",
            "LocalPath": str(DATASET_DIR / fn),
        })

    # Notion-importable database. Notion creates a DB from a CSV import;
    # images cannot ride along in CSV, so LocalPath is the pointer.
    csv_path = RUN_DIR / "catalog.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                           ["Name"])
        w.writeheader()
        w.writerows(rows)

    # Contact sheet -- curation is a visual judgement, so make it visual.
    tiles = []
    for r in rows:
        tiles.append(
            '<figure><img src="dataset/' + html.escape(r["File"]) + '" '
            'loading="lazy"><figcaption><b>' + html.escape(r["Name"])
            + "</b><br>" + html.escape(r["Framing"]) + " &middot; "
            + html.escape(r["Pose"]) + "<br>" + html.escape(r["Background"])
            + "<br>seed " + str(r["Seed"]) + "</figcaption></figure>")
    sheet = (
        "<!doctype html><meta charset='utf-8'><title>Aria LoRA candidates</title>"
        "<style>body{font-family:system-ui;background:#faf7ff;color:#2a2140;"
        "padding:24px}h1{font-size:20px}main{display:grid;"
        "grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}"
        "figure{margin:0;background:#fff;border:1px solid #e5dcf5;"
        "border-radius:12px;overflow:hidden}img{width:100%;display:block}"
        "figcaption{font-size:11px;padding:8px;line-height:1.4;color:#5b4a7d}"
        "</style><h1>Aria LoRA candidates &mdash; " + str(len(rows))
        + " images</h1><p>Identity tags are held constant; pose, framing, "
        "expression and background vary on purpose.</p><main>"
        + "".join(tiles) + "</main>")
    (RUN_DIR / "contact_sheet.html").write_text(sheet, encoding="utf-8")

    log = [
        "# Aria LoRA run log", "",
        "Created: " + manifest.get("created", "?"),
        "Base model: `" + manifest.get("model", "?") + "`",
        "Trigger word: `" + a.trigger + "`",
        "Staged for training: **" + str(staged) + "** images",
        "Training folder: `" + str(train_dir) + "`", "",
        "## Identity tags (held constant, NOT captioned)", "",
        "```", manifest.get("identity_tags", ""), "```", "",
        "Omitted from captions on purpose so the trigger word absorbs them.",
        "", "## Generation settings", "",
        "```json", json.dumps(manifest.get("settings", {}), indent=2), "```",
        "", "## Files", "",
        "- `dataset/` — the candidate PNGs",
        "- `catalog.csv` — Notion-importable database",
        "- `contact_sheet.html` — open this to curate visually",
        "- `manifest.json` — per-image seed + full prompt",
    ]
    (RUN_DIR / "RUN_LOG.md").write_text("\n".join(log), encoding="utf-8")

    print("staged   : " + str(staged) + " images -> " + str(train_dir))
    print("catalog  : " + str(csv_path))
    print("contact  : " + str(RUN_DIR / "contact_sheet.html"))
    print("run log  : " + str(RUN_DIR / "RUN_LOG.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
