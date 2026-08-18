"""Generate Aria's face at scale, unattended, overnight.

Reads the tag database in aria_face.json, expands it into thousands of distinct
booru prompts, and feeds them to the local ComfyUI until a wall-clock deadline.
Leaves behind a contact sheet to curate from in the morning.

    py -3.12 .claude/skills/booru-prompt/face_lab.py --until 07:00

Design constraints, all of them learned the hard way (see aria_face.json):

* IDENTITY IS A CONSTANT. The identity block is prepended verbatim to every
  prompt and there is no flag to vary it. Two earlier sets of Aria art came out
  as two different girls because several identity-carrying tags changed at once;
  making identity un-varyable is the structural fix, not a stylistic choice.

* IT MUST SURVIVE THE NIGHT ALONE. Nobody is awake to restart it. So: ComfyUI
  dropping out is waited on rather than fatal, every completed image is recorded
  to a resumable ledger before the next is queued, and the run is ordered by
  value so a crash at 03:00 still leaves the most useful images done.

* IT MUST GIVE BACK VRAM. Ollama's qwen2.5:7b (Aria herself) pins 4.78 GB with
  keep_alive:-1 and the tracker reloads her every ~120 s, which drags generation
  from ~20 s to ~60 s. A one-shot `ollama stop` before bed is therefore useless
  over eight hours -- it has to be repeated on a timer.

Stdlib only, no venv, no pip. Console is cp1252, hence the stdout reconfigure.
"""

import argparse
import csv
import datetime as dt
import hashlib
import html
import itertools
import json
import random
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COMFY = "http://127.0.0.1:8188"

# wrproj/.claude/skills/booru-prompt/face_lab.py -> wrproj
REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = Path(__file__).resolve().parent / "aria_face.json"
OUT_DIR = REPO_ROOT / "generated" / "aria_face"

COMFY_OUTPUT = Path(
    r"C:\Users\aware\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output"
)

# Aria's own model. Stopping her frees the VRAM this run needs; she reloads by
# herself on the tracker's next ping, so nothing has to be undone afterwards.
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_EVERY = 300.0

# Negative terms that must step aside when the positive prompt asks for them.
# The negative deliberately carries the other Aria's signature tags to stop the
# model drifting toward her -- but a prompt that explicitly wants headphones
# would otherwise fight itself, and the model resolves that contradiction by
# quietly dropping BOTH.
NEGATIVE_YIELDS = {
    "headphones": ("headphones",),
    "purple eyes": ("purple eyes",),
    "hands": ("hand on own cheek", "hands on own cheeks", "index finger raised",
              "v over eye", "peace sign", "holding pen", "hands up"),
    "arms": ("hand on own cheek", "hands on own cheeks", "index finger raised",
             "v over eye", "peace sign", "holding pen", "hands up"),
    # 'blurry' as a quality complaint vs 'blurry background' as a deliberate
    # depth-of-field request. Same token, opposite intents -- caught in the
    # 2026-08-18 dry run, where deep-tier prompts asked for a bokeh background
    # while the negative was still suppressing the word.
    "blurry": ("blurry background",),
    # Suppressed by default to hold bust framing; withdrawn if a prompt
    # ever genuinely asks for a tight head shot.
    "close-up": ("close-up",),
    "portrait": ("portrait",),
    "face focus": ("face focus",),
}


# --------------------------------------------------------------------------
# ComfyUI


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


def comfy_alive():
    try:
        _get("/system_stats")
        return True
    except Exception:
        return False


def wait_for_comfy(deadline, quiet_for=30.0):
    """Block until ComfyUI answers again, or the run deadline passes.

    Deliberately not fatal. A ComfyUI restart, a driver hiccup or a GPU reset at
    04:00 should cost the run a few minutes, not the whole night.
    """
    warned = False
    while time.time() < deadline:
        if comfy_alive():
            if warned:
                log("ComfyUI is back.")
            return True
        if not warned:
            log("ComfyUI is not answering -- waiting for it to come back.")
            warned = True
        time.sleep(quiet_for)
    return False


