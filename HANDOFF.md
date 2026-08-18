# Handoff — wrproj lifestyle tracker → NightOwl integration — ARCHIVED 2026-08-12

**STATUS: COMPLETE.** This handoff describes work-in-progress from an earlier session. The tracker integration is done:
- `build_tracker()` at line 85–158 reads today's mode log, baseline, and current block.
- The card data flows into NightOwl's hub as `tracker` field in the baked payload.
- Tested 2026-08-12: `py -3.12 nightowl/python/build_hub.py` runs cleanly; hub builds successfully.
- The scratch file `nightowl/hub/_corstest.html` never existed; no cleanup needed.

**For future reference:** If you are reading this and the tracker still fails to build, check CLAUDE.md §PSYCHOWOL for the current architecture. This document is now a historical record, not current tasking.

---

**Original text below (archived):**

The user is Ari. Concise for work. He wants to know *why* a choice was made,
not just the code. This project's ethos is **measure, don't guess** — the
record-then-replay architecture exists so detector changes are scored on
identical footage instead of vibes. Hold to that: verify claims by running
something, and report negative results plainly.

---

## 1. FIRST: the repo is currently broken

`nightowl/python/build_hub.py` will raise `NameError` on run. I made two edits
and stopped before writing the function they call:

- added `tracker = build_tracker()` right after `console = build_console()`
- added `"tracker": tracker,` to the dict returned by `build_payload()`

**`build_tracker()` does not exist.** Either write it (see §3) or revert those
two lines. Verify with:

```
py -3.12 nightowl/python/build_hub.py
```

Also delete the leftover probe file `nightowl/hub/_corstest.html` — it was a
scratch CORS test, not part of the project.

---

## 2. What is running right now

| thing | where | notes |
|---|---|---|
| tracker dashboard | `http://127.0.0.1:8787` | `py -3.12 src/dashboard.py`, background task |
| Aria's server | `http://127.0.0.1:8000` | `py -3.12 run_server.py` in `aria-assistant/` |
| Ollama | `http://127.0.0.1:11434` | `qwen2.5:7b` (Aria) + `moondream` (unused, see below) |

Aria's server keeps dying when started as a background task from an agent
session — it gets killed with the session, no traceback. Ari should run it in
his own terminal. The dashboard degrades to facts-only without her and
recovers on its own when she returns (it only advances its rate-limit clock on
a *successful* call).

**The dashboard holds the camera exclusively.** Anything else that opens the
camera must stop it first. It also has unsaved in-memory state (the torso
baseline) — restarting loses up to a few samples, which is harmless.

---

## 3. The task you are picking up

