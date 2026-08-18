# wrproj

**A personal instrumentation lab** — self-built tools for turning a day into
data instead of a vague impression of one. Built and maintained by
**Aryan Prasad** ([aryanaprasad2007-sudo](https://github.com/aryanaprasad2007-sudo)).

Most software here answers one question: *what actually happened, and does
it match the plan?* Rather than trusting self-reported logs, the flagship
project senses it directly — a desk camera and a screen watcher that infer
what you're doing without you having to type anything.

## The house rule

> A success flag must be derived from the thing itself, never from the
> absence of an exception.

That sentence is the throughline of this repo. The recurring bug pattern
across every subproject here has been the same shape: a script reporting
"done" because nothing crashed, not because the thing it claims to have done
actually happened — a webcam feed silently going stale and still returning
frames, a headline scanner running against a dead API key and logging a
clean exit, a script quietly picking up the wrong Python interpreter. Every
tool below tries to check the real thing, not just the absence of an error.

## Flagship: the lifestyle tracker

A camera + screen sensor pair that classifies what you're doing (deep work,
watching, resting, away, phone, ...) into a continuous timeline log — no
manual logging required. Two sensors, deliberately kept from agreeing with
each other's blind spots:

| Sensor | Answers | Blind to |
|---|---|---|
| **Camera** | Where you are, how you're sitting | What's on screen |
| **Screen** | What's in front of you | Whether you're still in the chair |
| **Clock** | Whether that's fine right now | — |

Detectors are scored against hand-labelled ground truth rather than tuned by
eye — see [`docs/LIFESTYLE-TRACKER.md`](docs/LIFESTYLE-TRACKER.md) for the
full writeup, architecture, and setup instructions.

## Other subprojects

This repo has grown into a small estate of tools built at different times
for different reasons — not all equally finished or maintained.

| Project | What it is |
|---|---|
| [`nightowl/`](nightowl/README.md) | A circadian/mode-aware desktop shell — themes, prompts, and automation keyed to time of day |
| [`grimoire-calendar/`](grimoire-calendar/README.md) | A starry, month-view calendar web app |
| [`daily-docket-pwa/`](daily-docket-pwa/README.md) | An installable daily-planning PWA that pulls from Google Calendar |
| [`focusflow-v2/`](focusflow-v2/README.md) | A focus-session timer/companion |
| [`animation-studio/`](animation-studio/README.md) | A local, GPU-based AI animation pipeline |
| `Solo-Leveling-System/` | A gamified XP/leveling overlay for daily tasks |
| `enchanted-night-garden-xr/` | An in-progress Unity XR prototype |
| `aria-assistant/` | A local voice-assistant persona/companion (separate git history) |

## Design principles across the repo

- **Facts, not judgments.** Sensors report what they observed (a category, a
  posture, an idle duration), and a separate layer decides what that means —
  so the same raw signal can be reinterpreted without re-instrumenting
  anything.
- **Measure, then replay.** Where a detector or heuristic can be scored
  against a fixed, labelled fixture, changes are graded against that fixture
  instead of judged by feel.
- **Local-first.** Camera frames aren't stored; inference happens on-device;
  cloud calls are the exception, not the default.

## Stack

Python (detection, sensors, scoring), vanilla JS/HTML/CSS (dashboards and
web apps), PowerShell (Windows launchers/automation), and a handful of local
models (YOLOv8-pose, Ollama-served LLMs) — no cloud dependency required to
run the core tracker.

---

Personal config, working notes, and any file with real personal detail
(`CLAUDE.md`, `WHOAMI.md`, finance/resume/trading content) are intentionally
excluded from this repo — see `.gitignore` and
[`CLAUDE.example.md`](CLAUDE.example.md) if you're forking this and want to
know what's missing and why.