def build_workflow(job, render):
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": render["model"]}},
        "2": {"class_type": "VAELoader",
              "inputs": {"vae_name": render["vae"]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": job["positive"], "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": job["negative"], "clip": ["1", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": job["width"], "height": job["height"],
                         "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": job["seed"], "steps": render["steps"],
                         "cfg": render["cfg"],
                         "sampler_name": render["sampler"],
                         "scheduler": render["scheduler"],
                         "denoise": 1.0, "model": ["1", 0],
                         "positive": ["3", 0], "negative": ["4", 0],
                         "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["2", 0]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": job["prefix"], "images": ["7", 0]}},
    }


def await_result(prompt_id, timeout=420):
    started = time.time()
    while time.time() - started < timeout:
        try:
            hist = _get("/history/" + prompt_id)
        except Exception:
            hist = {}
        if prompt_id in hist:
            entry = hist[prompt_id]
            status = entry.get("status", {}).get("status_str", "unknown")
            images = entry.get("outputs", {}).get("8", {}).get("images", [])
            return status, images, time.time() - started
        time.sleep(1.5)
    return "timeout", [], time.time() - started


# --------------------------------------------------------------------------
# Prompt construction

# Tags that cannot both be true of one picture. A diffusion model does not
# refuse a contradiction, it averages it -- which is how "looking at viewer"
# plus "looking away" becomes a girl facing nowhere in particular, and why 10%
# of the first queue would have rendered mush.
#
# The `keep` field is a claim about where INTENT lives, not about the tags:
#
#   "last"  -- the earlier tag was boilerplate. Every framing string ends in
#              "looking at viewer"; an axis that names a different gaze is the
#              deliberate request and must win.
#   "first" -- the earlier tag came from the more deliberate source. Expression
#              is chosen before decoration, so a closed-eyed laugh outranks a
#              sparkle bolted on two axes later.
EXCLUSIVE_GROUPS = [
    ("gaze", "last", ("looking at viewer", "looking away", "looking to the side",
                      "looking back", "looking up", "looking down",
                      "looking afar")),
    ("eye aperture", "first", ("closed eyes", "half-closed eyes", "wide-eyed",
                               "one eye closed")),
    ("mouth", "first", ("open mouth", "closed mouth", "parted lips")),
    # Which side the camera is on. "from above"/"from below" are deliberately
    # ABSENT: height composes with side ("from behind, from below" is a real
    # shot), so grouping them would delete legitimate camera work.
    ("view", "first", ("from side", "from behind", "from front", "straight-on")),
    # What she is sitting on -- and nothing more. "leaning back"/"leaning
    # forward"/"stretching" are NOT here: you can lean back while sitting, and
    # 23 of the 100 conflicts the first scene audit reported were exactly that
    # false positive. Only the seat itself is exclusive, and the activity axis
    # (whose whole job is posture) outranks a framing that merely says "sitting".
    ("seat", "last", ("sitting", "sitting on floor", "standing")),
]

# Shut lids hide whatever the eyes were going to do, so this is suppression, not
# rivalry -- there is no winner to pick.
#
# Aperture and pupil SHAPE are otherwise independent: "wide-eyed, star-shaped
# pupils" is a legitimate, common pairing, and the first version of the conflict
# audit wrongly flagged it. Widening this tuple to cover aperture would delete
# the single most characteristic tag Aria has.
EYES_SHUT = "closed eyes"
HIDDEN_BY_SHUT_EYES = ("star-shaped pupils", "heart-shaped pupils",
                       "symbol-shaped pupils", "sparkling eyes", "glowing eyes",
                       "very detailed eyes", "detailed eyes",
                       "eyes visible through hair")


