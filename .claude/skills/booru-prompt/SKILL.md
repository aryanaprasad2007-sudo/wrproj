---
name: booru-prompt
description: Turn a plain-English description of a character or scene into a booru-tag prompt for the local anime SDXL models, and generate it through the running ComfyUI. Use when Ari describes an image he wants ("a white-haired girl with star pupils..."), asks to convert or fix a prompt, says an image "came out wrong", or wants more art for Aria or any other character.
---

Anime SDXL checkpoints (Animagine, Illustrious, Pony) are trained on **Danbooru
captions** — comma-separated tags from a closed vocabulary, not sentences. Prose
mostly wastes tokens, and a near-synonym that isn't a real tag conditions weakly
and **silently drops the trait**. Nothing errors; the image just quietly lacks
what he asked for. Preventing that specific failure is why this skill exists.

## Where this lives and why

Everything is **project-local to wrproj**, deliberately — never `~\.claude\skills\`:

```
wrproj/.claude/skills/booru-prompt/
  SKILL.md    <- procedure + provenance (this file)
  tags.json   <- the prose->tag mappings, as DATA
  queue.py    <- ComfyUI driver, stdlib only
wrproj/generated/            <- output PNGs land here
```

The skill, its data, and its artifacts stay inside the repo so the whole thing is
one portable, inspectable unit that travels with the project and can be diffed,
rebuilt, or fed to another system. A user-level copy would split the skill from
the measurements that justify it.

**Note:** `wrproj` is under OneDrive, so `generated/` syncs. ~1.2 MB per 1024²
PNG. Prune it or add it to an ignore rule if a large set is being produced.

## Procedure

1. Restate his description as tags using `tags.json`.
2. Show him the tag list **before** generating, grouped in `tag_order`, so he can
   veto a reading. He knows the character; the mapping is a guess until he sees it.
3. Generate:
   ```bash
   py -3.12 .claude/skills/booru-prompt/queue.py --positive "1girl, solo, ..." --seed N
   ```
4. Read the returned PNG back in chat and **say what the model dropped or invented**.
   That report is what earns new entries in `tags.json`.
5. `py -3.12 .claude/skills/booru-prompt/catalog.py` — sweep every image into
   wrproj and rebuild `generated/CATALOG.csv`. Run it after any batch.

## Keeping the local record

**Every generated image must end up in `wrproj/generated/`.** ComfyUI writes to
its own AppData output dir; `catalog.py` sweeps from there and is idempotent, so
run it freely.

It reconstructs each image's model / seed / steps / cfg / sampler / prompt by
reading **ComfyUI's API-format graph out of the PNG's tEXt chunks**. That means
an image carries its own provenance even when nothing logged it at the time —
images generated before any logging existed still catalogue correctly instead of
becoming unlabelled orphans. Nothing needs to be captured at generation time for
this to work.

`generated/CATALOG.csv` is Notion-importable as-is (Notion builds a database
from a CSV import). Images can't ride along in a CSV, so the `Path` column
points at the local file.

**Do not prune failed or embarrassing generations from the catalogue.** The
run where a prompt landed in the negative box is recorded with its actual
`blurry, low quality...` prompt. A catalogue that only contains successes can't
be used to work out what went wrong.

`queue.py --help` for the rest. It refuses unknown checkpoints and prints what
ComfyUI actually sees, which distinguishes "model missing" from "UI not refreshed".

## Rules

Tag order (weight decreases left to right) and the mapping table both live in
`tags.json` — read it rather than duplicating it here. The structural rules:

- Lead with the count tag (`1girl` / `1boy` / `2girls`) and add `solo`.
- Expressions are **emoticon tags** (`:d`, `:3`, `^_^`, `;)`), not adjectives.
- Spaces, not underscores — these models trained with underscores substituted out.
- The negative is boilerplate (`queue.py` supplies it). Edit it only to *remove*
  something specific that keeps appearing, e.g. add `hat`.

## Measured on this rig — do not re-derive

- **Anime fine-tunes want LOW cfg (5.0), base SDXL wants 7.5.** Anime tunes are
  far more prompt-adherent; high cfg oversaturates and hardens linework instead
  of improving accuracy. Carrying base SDXL's 7.5 over is the common mistake.
- **Base SDXL cannot render `star-shaped pupils` at all**, and renders "violet
  eyes" as grey-blue. Observed 2026-08-17 on `sd_xl_base_1.0_0.9vae`. This is a
  vocabulary gap, not a weighting problem — parentheses will not fix it.
- **A prompt in the negative slot does not fail, it steers away.** Observed the
  same day: Aria's description in the negative box produced a confidently wrong
  desk photo. Always confirm which node the text landed in.
- **VRAM is 8 GB and Ollama's `qwen2.5:7b` (Aria) pins 4.78 GB with
  `keep_alive: -1`**, so generation runs ~60 s instead of ~20, and a cold load of
  a new 6.5 GB checkpoint is much worse. `ollama stop qwen2.5:7b` buys it back;
  she reloads on the tracker's next ping. See [[psychowl-service]].
- **Models added while ComfyUI is open need a refresh** (`R`). The server rescans
  per request; the frontend caches `/object_info` at page load.

## Generating a face database overnight

`face_lab.py` + `aria_face.json` build thousands of Aria face prompts and run
them unattended against ComfyUI until a wall-clock deadline.

```bash
py -3.12 .claude/skills/booru-prompt/face_lab.py --until 07:00
```

`--dry-run` prints the queue and some sample prompts without generating.
Output, a resumable ledger, `manifest.csv` and `contact_sheet.html` land in
`generated/aria_face/`. Re-running skips anything already in the ledger, so an
interrupted night resumes rather than restarts.

**Identity is a constant there, not an axis, and that is the whole point.**
`generated/aria_clean` and `generated/aria_stars` were meant to be the same
character and are demonstrably two different girls: eyes, hair ornament,
neckwear and headphones all changed at once, and identity in a booru model is
carried by exactly those few high-weight leading tags. `face_lab.py` therefore
prepends the identity block verbatim to every prompt and exposes no way to vary
it. Do not add an eye-colour, hair or outfit axis to `aria_face.json`.

Measured 2026-08-18 while building it, both from reading output back:

- **Framing had to be walked out twice, and the second time was Ari's call.**
  `close-up` crops the head at 832x1216 and *overpowers* `cropped head` sitting
  in the negative -- so it went to `portrait, head and shoulders`, which was
  measurably better and **still too close**: Ari's words were "WAY too close to
  the camera". Danbooru's `portrait` IS a head shot; it is not the English word.
  What ships is `upper body` **plus `close-up, portrait, face focus` pushed into
  the negative** -- the framing tag alone loses to the model's prior, so the
  suppression is load-bearing, not belt-and-braces. `cowboy shot` overshoots and
  starts drawing a picture frame. Probes: `generated/aria_face_probe{,2}/`.
  Do not "tidy" those three terms out of the negative.
- **`straight-on` does not level the head.** It conditions gaze more than camera
  height. Levelling still has to happen in post.
- **A negative term the positive asks for makes the model drop both.**
  `tune_negative()` removes a term when the prompt requests it -- needed because
  the negative deliberately carries the *other* Aria's signature tags.
- **10% of the first generated queue contradicted itself.** Measured over 6840
  built prompts: 434 carried `looking at viewer` (appended by every framing
  string) *and* a second gaze tag from an axis; 230 asked for pupil detail
  through `closed eyes`. A model does not refuse a contradiction, it averages
  it. `resolve_conflicts()` fixes this at assembly time, and its `keep` field
  encodes **where intent lives, not tag semantics**: framing's `looking at
  viewer` is boilerplate so a named gaze wins (`last`), while expression is
  chosen before decoration so a closed-eyed laugh beats a sparkle added two axes
  later (`first`). Closed lids *suppress* pupil tags rather than outranking
  them.
- **The obvious wider grouping is wrong, and was caught by looking.** Aperture
  and pupil shape are independent -- `wide-eyed, star-shaped pupils` is
  legitimate and the first audit flagged it as a conflict; so is `leaning back,
  sitting` and `from behind, from below`. Grouping those would delete Aria's
  single most characteristic tag. Only genuinely impossible pairs are resolved.
- **A pose tag had leaked into the room list.** `sitting on floor` sat inside a
  `scene.rooms` entry and collided with the activity axis in 38/1200 sampled
  prompts. Rooms describe the room; bodies belong to `scene.activities`.

### The scene tier (purple gamer room)

Ari's ask, 2026-08-18, referenced to Shiro's room in *No Game No Life*. It is a
**separate tier, not a replacement background**: the avatar page multiplies her
against its own panel, so a room behind her becomes a pasted-in rectangle. White
stays for the avatar plate; scenes are for wallpapers and the control panel.
Same frozen identity, so it is unmistakably her in both. Landscape 1216x832.

- **A single `purple theme` tag loses.** The model's default dark-room-with-
  monitors is *blue*-lit, and four separate readings came back blue despite
  asking for purple. Weighting to `(purple theme:1.4)` was still not enough.
  What worked needs **both halves**: pile on colour synonyms
  (`violet, magenta, neon purple, purple light, purple glow, neon lights`) **and**
  negate the competitor (`blue theme, blue light, cyan`). Applied to every scene
  prompt, never sampled. Probes: `generated/aria_scene_probe/`.
- RGB/LED vocabulary drifts the star hair ornament orange. Left out deliberately.

### Tier order is a failure-mode decision

`canon` runs alone and first -- it is the avatar plate and its locked seeds only
mean anything as a complete set. `sweep` and `scene` are then **braided**
(`interleave()`), because both are breadth on an identity canon has already
proven and neither outranks the other. A night reaches roughly 1000 images out
of ~5900 queued, so where it stops is not an edge case, it is the normal case:
braided, a 03:00 crash leaves ~200 of each instead of all of one and none of the
other. `deep` is last and is *meant* not to finish.

## Character consistency

Cheap route — lock `--seed` once a face is right, change only expression/pose/
framing tags, and keep identity tags **byte-identical** (reordering moves the
face). This gives family resemblance, **not identity**.

### LoRA route

ComfyUI 0.33.2 has a **native trainer** — no kohya, no separate venv:

```
CheckpointLoaderSimple -> LoadImageTextDataSetFromFolder
  -> MakeTrainingDataset -> TrainLoraNode -> SaveLoRA
