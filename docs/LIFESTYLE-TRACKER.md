# Lifestyle Tracker

Watches your room and your screen, works out what you're actually doing, and
writes a timeline of it. Built to answer "where did my day go" without you
having to log anything by hand.

Everything runs locally. No frames are stored — each one is classified in
memory and discarded — and the log holds labels and timestamps only.

## The two sensors

Neither one can label a mode alone. That's the whole design.

| Sensor | Answers | Blind to |
|---|---|---|
| **Camera** (`camera_state.py`) | Where you are, how you're sitting | What's on screen — coding and anime are the same image |
| **Screen** (`window_sensor.py`) | What's in front of you | Whether you're still in the chair |
| **Clock** (`mode_log.py`) | Whether that's OK right now | — |

The clock is a real input, not decoration. Bed + anime at 23:30 is `recovery`;
the identical camera frame and identical window title at 14:00 is `watching`.
Nothing but the hour separates them.

Both sensors report **facts, not judgments**. The screen sensor reports
`category` and `idle` separately rather than collapsing them, because no input
for five minutes means opposite things for a playing video versus an open
editor — and only the camera can tell those apart.

## Modes

| Mode | Means |
|---|---|
| `deep_work` | Work/school on screen, actively inputting — desk *or* bed |
| `work_paused` | Same, but no input — reading, thinking, or stalled |
| `leisure` | Games/social/shopping, awake hours |
| `watching` | Passive content playing with you in front of it |
| `watching_in_bed` | Lying down watching, during the day |
| `resting` | Lying down, nothing much on screen |
| `recovery` | Any of the above during night hours — this is fine |
| `on_phone` / `phone_night` | Phone in hand; attention is off both screens |
| `away` | Nobody in frame, screen idle or locked |
| `screen_abandoned` | Nobody in frame but something active was left open |
| `present_unclear` | You're there, posture unreadable, screen inconclusive |
| `camera_lost` | The camera feed is dead — **not** a claim about where you are |

`camera_lost` exists because a dead Iriun feed doesn't fail, it streams a
placeholder card. That image contains no person, so without a separate state it
becomes a convincing `absent` and the log grows a stretch of `away` that never
happened. `absent` is a claim about *you*; `camera_lost` is a claim about the
*rig*, and a log that can't tell them apart isn't recording your life. The
screen sensor is unaffected by the outage, so active input still counts.

Modes involving lying down require the **pose** detector — the Haar detector
cannot tell sitting from lying, so it never emits them.

## Which Python

Bare `python` on this machine is **3.14** and has none of these packages —
it starts fine and then dies with `ModuleNotFoundError: No module named 'cv2'`,
which looks like a missing package but is actually the wrong interpreter.
The stack lives on **3.12**. Either spell it explicitly:

```bash
py -3.12 src/mode_log.py
```

or use the launcher, which finds a working interpreter by importing cv2 rather
than trusting PATH:

```bash
.\run.ps1 doctor
```

The rest of this README uses the launcher.

## Run it

```bash
.\run.ps1 log
```

Ctrl+C stops and flushes the run in progress. Then:

```bash
.\run.ps1 today
```

which prints the day's timeline plus totals per mode. Logs are one JSON line
per **run** (a contiguous stretch in one mode), in `logs/modes-YYYY-MM-DD.jsonl`
— a few dozen rows a day, not thousands of samples.

## Validate the camera first

The camera's error rate is the one number that decides how much to trust the
log. Measure it before relying on anything:

```bash
.\run.ps1 validate present 3
```

Sit and work for 3 minutes without leaving. Because the truth is constant for
the whole trial, **every reading that disagrees is by definition an error** —
no frame labelling needed. Then the other direction:

```bash
.\run.ps1 validate absent 1
```

Each tick records a burst of 9 raw frames, and burst sizes 1/3/5/7/9 are
replayed against that same recording — so one sitting scores every candidate
on identical data. The output ends with the burst size to set in
`camera_state.py`.

### Why bursts instead of a rolling window

A Haar cascade run on two consecutive frames of someone sitting perfectly
still will routinely find a head in one and not the other. The obvious fix — a
rolling window over production samples — is a trap: at a 15s sample interval, a
5-sample window lags by 75 seconds.

But the flicker is *frame-to-frame* noise, so it averages out over one second
just as well as over five minutes. Every tick grabs 5 frames back-to-back and
votes. Same statistical idea, no latency.