def resolve_conflicts(tags):
    """Drop tags contradicted by a tag that outranks them.

    Runs on the flattened tag list rather than on the chunks, because a conflict
    lives BETWEEN chunks -- framing supplies one half and an axis the other, so
    it is invisible while each is still its own string.
    """
    out = list(tags)
    for _name, keep, members in EXCLUSIVE_GROUPS:
        hits = [i for i, t in enumerate(out) if t in members]
        if len(hits) < 2:
            continue
        winner = hits[0] if keep == "first" else hits[-1]
        out = [t for i, t in enumerate(out) if i == winner or i not in hits]
    if EYES_SHUT in out:
        out = [t for t in out if t not in HIDDEN_BY_SHUT_EYES]
    return out



def tune_negative(positive, base, portrait_add, tight):
    """Drop negative terms the positive prompt explicitly asks for.

    Without this a prompt containing 'headphones' meets a negative containing
    'headphones' and the model splits the difference by rendering neither
    cleanly -- the silent-drop failure the whole skill exists to prevent, only
    self-inflicted.
    """
    terms = [t.strip() for t in base.split(",") if t.strip()]
    if tight:
        terms += [t.strip() for t in portrait_add.split(",") if t.strip()]

    low = positive.lower()
    keep = []
    for term in terms:
        wanted = False
        for neg_term, triggers in NEGATIVE_YIELDS.items():
            if term == neg_term and any(t in low for t in triggers):
                wanted = True
                break
        if not wanted:
            keep.append(term)
    return ", ".join(keep)


def assemble(db, parts, seed, tier, label, prefix, extra_neg="", size=None):
    """Identity first, always, byte-identical. Everything else is decoration."""
    chunks = [db["identity"]["tags"]]
    chunks += [p for p in parts if p and p.strip()]
    chunks.append(db["quality_suffix"])

    # Flatten to individual tags, keeping first occurrence. Identity is first in
    # and therefore survives verbatim -- the frozen-identity guarantee is what
    # makes it safe to let everything downstream be edited.
    tags, seen = [], set()
    for chunk in chunks:
        for tag in chunk.split(","):
            tag = tag.strip().strip(",")
            if tag and tag not in seen:
                seen.add(tag)
                tags.append(tag)
    positive = ", ".join(resolve_conflicts(tags))

    tight = "close-up" in positive or "portrait" in positive
    negative = tune_negative(
        positive, db["negative"]["base"], db["negative"]["portrait_add"], tight
    )
    if extra_neg:
        negative = extra_neg + ", " + negative
    w, h = size if size else (db["render"]["width"], db["render"]["height"])
    return {
        "tier": tier,
        "label": label,
        "positive": positive,
        "negative": negative,
        "seed": seed,
        "prefix": prefix,
        "width": w,
        "height": h,
    }


def dedupe(jobs, render, seen):
    """Drop jobs already claimed, stamping each survivor with its key.

    Runs PER TIER and before interleave(), which is load-bearing rather than
    tidy: braiding raw lists and deduping afterwards lets a tier with many
    internal duplicates lose most of its slots to its partner. On 2026-08-18
    that turned an intended 1:1 sweep/scene braid into an actual 214:655.
    """
    out = []
    for job in jobs:
        k = job_key(job, render)
        if k in seen:
            continue
        seen.add(k)
        job["key"] = k
        out.append(job)
    return out


def job_key(job, render):
    """Identity of a job for resume purposes: prompt + seed + render settings.

    Deliberately excludes tier/label, so re-labelling the tiers later does not
    orphan a night's worth of finished work.
    """
    blob = "|".join([
        job["positive"], job["negative"], str(job["seed"]),
        render["model"], str(job["width"]), str(job["height"]),
        str(render["cfg"]), str(render["steps"]), render["sampler"],
        render["scheduler"],
    ])
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# The three tiers, in descending order of value


