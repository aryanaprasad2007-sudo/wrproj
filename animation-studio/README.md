# animation-studio

A local, shot-based AI animation pipeline for an original animated short.
Runs entirely on this machine — RTX 4060 (8 GB), 32 GB RAM, no cloud APIs.

Shot list in, `film.mp4` out. Any single shot can be re-rendered without
rebuilding the rest.

---

## The one design decision that explains everything else

**Text-to-video cannot hold a character identity on 8 GB.** Small video models
have no mature character-LoRA or IP-Adapter ecosystem, so asking one to produce
"the same fox spirit" across thirty separate generations gives you thirty
different fox spirits.

So the pipeline is **keyframe-first**:

```
 Stage A  SDXL + character LoRA + IP-Adapter + ControlNet  ->  ONE STILL
          all the consistency tooling lives here, and it is mature
                              |
 Stage B  image-to-video model  ->  a 3-second clip
          only has to MOVE what is already in the frame.
          It never needs to know who the character is.
                              |
 Stage C  Real-ESRGAN upscale  ->  RIFE interpolation  ->  clip.mp4
                              |
 Stage D  ffmpeg: cuts, crossfades, music, SFX  ->  film.mp4
```

**Practical consequence:** if a character looks wrong in the finished clip, the
bug is almost always in the Stage A still, not in the video stage. Render
keyframes alone first (`--stage keyframe`) and judge those. It takes minutes
instead of hours.

---

## Install

This machine already has a CUDA-capable GPU **and** a CPU-only `torch`. Those
facts coexist and the second one silently disables the first.

```
py -3.12 -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# -> 2.12.1+cpu False        <- the GPU is fine; the wheel is wrong
```

The setup script builds a **separate venv** rather than fixing that in place,
for two reasons: `py -3.12` runs the lifestyle tracker (ultralytics + CPU
torch) and swapping its torch would silently change a working system; and the
venv must live **outside OneDrive**, because 6–8 GB of CUDA wheels that change
on every pip operation is not something to sync.

```bash
py -3.12 scripts/setup_env.py
```

Creates `~/.venvs/animstudio` with `torch+cu126`, diffusers, transformers,
accelerate and peft. Then:

```bash
~/.venvs/animstudio/Scripts/python.exe scripts/doctor.py
```

`doctor` reports the GPU using `nvidia-smi` (not torch), so it can still tell
you *"this is the CPU-only build"* when torch itself claims there is no GPU.

Copy the config and you are ready:

```bash
cp config/project.example.yaml config/project.yaml
```

> Throughout this README, `py` means the venv interpreter
> (`~/.venvs/animstudio/Scripts/python.exe`). The tests are the exception —
> they run on plain `py -3.12` on purpose.

---

## Models

### Already on this machine — no download needed

ComfyUI Desktop installed these under
`%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\models\`, and
`config/project.example.yaml` already points at them:

| file | size | role |
|---|---|---|
| `animagine-xl-4.0.safetensors` | 6.5 GB | **default base** — anime/fantasy SDXL |
| `sd_xl_base_1.0_0.9vae.safetensors` | 6.5 GB | photoreal alternative |
| `sdxl_vae_fp16fix.safetensors` | 0.3 GB | avoids fp16 NaN → black images |

> The `minimax_h3_*` files in that folder (19.5 GB diffusion + 14.6 GB text
> encoder) **cannot run here** — ~34 GB of weights against 8 GB VRAM and 32 GB
> RAM. They will not fit even fully offloaded. Not used by this project.

### What you still need

```bash
py scripts/download_models.py --list          # sizes and notes
py scripts/download_models.py --video ltx     # ~9 GB, the default backend
py scripts/download_models.py --ipadapter     # ~2.5 GB, character reference
py scripts/download_models.py --controlnet sdxl   # ~2.5 GB, pose/depth/canny
py scripts/download_models.py --all-post      # ~65 MB, upscaler + RIFE binaries
```

Minimum for a first real render: `--video ltx`. Everything else degrades
gracefully — no IP-Adapter means consistency rests on the LoRA and trigger
token; no Real-ESRGAN falls back to Lanczos; no RIFE falls back to ffmpeg's
`minterpolate`.

### Choosing a video backend

| backend | size | frames | prompt? | verdict on 8 GB |
|---|---|---|---|---|
| **`ltx`** | ~9 GB | 8k+1, ≤257 | yes | **default.** Fastest usable option |
| `wan` | 7–32 GB | 4k+1, ≤81 | yes | best motion; use the 1.3B, not the 14B |
| `svd` | ~9 GB | 25 fixed | **no** | lovely drift, zero control |
| `animatediff` | ~1.8 GB | ≤32 | yes | **requires `base_kind: sd15`** |

`animatediff` is the only backend where your character LoRA and IP-Adapter
apply to *every generated frame* rather than only the keyframe — identity gets
re-asserted 16 times instead of once. That is a real advantage for a
two-character short. The cost is that it is SD1.5, so it needs an SD1.5 base
checkpoint and an SD1.5-trained LoRA. **That is a fork in the project, not a
toggle** — an SDXL LoRA will not load into it.

Backends are swappable per project (`stages.video_backend`) and the sensible
workflow is to draft the whole film on `ltx`, then switch the six shots the
audience actually looks at.

---

## Writing a shot list

`shots/example.yaml` is a complete annotated 10-shot short — start by copying
it. Only `id` and `prompt` are required.

```yaml
title: kettle-and-mira