Vote thresholds differ per axis, matching each detector's error profile: YOLO's
person detection is accurate both ways so presence takes a plain majority,
while the head cascade has high precision and poor recall — a hit is strong
evidence, a miss is weak — so one hit in three is enough.

### Scoring recorded footage

Live trials only cover one situation at a time. A long recording covering desk
work, breaks, walking around, and lying in bed is worth more, and it lets two
detectors be compared on identical frames:

```bash
.\run.ps1 analyze latest --both --every 5
```

That runs Haar and pose over the same bursts and prints where they disagree —
every such row is a frame where they cannot both be right. Contact sheets in
`sessions/<name>_analysis/` are how you settle it: read off the indices it got
wrong and what you were actually doing.

On the CPU-only torch build here, expect roughly a minute of analysis per
minute of footage per detector at `--every 5`. Ctrl+C is safe and writes
partial results.

### Why the head check is constrained to the person box

The camera sits off to one side, so a *frontal* face cascade doesn't find you —
but it happily matches the photo collage on the wall, which scored an empty
room as productive. Faces are searched with the **profile** cascade and only
**within YOLO's person box**. A face outside the person isn't a face, it's decor.

## Setup

1. **Python 3.12** — `winget install Python.Python.3.12`
2. **Dependencies** — `py -3.12 -m pip install -r requirements.txt`
   (note the explicit `-3.12`; first run auto-downloads a ~6 MB model)
3. **Camera** — this rig uses [Iriun](https://iriun.com/) (phone as webcam);
   the phone app must be connected and the PC client running. If the phone
   drops off WiFi, Iriun keeps streaming a placeholder card rather than
   failing — the tracker now detects that and logs `camera_lost`, but the
   feed still needs reconnecting before the camera means anything.

## Tuning

| File | Holds |
|---|---|
| `apps.json` | Which apps/sites map to which category. **Meant to be corrected** — anything landing in `unknown` or `browsing` is a line to add. Browser needles match the **window title**, not the URL. |
| `modes.json` | Night window, category groups, debounce length, sample interval |
| `camera_state.py` | Burst size and the per-axis vote thresholds |

`min_run_seconds` in `modes.json` is the debounce: a mode must hold this long
before it's committed. Without it, glancing at Discord for eight seconds carves
a two-hour work block into three rows and the rollup reports fragmentation that
never happened.

## Layout

| Path | Role |
|---|---|
| `run.ps1` | Launcher; resolves a Python that actually has cv2 |
| `src/mode_log.py` | **Main loop.** Resolver + run logger + `today` view |
| `src/camera_state.py` | Burst voting; turns flickery frames into a stable reading |
| `src/window_sensor.py` | Foreground window, process, idle time |
| `src/local_detector.py` | YOLOv8 + Haar, person-box constrained |
| `src/pose_detector.py` | YOLOv8-pose keypoints; adds posture (sitting vs lying) |
| `src/validate_camera.py` | Ground-truth error measurement (live trials) |
| `src/capture.py` | Webcam access, backend fallback + reconnect |
| `src/watcher_nudge.ps1` | The intervention card |
| `src/claude_eyes.py` | Contact sheets for Claude to label; scores detectors against them |
| `src/test_stall.py` | Regression test for the dead-camera bug |
| `src/record_session.py` | Record footage for offline analysis |
| `src/analyze_session.py` | Replay the detector over recorded footage |

## Ground truth

The detectors are scored against labels, not impressions:

```bash
py -3.12 src/claude_eyes.py sheet <video> --every 30   # blind contact sheets
py -3.12 src/claude_eyes.py score <session>            # once labelled
```

The sheets are **blind** by default — no detector output printed on the tiles,
not even the colour bar — because a tile that already says `at_desk` pulls the
judgement toward `at_desk`, and ground truth contaminated by the thing it scores
is worthless. Use `--audit` to show the guess when you're hunting for *where*
the detector is wrong rather than establishing what was true.

Labelling one session permanently converts it into a regression test: any
threshold change can be re-scored against it without labelling anything again.
Current scores are in `CLAUDE.md`.

### Superseded

`src/main.py` and `src/reinforcement.py` are from the original binary
productive/lazy + screen-flash design, before this became a tracker. They are
not used by `mode_log.py`.

`src/claude_judge.py` joins them. It sent one frame to the API for one word
("productive"/"lazy") — both the punisher vocabulary and the most expensive
possible way to use a vision model. `claude_eyes.py` replaces it: Claude labels
sessions in bulk from contact sheets instead of judging frames one at a time.