def tier_canon(db):
    """Aria's ten real emotions, every candidate reading, on locked seeds.

    First because it is the thing actually asked for -- a face per emotion for
    the avatar -- and because locked seeds make the ten comparable to each
    other. Everything after this is breadth.
    """
    jobs = []
    frame = db["framing"]["avatar_locked"]
    bg = "white background, simple background"
    for seed in db["seeds"]["identity_locks"]:
        for emotion, readings in db["canon_emotions"].items():
            if not isinstance(readings, list):
                continue
            for i, reading in enumerate(readings):
                jobs.append(assemble(
                    db, [frame, reading, bg, "even lighting"],
                    seed, "canon", "{}#{}".format(emotion, i + 1),
                    "ariaface_canon",
                ))
    return jobs


def tier_sweep(db):
    """The same ten emotions across framings, lighting and backgrounds.

    Answers 'which camera and light flatter this face', which is a different
    question from 'which tags render this mood' and needs the mood held still.
    """
    jobs = []
    seed = db["seeds"]["identity_locks"][0]
    frames = db["framing"]["variants"]
    lights = ["even lighting", "soft lighting", "studio lighting",
              "rim light", "high key lighting", "cinematic lighting"]
    # dict.fromkeys, not a bare slice. `axes.background` repeats
    # "white background, simple background" FOUR times on purpose -- that is how
    # the deep tier, which samples the axis at RANDOM, weights white upward.
    # A deterministic slice turns that weighting into a silent no-op: the first
    # three entries are byte-identical, so this loop rendered one background
    # three times and never reached purple, pink or gradient at all. Measured
    # 2026-08-18: it collapsed 1440 built jobs to 480 on dedupe.
    bgs = list(dict.fromkeys(db["axes"]["background"]))
    for emotion, readings in db["canon_emotions"].items():
        if not isinstance(readings, list):
            continue
        primary = readings[0]
        for frame in frames:
            for light in lights:
                for bg in bgs[:3]:
                    jobs.append(assemble(
                        db, [frame, primary, bg, light],
                        seed, "sweep", emotion, "ariaface_sweep",
                    ))
    return jobs


def tier_scene(db, count, rng):
    """Purple gamer-room scenes: wide, dark, monitor-lit.

    Sampled rather than enumerated -- the room/activity/framing/atmosphere
    product is ~13.8k. Runs after the face tiers because the avatar plate is the
    thing actually blocking work; these are wallpapers and panel art.

    The colour recipe and its matching negative are applied to every scene, not
    sampled: without both halves the room renders blue. That was measured, and
    it is the one part of a scene prompt that is not allowed to vary.
    """
    sc = db["scene"]
    emotions = [v[0] for v in db["canon_emotions"].values() if isinstance(v, list)]
    jobs = []
    base = db["seeds"]["deep_base"] + 500000
    for i in range(count):
        parts = [
            rng.choice(sc["framings"]),
            rng.choice(sc["activities"]),
            rng.choice(emotions),
            rng.choice(sc["rooms"]),
            sc["colour_recipe"],
            rng.choice(sc["atmosphere"]),
        ]
        jobs.append(assemble(
            db, parts, base + i, "scene", "scene{:05d}".format(i + 1),
            "ariascene", extra_neg=sc["colour_negative"],
            size=(sc["width"], sc["height"]),
        ))
    return jobs


def interleave(*lists):
    """Round-robin merge of several tiers.

    Used so the night degrades gracefully. The deadline lands mid-queue by
    design, and a crash can land anywhere, so tiers of comparable value are
    braided rather than queued behind one another: whenever the run stops, some
    of each exists instead of all of one and none of the next.
    """
    out = []
    for row in itertools.zip_longest(*lists):
        out.extend(x for x in row if x is not None)
    return out