```

Three scripts, run in order:

```bash
py -3.12 .claude/skills/booru-prompt/make_dataset.py --count 30
py -3.12 .claude/skills/booru-prompt/prepare_dataset.py --trigger ariakun
py -3.12 .claude/skills/booru-prompt/train_lora.py --steps 1200
```

Everything lands in `generated/aria_lora/` — `dataset/`, `manifest.json`,
`catalog.csv` (Notion-importable), `contact_sheet.html` (open it to curate),
`RUN_LOG.md`, `training_config.json`.

**Three design decisions worth not re-litigating:**

1. **The training set varies its backgrounds on purpose.** Standardising on
   white would bake the background into the character — the exact coupling the
   `floating-decor-fights-flat-background` failure is about.
2. **Captions omit the identity tags.** Caption what you want to be able to
   *change*; omit what you want *baked in*. Caption "white hair" and you get a
   LoRA that needs it in every prompt and will drop it; omit it and the trigger
   token carries it.
3. **`gradient_checkpointing` + `offloading` + `quantized_backward` all ON.**
   8 GB is marginal for SDXL LoRA training. `train_lora.py` preflights VRAM and
   **refuses to start** if Ollama still holds a model — a multi-hour run that
   stalls on VRAM is the worst possible failure here.

`--steps` / `--rank` / `--lr` are conventional starting points, **not measured
on this rig**. Treat run 1 as a probe: check a test generation before trusting
them, and compare against `training_config.json` on run 2.

## Rebuilding this skill

If this skill is lost, extended, or regenerated by another system, rebuild it
from the invariant below rather than by copying the current text.

**Invariant:** the skill's job is to stop traits from being silently dropped when
a natural-language description meets a tag-trained model. Everything else is
implementation.

**Parts and their responsibilities:**

| file | owns | rebuild by |
|---|---|---|
| `tags.json` | prose→tag mappings, tag order, per-model settings | observation (below) |
| `queue.py` | talking to ComfyUI, defaults, output copy | ComfyUI API is stable; re-read `/object_info` for current sampler/scheduler enums |
| `SKILL.md` | when to invoke, procedure, provenance | this section |

**How a mapping entry is earned — the only valid method:**

1. Generate with the **prose** form of the trait.
2. Read the image back and check whether the trait is present.
3. If it is absent, find the real tag, regenerate, and confirm it appears.
4. Only then add the entry with `"verified": true`.

Guessed synonyms are actively harmful here: they make the table look
authoritative without being tested, and the failure they encode is invisible.
Entries that have not been through steps 1–3 must be marked `"verified": false`.

**What to re-measure when the rig changes:** cfg/steps/sampler per checkpoint
(new model = new defaults, read the model card), the sampler/scheduler enums
(`GET /object_info/KSampler`), and the VRAM contention note if Aria's
`keep_alive` or the GPU changes. The prose→tag mappings are **model-family**
facts, not rig facts — they survive a GPU change and should not be re-derived
for one.
