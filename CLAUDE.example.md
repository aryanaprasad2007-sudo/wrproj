# wrproj — personal instrumentation lab (example instructions)

This repo is driven day-to-day by a `CLAUDE.md` at the project root that is
**intentionally not committed** — it's the working-instructions file for
Claude Code / an AI coding agent, and it accumulates a lot of personal
context (routines, room/hardware setup, in-progress life details) that
doesn't belong in a public repo.

This file is the public stand-in: it explains the project's shape and rules
without the personal payload, so a fresh clone can bootstrap a real
`CLAUDE.md` of its own if you want to run an agent against this codebase.

## What this project is

A personal instrumentation lab: a set of small, mostly local-first tools that
try to give one person an honest, continuously-updated picture of their own
day — what they're doing, whether it matches their plan, and where their own
tracking is lying to them.

The flagship subproject is a **lifestyle tracker**: a camera + screen sensor
pair that infers "mode" (deep work, watching, resting, away, etc.) and writes
a timeline log, on the theory that self-reported time tracking is
unreliable and passive sensing is not. See `src/` and its own `README.md`.

Everything else in the repo — a dashboard, a calendar app, a trading
research desk, a Discord bot, an AI assistant persona, animation tooling —
is a satellite project built by the same person, at different times, for
different reasons. Not all of them are finished or currently maintained.

## House rules worth keeping if you fork this

- **A success flag must be derived from the thing itself, never from the
  absence of an exception.** The recurring bug pattern here was a script
  reporting "done" or "present" purely because nothing crashed, when the
  actual sensor/API/process had silently failed. Every "it worked" claim
  should be checked against real evidence, not just a clean exit code.
- **Measure before you claim.** Where there's a scored/replayable test
  fixture, changes get scored against it rather than asserted from intuition.
- **Don't let one subproject silently break another.** Several tools here
  read each other's output files; if you rename or restructure one, check
  what downstream consumes it before you do.

## Setting up your own local CLAUDE.md

Copy this file to `CLAUDE.md`, then add whatever local, personal, or
environment-specific detail makes sense for your own setup: real file paths,
your own daily routine if relevant to a tracker like this, credentials
locations, hardware quirks, and so on. `.gitignore` already excludes
`CLAUDE.md` and `WHOAMI.md` so that content stays local.