**Goal (Ari's words): "Integrate this entire project into the nightowl html
project that I've made."**

### The architectural constraint that shapes everything

NightOwl's `hub/index.html` is **statically built**. `python/build_hub.py`
bakes JSON into the page at build time, specifically because *"a file:// page
cannot fetch local JSON"* (its own docstring). It is opened from a desktop
shortcut / `no hub` / `Ctrl+Alt+H`, and rebuilt with `no sync`.

The tracker is the opposite: a live HTTP server with an MJPEG stream and
polling JSON endpoints.

### The design I had settled on (keep it unless you find it wrong)

**Baked data + live upgrade.** Do not make the hub depend on the tracker being
up:

1. `build_tracker()` in `build_hub.py` reads today's mode log
   (`logs/modes-YYYY-MM-DD.jsonl`), `profile.json`, and
   `logs/torso_baseline.json`, and returns a summary that gets baked into
   `__NIGHTOWL_DATA__`. This always works, offline, matching NightOwl's
   existing architecture.
2. The card's JS renders the baked summary immediately, then attempts
   `fetch("http://127.0.0.1:8787/api/state")`. If that succeeds, it upgrades
   the card to live (current mode, deviation, Aria's line) and can show the
   MJPEG stream. If it fails, the baked view stays and the card says the
   tracker isn't running.

**CORS is already done and verified.** `src/dashboard.py` sends
`Access-Control-Allow-Origin: *` on both `_send()` and `/stream` (confirmed
with curl, both endpoints). Safe because the socket binds to 127.0.0.1 only.

**UNVERIFIED — you must test this:** whether Brave actually permits a
`file://` page (origin `null`) to fetch `http://127.0.0.1`. Chrome's private
network access rules and Brave Shields may block it regardless of CORS. I
could not test it: the in-app browser pane renders out-of-project `file://`
pages as static snapshots, so JS never runs. **Have Ari open a probe page in
Brave himself, or drive Brave via the claude-in-chrome MCP.** The whole
"live upgrade" half of the design rests on this. The baked half does not, which
is exactly why the design is split that way.

If the live fetch turns out to be blocked, the fallback options are: serve the
hub from the tracker's own server (breaks `no hub` and the shortcut), or accept
baked-only and rebuild on `no sync`.

### Card style to match

Cards live in a `.grid` in the template string inside `build_hub.py` (~line
444+). Shape:

```html
<div class="card">
  <h2>Title<em>subtitle</em></h2>
  <div id="somethingBody"></div>
</div>
```

Data reaches JS as `const D = __NIGHTOWL_DATA__;` and cards are populated by
JS. Theme vars already exist (`--pink`, `--purple`, `--soft`). The hub
switches to a warm plum theme at wind-down on its own.

### Things worth surfacing in the card

Today's mode totals (deep_work / leisure / away / recovery minutes), the
current Perfect Ari block and whether he's on plan, and the moment strip.
Don't invent metrics — everything must trace to a log row. NightOwl's README
already claims a "webcam Productivity Coach" feeds the Solo Leveling System;
check `Solo-Leveling-System/` before adding a second, competing EXP path.

---

## 4. Hard-won findings — do NOT re-derive these

All are in CLAUDE.md in more detail. The expensive ones:

- **Resolution must be asked for.** `cv2.VideoCapture` takes the driver
  default; the project ran at 640×480 for weeks while the rig did 4K.
- **Iriun pads every 16:9 mode** — real content is exactly 75% of the requested
  width AND height, so 43% of a 4K frame is black. `capture.py` auto-crops it
  (2880×1624 out of 3840×2160). 4:3 modes are not padded.
- **A dead Iriun feed does not fail** — it streams a placeholder card (cartoon
  cat, "Looking for the phone"). `grab()` succeeds, so `reconnect()` never
  fires and it logs as `away`. Detected via byte-identical consecutive frames
  (a real sensor can't produce two identical frames) and surfaced as
  `camera_lost`, which must **never** collapse into `absent`. Regression test:
  `py -3.12 src/test_stall.py` → 13/13.
- **`posture` never reached `place()` in production** until this session. It
  was voted only in `analyze_session.reduce_burst()`, so `reclined`/
  `lying_down` were unreachable live and the whole bed-at-night branch was dead
  code. Now in `CameraState.reduce`; verified behaviour-identical on 4000/4000
  randomised bursts. **Do not split the reducer in two again.**
- **moondream is unusable for this** and is off by measurement, not by
  omission. Shown a frame where Ari was standing across the room with an empty
  chair, it said "a person sitting in an office chair... focus and
  concentration." Yes/no questions return empty strings. `VISION_CAPTIONS =
  False` in `dashboard.py`. Re-test with `llava:7b` before enabling.
- **Ground truth exists**: `sessions/IMG_9874_analysis/labels.json` +
  `score.json`. haar 66%, pose 91% over 287 scorable bursts. That session is
  100% `at_desk`, so it validates nothing about bed/absence — don't quote 91%
  as general accuracy.
- Pose at 4K costs only 3.5 ms more than at 1280; the 523 ms 4K figure in the
  notes is **Haar**, not YOLO. Detection is pinned to 1280 to match
  `analyze_session.py`'s `MAX_WIDTH` so the 91% describes what actually runs.

---

## 5. Decisions Ari made — do not quietly reverse them

- **Broad beats precise.** He moves the camera constantly for unrelated
  reasons, so a per-mount calibration is stale by design and fails *silently*.
  `src/torso_baseline.py` therefore learns his normal posture continuously
  (running median of observed angles) instead of storing a constant. **There is
  no `UPRIGHT_TORSO_ANGLE` to set any more. Do not add a calibration step
  back.** Measured proof he was right: his actual upright is ≈ 0.5° while the
  hardcoded constant was −47.0° — under the old 35° gate he'd have been logged
  `reclined` → `watching_in_bed` on essentially every sample.
- **`reclined` is deleted as a class.** It demanded a precise baseline *and*
  routed a desk-chair lean to "in bed". Two classes ~90° apart, 55° gate.
- **Aria writes the deviation line, and she never sees an image.** She gets a
  facts table only. The wall is deliberate: `mode_log.py`'s house rule is that
  every claim must come from recorded data, and `persona/aria.yaml` carries
  scar tissue from qwen2.5 inventing file contents. A vision model on the
  thumbnail is allowed but its output is confined to the tile, marked
  unverified.
- **Do not auto-switch Aria's mode.** `aria-assistant/assistant/modes.py` is
  explicit that an inferred mode is worse than none. The Perfect Ari block is
  passed as a hint; she decides.
- She is reached through her own server on session id `lifestyle-tracker` so
  tracker pings never pollute his real conversation. `server.py`'s stated
  design is "one brain, many thin clients" — be another thin client, don't
  build a second personality.
- **Stored frames are a narrow, deliberate exception** to the project's
  no-frames-stored promise: one thumbnail per mode change, capped at 40,
  oldest deleted, local only.

---

## 6. Environment gotchas

- **Never bare `python`** — it's 3.14 with no packages and dies with a
  misleading `ModuleNotFoundError: No module named 'cv2'`. Use **`py -3.12`**.
- **The shell is PowerShell.** `2>&1`, `tail`, `head` do not work there.
  Bash-style one-liners must be run in Git Bash, not pasted into PowerShell —
  Ari hit `RedirectionNotSupported` doing exactly that.
- `.ps1` execution is blocked (policy Undefined → Restricted). Run
  `py -3.12 src/....py` directly.
- **The console is cp1252** and `profile.json` is full of emoji — any script
  that prints profile text must call
  `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` first, or it
  dies in the *reporting* path after doing all the work.
- torch is **CPU-only**. Ollama does use the 4060 (~5.7 GB free).

---

## 7. Files this session created or changed

New: `src/claude_eyes.py`, `src/test_stall.py`, `src/dashboard.py`,
`src/profile_plan.py`, `src/aria_link.py`, `src/torso_baseline.py`,
`web/dashboard.html`, `profile.json`, `CLAUDE.md`,
`sessions/IMG_9874_analysis/labels.json` + `score.json`.

Changed: `src/capture.py` (resolution request, autocrop, stall detection),
`src/camera_state.py` (posture in reduce, DETECT_WIDTH), `src/pose_detector.py`
(two-class posture, camera_lost), `src/mode_log.py` (camera_lost branch),
`src/analyze_session.py` (reduce_burst is now an alias), `README.md`,
`nightowl/python/build_hub.py` (**BROKEN — see §1**).

Standalone dashboard: `py -3.12 src/dashboard.py` → `http://127.0.0.1:8787`.
It works and is verified; the NightOwl card is the only unfinished piece.

---

## 8. Suggested first moves

1. Fix or revert the two lines in `build_hub.py`; confirm it runs.
2. Delete `nightowl/hub/_corstest.html`.
3. Settle the `file://` → localhost question in **real Brave** before building
   the live half.
4. Write `build_tracker()`, add the card, run `py -3.12
   nightowl/python/build_hub.py`, and open the hub to check it.
5. Re-run `py -3.12 src/test_stall.py` (expect 13/13) before declaring done.