def pick_axes(rng, axes):
    """Choose which axes contribute to one deep-tier prompt, and their values.

    This is the knob that decides what the deep tier is actually FOR. Booru
    models degrade past roughly 40 tags, and every extra axis is another chance
    to pull the render away from the frozen identity -- but too few axes and the
    night just re-renders near-duplicates of the sweep tier.

    Current policy: expression always (it is the point), background always (the
    avatar needs a predictable key), then 2-4 of the optional axes. Tuned toward
    variety without letting any one prompt get long enough to drift.
    """
    parts = [rng.choice(axes["expression"]), rng.choice(axes["background"])]
    optional = ["eye_effect", "hair_state", "effect", "accessory",
                "lighting", "style"]
    rng.shuffle(optional)
    for name in optional[:rng.randint(2, 4)]:
        parts.append(rng.choice(axes[name]))
    return parts


def tier_deep(db, count, rng):
    """Random stratified sampling of the axis space.

    The full cartesian product is far larger than any night could render, so the
    run samples it instead of enumerating it. The RNG is seeded, so an
    interrupted night resumes into the same sequence rather than a fresh one.
    """
    jobs = []
    frames = db["framing"]["variants"]
    base = db["seeds"]["deep_base"]
    for i in range(count):
        parts = [rng.choice(frames)] + pick_axes(rng, db["axes"])
        jobs.append(assemble(
            db, parts, base + i, "deep", "deep{:05d}".format(i + 1),
            "ariaface_deep",
        ))
    return jobs


# --------------------------------------------------------------------------
# Bookkeeping


def log(msg):
    stamp = dt.datetime.now().strftime("%H:%M:%S")
    print("[{}] {}".format(stamp, msg))


def load_ledger(path):
    done = {}
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # a half-written line from a hard kill; skip it
            done[rec["key"]] = rec
    return done


def append_ledger(path, rec):
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()


def free_vram(enabled):
    if not enabled:
        return
    try:
        subprocess.run(["ollama", "stop", OLLAMA_MODEL],
                       capture_output=True, timeout=30)
    except Exception:
        pass  # ollama absent or already stopped -- neither is worth failing on


def write_contact_sheet(records, path, started):
    """A curation surface, not a gallery.

    Grouped by tier then label so the ten emotions sit next to their own
    variants, and every tile carries its seed and prompt -- an image you like is
    useless if you cannot reproduce it.
    """
    by_tier = {}
    for rec in records:
        by_tier.setdefault(rec["tier"], []).append(rec)

    parts = ["""<!doctype html><meta charset="utf-8">
<meta http-equiv="refresh" content="15">
<title>Aria face lab</title>
<style>
 body{background:#14101c;color:#f3ecff;font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px}
 h1{font-size:20px;margin:0 0 4px}
 h2{font-size:16px;margin:32px 0 12px;color:#d9b3ff;border-bottom:1px solid #3a2f52;padding-bottom:6px}
 .meta{color:#9d8fb5;margin-bottom:8px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
 figure{margin:0;background:#1e1830;border:1px solid #362b4e;border-radius:10px;overflow:hidden}
 img{width:100%;display:block;background:#fff}
 figcaption{padding:7px 9px;font-size:11px;color:#b9a9d4;word-break:break-word}
 .lab{color:#ffd9f5;font-weight:600}
 .seed{color:#8fd9ff}
 .live{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-bottom:8px}
 .live img{border-radius:10px}
 .dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#7CFFB2;margin-right:7px;animation:p 1.6s infinite}
 @keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
</style>"""]
    parts.append("<h1>Aria face lab</h1>")
    parts.append('<div class="meta"><span class="dot"></span>{} images '
                 "&middot; run started {} &middot; this page reloads every 15s"
                 "</div>".format(len(records), html.escape(started)))

    # Newest first, big, at the top -- this is the live view. Capped at 8 so a
    # thousand-image run does not reload a thousand files every 15 seconds.
    if records:
        parts.append("<h2>latest</h2>")
        parts.append('<div class="live">')
        for rec in list(reversed(records))[:8]:
            parts.append(
                '<figure><img loading="lazy" src="{src}">'
                '<figcaption><span class="lab">{lab}</span> '
                '<span class="seed">seed {seed}</span></figcaption></figure>'.format(
                    src=html.escape(rec["file"]), lab=html.escape(rec["label"]),
                    seed=rec["seed"]))
        parts.append("</div>")

    for tier in ("canon", "sweep", "scene", "deep"):
        recs = by_tier.get(tier)
        if not recs:
            continue
        parts.append("<h2>{} &mdash; {} images</h2>".format(tier, len(recs)))
        parts.append('<div class="grid">')
        for rec in recs:
            parts.append(
                '<figure><img loading="lazy" src="{src}">'
                '<figcaption><span class="lab">{lab}</span> '
                '<span class="seed">seed {seed}</span><br>{pos}</figcaption>'
                "</figure>".format(
                    src=html.escape(rec["file"]),
                    lab=html.escape(rec["label"]),
                    seed=rec["seed"],
                    pos=html.escape(rec["positive"][:240]),
                )
            )
        parts.append("</div>")

    path.write_text("\n".join(parts), encoding="utf-8")