audio:
  music: ../assets/music/theme.mp3
  music_gain: 0.55
  sfx:
    - { path: ../assets/sfx/whistle.wav, at: 14.0, gain: 0.9 }

shots:
  - id: s03_mira_enters
    prompt: peering around the doorframe into the kitchen, curious, ears forward
    characters: [mira]
    camera: medium shot, eye level, static
    duration: 3.5
    transition: crossfade
    transition_seconds: 0.6

  - id: s04_mira_closeup
    prompt: eyes widening, whiskers twitching, looking up at something off frame
    characters: [mira]
    camera: close up on the face, shallow depth of field
    duration: 2.5
    carry_from: s03_mira_enters   # seeds this keyframe from s03's last frame
    carry_strength: 0.45          # 0.35 = nearly identical, 0.75 = palette only
    preset: high                  # hero shot: render properly even in a draft pass
```

| key | meaning |
|---|---|
| `id` | folder name **and seed source**. Renaming a shot re-rolls it. |
| `prompt` | what *happens*. Not the character design — that lives in the character file. |
| `characters` | names from `characters/*/character.yaml` |
| `camera` | appended to the prompt; also passed to the video stage |
| `duration` | seconds; the backend rounds to a legal frame count |
| `seed` | omit for a stable seed derived from `id` |
| `ref_image` | start from an image instead of noise (overrides `carry_from`) |
| `control` | `{pose\|depth\|canny: path}` — ControlNet for the keyframe |
| `control_scale` | 0.4 loose · 0.65 default · 0.9 rigid |
| `carry_from` | an **earlier** shot id, for continuity |
| `transition` | `cut` or `crossfade` — how this shot *enters* |
| `preset` | per-shot override |
| `notes` | ignored by the renderer |

**Seeds derive from the shot `id`, not from position.** Inserting a shot at
position 3 does not re-roll every shot after it — the classic way to lose a
take you liked.

Validate before committing GPU hours. This loads no models:

```bash
py -m animstudio render shots/example.yaml --dry-run
```

```
shot              chars                frames   secs        size         seed
--------------------------------------------------------------------------------
s01_kitchen_wide                           49   4.08     512x512   3493063249
s02_pov_reach     pov                      33   2.75     512x512   2915804965
...
10 shots, 386 frames, ~10m17s of generation

consistency warnings:
  ! 'Mira' has neither a LoRA nor reference images (5 shots) -- identity will
    rest on the prompt alone and will drift
```

---

## Characters

One folder per character in `characters/`. Three stacked mechanisms, weakest
to strongest:

| mechanism | cost | strength | fails by |
|---|---|---|---|
| trigger token + description | free | weak | drifting — the model re-interprets "silver-haired" every render |
| reference images (IP-Adapter) | no training | medium | importing the reference's *composition* above ~0.75 weight |
| **LoRA** | ~25 min once | strongest | overfitting to pose/background if the dataset is thin |

```yaml
name: Mira
kind: full                # full | pov

# A rare token the base model has no prior for. Real words ("mira", "fox")
# bind to what the model already thinks they mean and fight your design.
trigger: mirafx

# STABLE traits only. No pose, no camera, no setting — those come from the
# shot, and repeating them here drags the turnaround pose into every scene.
description: >-
  small fox spirit, cream and rust fur, oversized amber eyes,
  two tails, moss-green scarf, soft cel shading

lora_path: lora/mira_r16_s1200.safetensors
lora_weight: 0.85
ipadapter_weight: 0.6
```

**The POV character** (`kind: pov`) is a first-class case because its problem
is different — there is no face to lock, so the useful signal is skin tone,
sleeve and worn props. It gets a lower default IP-Adapter weight and an
automatic negative for the thing that ends a POV shot: `face, head, portrait,
full body, mirror reflection, selfie`.

**Two characters in one frame is where consistency breaks worst** — the model
averages them into a single hybrid design. The pipeline auto-scales stacked
LoRAs by `1/sqrt(n)` (0.85 + 0.85 → 0.60 each, verified in the tests) so they
compete less. Beyond that, use a pose ControlNet so each body is *placed*
rather than invented.

---

## Training a character LoRA

### The dataset matters more than any hyperparameter

- **15–30 images.** Under 10 overfits to the background; over ~40 stops helping.
- **Vary pose, angle, expression, framing.** A LoRA trained on six turnaround
  poses reproduces those six poses forever — the most common failure, and it
  presents as *"the model ignores my prompt."*
- **Vary or remove the background**, or it becomes part of the character.
- **Caption what varies, not what is constant.** Anything you caption becomes
  editable; anything you leave uncaptioned is absorbed into the trigger token —
  which is exactly what you want for identity.

```
characters/mira/
  character.yaml
  refs/
    001.png
    001.txt        <- optional per-image caption: "side view, arms raised"
    002.png
    ...
```

```bash
py -m animstudio.train_lora --character characters/mira --steps 1200
```

Then set `lora_path: lora/mira_r16_s1200.safetensors` in `character.yaml`.

### Why it fits in 8 GB

Standard advice says SDXL LoRA training needs 12–16 GB. This trainer encodes
every image to a latent and every caption to embeddings **once**, then deletes
the VAE and both text encoders before the training loop starts:

```
naive:   unet 5.0 + text encoders 1.4 + VAE 0.3 + grads/optimiser  -> OOM
cached:  unet 5.0 + LoRA grads 0.1 + optimiser 0.2                 -> ~6.5 GB
```

Plus gradient checkpointing (~30 % slower, and the difference between fitting
and not fitting) and 8-bit AdamW when `bitsandbytes` is available.

The trade-off: caching freezes captions and crops, so there is no per-epoch
augmentation. For a 15–30 image character set that is the right call — the
dataset is too small for augmentation to matter more than fitting on the card.

Defaults: rank 16 (rank 4 loses eye shape and accessory geometry; rank 64
memorises the background and triples the file size for no identity gain), lr
1e-4, 1200 steps, 768 px for SDXL.

---

## Rendering

```bash
# fast iteration — 512px, no upscale, no interpolation
py -m animstudio render shots/example.yaml --preset draft

# final
py -m animstudio render shots/example.yaml --preset high

# just the stills, to judge character consistency (minutes, not hours)
py -m animstudio render shots/example.yaml --stage keyframe

# redo two shots and rebuild the film
py -m animstudio render shots/example.yaml --only s04_mira_closeup,s07_chase_start

# continue an interrupted run
py -m animstudio render shots/example.yaml --resume

# recut / change the music — no GPU at all
py -m animstudio assemble shots/example.yaml
```

`--stage` takes any comma-separated subset of `keyframe,video,post,assemble`.

**Run order is dictated by VRAM, not logic.** The pipeline renders *all*
keyframes, unloads SDXL entirely, then animates all of them. Interleaving would
swap a ~5 GB model in and out once per shot — on a 40-shot film that is roughly
40 minutes of pure loading.

A failed shot logs and continues; the run finishes and tells you what to retry.

### Output layout

```
<work_root>/<film>/
  run.jsonl                 append-only production log; drives --resume
  <film>.mp4                the film
  shots/<id>/
    keyframe.png            Stage A  <- judge character consistency HERE
    carry.png               the frame handed to the next shot
    frames/                 Stage B, raw generated PNGs
    frames_up/              Stage C1, upscaled
    frames_final/           Stage C2, interpolated (RIFE path)
    clip.mp4                the finished shot
    meta.json               exactly what produced it (prompt, seed, LoRAs)
```

`work_root` defaults to `C:/Users/aware/animstudio-work` — **outside OneDrive**,
because a short film is tens of GB of PNG sequences and OneDrive will try to
sync all of it, sometimes locking files while ffmpeg is writing them.

---

## Expected time per shot

**These are estimates, not measurements.** They are extrapolated from published
LTX/SDXL throughput on comparable 8 GB Ada cards — nothing in this table has
been benchmarked on this machine yet, because the CUDA venv is created by
`setup_env.py` and the video weights are not downloaded until you ask for them.
The ffmpeg and config numbers elsewhere in this README *are* measured.

For a 3-second shot, LTX backend, after the model is warm:

| stage | draft (512px) | high (768px) |
|---|---|---|
| Stage A keyframe | ~8 s | ~20 s |
| Stage B video (33–49 frames) | ~60–90 s | ~2–4 min |
| Stage C1 upscale to 1080p | skipped | ~20–40 s |
| Stage C2 RIFE 12→24 fps | skipped | ~10–20 s |
| **per shot** | **~1.5 min** | **~4–6 min** |

Plus one-off costs per run: ~60–90 s to load SDXL, ~60 s to load the video
model. Both are paid once, not per shot — that is what the stage ordering buys.

Rough film-level arithmetic:

- **40 shots, draft:** ~1 hour
- **40 shots, high:** ~3–4 hours
- **LoRA training, 20 images, 1200 steps:** ~25–40 min

Replace this table with your own numbers once you have run a batch — `run.jsonl`
records per-stage seconds for every shot, and `RunTracker.summary()` prints the
median. The ETA shown during a run uses a **trailing median of the last 5
shots**, not a running mean, because the first shot of a run pays model load and
a mean lets that one-off poison the estimate for the whole batch.

---

## Continuity policy — one decision left to you

`select_carry_frame()` in `src/animstudio/pipeline.py` chooses **which frame of
a finished shot seeds the next one**. It ships with the conservative default
(the last frame) and a `TODO` marking the real decision, because this changes
how the film feels more than any parameter here:

- **Last frame** *(current default)* — perfect temporal continuity. But small
  video models degrade *over* a clip, so the last frame is usually the blurriest
  and most drifted. Carrying it compounds drift down the chain: by shot 8 the
  character has quietly become someone else.
- **First frame** — sharpest, closest to the Stage A keyframe, drift never
  accumulates. But it discards the motion, so shot N+1 begins where shot N
  *began* — reads as a jump cut backwards.
- **Sharpest frame** (variance of Laplacian) — resists drift well; may pick from
  the middle, so continuity is approximate.
- **Blend** — e.g. sharpest within the last third. The usual compromise: near
  the end for continuity, backed off from where degradation is worst.

The sharpness-aware version is about six lines, and the docstring sketches it.
Which one is right depends on how long your chains of `carry_from` shots are —
worth deciding once you have seen your own footage drift.

---

## Swapping components

Everything is behind a small interface, selected by name in `project.yaml`:

| what | where | how |
|---|---|---|
| base checkpoint | `models.base_checkpoint` | any SDXL or SD1.5 `.safetensors` |
| video backend | `stages.video_backend` | `ltx` · `wan` · `svd` · `animatediff` |
| upscaler | `stages.upscaler` | `realesrgan` · `lanczos` · `none` |
| interpolator | `stages.interpolator` | `rife` · `ffmpeg` · `none` |

Adding a video backend: subclass `VideoBackend` in `src/animstudio/video/`,
implement `generate()` plus the frame/dimension constants, and add one line to
`registry.py`. Nothing else changes — frame quantisation, VRAM policy, progress
and assembly are all inherited.

---

## Tests

```bash
py -3.12 tests/test_pipeline.py
```

Runs on the **plain system interpreter** on purpose — no GPU, no models, no
downloads. The things most likely to break are config parsing, the ffmpeg filter
graph and resume bookkeeping, none of which touch torch, and a suite that needs
the CUDA venv to be healthy cannot tell you the venv is unhealthy.

38 checks, currently all passing. The one that earns its keep: **a crossfade
following a cut.** `concat` emits timebase `1/1000000` while a freshly scaled
input carries `1/fps`, and `xfade` hard-fails on the mismatch — a bug invisible
to any test that uses a single transition type. That is why every input carries
`settb=AVTB`.

---

## Troubleshooting

| symptom | cause |
|---|---|
| `torch.cuda.is_available() == False` with a working GPU | CPU-only torch wheel. Run `scripts/doctor.py` — it prints the exact fix. |
| Black or NaN images | SDXL fp16 VAE bug. Set `models.vae` to `sdxl_vae_fp16fix.safetensors`. |
| Character drifts across shots | No LoRA and no reference images. `--dry-run` warns about this per character. |
| Two characters blend into one | Train both LoRAs; add a pose ControlNet. Stacked LoRAs are already auto-scaled. |
| Reference image's *framing* keeps reappearing | `ipadapter_weight` above ~0.75. Drop to 0.55–0.65. |
| Last half-second of every shot glitches | Illegal frame count for the backend's temporal VAE. `--dry-run` shows the quantised count. |
| OOM at step 27 of 30 | Something else is holding VRAM. Ollama pins 4.78 GB with `keep_alive: -1` — `ollama stop qwen2.5:7b` first. |
| Shot 12 has shot 3's character | LoRA state leak — should be impossible (`_apply_loras` unloads first). File it. |
| AnimateDiff output is washed out | Wrong scheduler config. The backend forces linear beta + `clip_sample=False`. |

> **Sharing the GPU with Aria:** per the `comfyui-sdxl` notes, `qwen2.5:7b`
> pins 4.78 GB with `keep_alive: -1`, and loading a second large checkpoint
> alongside it stalls indefinitely rather than failing. Stop Ollama before a
> render batch; it reloads on the tracker's next ping by itself.