def write_manifest(records, path):
    cols = ["key", "tier", "label", "seed", "file", "elapsed", "positive",
            "negative"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for rec in records:
            w.writerow(rec)


def parse_until(text):
    """'07:00' -> the next time it is 07:00. '6h' -> six hours from now."""
    text = text.strip().lower()
    now = dt.datetime.now()
    if text.endswith("h"):
        return now + dt.timedelta(hours=float(text[:-1]))
    if text.endswith("m"):
        return now + dt.timedelta(minutes=float(text[:-1]))
    hh, mm = text.split(":")
    target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return target


# --------------------------------------------------------------------------


def main():
    # line_buffering so a redirected log shows progress live; without it Python
    # block-buffers when stdout is not a TTY and an eight-hour run looks
    # identical to a hang.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=True)

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--until", default="07:00",
                   help="Stop at this clock time (HH:MM), or after '6h'/'90m'.")
    p.add_argument("--deep", type=int, default=4000,
                   help="How many deep-tier prompts to sample. The night will "
                        "not get through them all; that is the point.")
    p.add_argument("--out", default=str(OUT_DIR),
                   help="Output dir. Default is under generated/, which is "
                        "inside OneDrive and will sync ~1.1 MB per image.")
    p.add_argument("--skip-canon", action="store_true")
    p.add_argument("--skip-sweep", action="store_true")
    p.add_argument("--skip-scene", action="store_true")
    p.add_argument("--scene", type=int, default=1200,
                   help="How many purple gamer-room scenes to sample.")
    p.add_argument("--keep-ollama", action="store_true",
                   help="Do NOT stop Aria's model. Generation runs ~3x slower.")
    p.add_argument("--dry-run", action="store_true",
                   help="Build and count the queue, print samples, generate "
                        "nothing.")
    p.add_argument("--sheet-every", type=int, default=1,
                   help="Rewrite the contact sheet every N images. Default 1 so "
                        "the sheet works as a live view while the run is going.")
    a = p.parse_args()

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    render = db["render"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / "ledger.jsonl"

    rng = random.Random(db["seeds"]["deep_base"])
    # Each tier is deduped as it is built, so the counts below are real work and
    # the braid ratio means what it says.
    seen = set()
    canon = [] if a.skip_canon else dedupe(tier_canon(db), render, seen)
    sweep = [] if a.skip_sweep else dedupe(tier_sweep(db), render, seen)
    scene = ([] if a.skip_scene
             else dedupe(tier_scene(db, a.scene, rng), render, seen))
    deep = dedupe(tier_deep(db, a.deep, rng), render, seen)

    # Canon runs alone and first: it is the avatar plate, it is the thing
    # actually blocking work, and its locked seeds only mean anything as a
    # complete set. Sweep and scene are then BRAIDED -- both are breadth on an
    # identity canon has already proven, so neither outranks the other, and
    # interleaving them is what makes an early stop leave some of each.
    unique = canon + interleave(sweep, scene) + deep

    done = load_ledger(ledger_path)
    todo = [j for j in unique if j["key"] not in done]

    deadline = parse_until(a.until)
    log("database : {}".format(DB_PATH))
    log("identity : {}".format(db["identity"]["tags"]))
    log("queue    : {} unique, {} already done, {} to run".format(
        len(unique), len(unique) - len(todo), len(todo)))
    log("deadline : {}  ({:.1f} h from now)".format(
        deadline.strftime("%Y-%m-%d %H:%M"),
        (deadline - dt.datetime.now()).total_seconds() / 3600.0))
    log("output   : {}".format(out))

    if a.dry_run:
        by_tier = {}
        for j in todo:
            by_tier[j["tier"]] = by_tier.get(j["tier"], 0) + 1
        log("tiers    : {}".format(by_tier))
        for j in (todo[:2] + todo[len(todo) // 2:len(todo) // 2 + 2]):
            print("\n--- {} / {} / seed {}".format(j["tier"], j["label"], j["seed"]))
            print("  +", j["positive"])
            print("  -", j["negative"])
        return 0

    if not comfy_alive() and not wait_for_comfy(deadline.timestamp()):
        log("ComfyUI never came back before the deadline. Nothing generated.")
        return 1

    ckpts = _get("/object_info/CheckpointLoaderSimple")
    ckpts = ckpts["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    if render["model"] not in ckpts:
        log("Checkpoint missing: {}".format(render["model"]))
        log("ComfyUI sees: {}".format(", ".join(ckpts)))
        return 1

    records = [done[k] for k in done]
    started_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    free_vram(not a.keep_ollama)
    last_vram = time.time()

    made = failed = 0
    for job in todo:
        if time.time() >= deadline.timestamp():
            log("Deadline reached.")
            break

        if time.time() - last_vram > OLLAMA_EVERY:
            free_vram(not a.keep_ollama)
            last_vram = time.time()

        if not comfy_alive() and not wait_for_comfy(deadline.timestamp()):
            log("Deadline passed while ComfyUI was down.")
            break

        try:
            res = _post("/prompt", {"prompt": build_workflow(job, render),
                                    "client_id": "aria-face-lab"})
        except Exception as exc:
            log("queue failed ({}): {}".format(job["label"], exc))
            failed += 1
            time.sleep(5)
            continue

        if res.get("node_errors"):
            log("rejected ({}): {}".format(job["label"], res["node_errors"]))
            failed += 1
            continue

        status, images, elapsed = await_result(res["prompt_id"])
        if status != "success" or not images:
            log("{} -> {} after {:.0f}s".format(job["label"], status, elapsed))
            failed += 1
            continue

        for img in images:
            src = COMFY_OUTPUT / img.get("subfolder", "") / img["filename"]
            if not src.exists():
                log("missing on disk: {}".format(src))
                failed += 1
                continue
            dst = out / "{}_{}_{}".format(job["tier"], job["key"], img["filename"])
            shutil.copy2(src, dst)
            rec = {
                "key": job["key"], "tier": job["tier"], "label": job["label"],
                "seed": job["seed"], "file": dst.name,
                "elapsed": round(elapsed, 1),
                "positive": job["positive"], "negative": job["negative"],
            }
            append_ledger(ledger_path, rec)
            records.append(rec)
            made += 1

        if made % a.sheet_every == 0:
            write_contact_sheet(records, out / "contact_sheet.html", started_str)
            write_manifest(records, out / "manifest.csv")
            remaining = (deadline.timestamp() - time.time()) / 60.0
            log("{} made / {} failed / {:.0f} min left  (last {:.0f}s: {})".format(
                made, failed, remaining, elapsed, job["label"]))

    write_contact_sheet(records, out / "contact_sheet.html", started_str)
    write_manifest(records, out / "manifest.csv")
    log("done: {} new, {} failed, {} total on disk".format(
        made, failed, len(records)))
    log("open {}".format(out / "contact_sheet.html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
