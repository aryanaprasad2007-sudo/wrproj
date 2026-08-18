---
name: speedrun
description: Take today's Top 5 off The Docket and drive it to done as fast as possible — triage each item by who can actually act on it, finish the ones Codex can finish outright, strip every second of setup off the ones only Ari can do, and run him through them one at a time wired to the RIGHT NOW module. Use when he says "speedrun my top 5", "help me knock out my top 5", "let's tackle the docket", "what do I do first", "run my list", "help me get through today", or otherwise wants to EXECUTE the board rather than re-plan it.
---

# Speedrun the Top 5

Execution, not curation. The 6 AM run already judged what matters and
`rerank-top5` re-judges it mid-day — **this skill does not re-rank anything.**
It takes the five as given and makes them happen with the least friction
possible.

If the list is visibly wrong mid-sprint (something got done, a fire started),
say so in one line and offer `rerank-top5`. Never quietly re-order the board
here; two skills silently deciding the same thing is how the board starts
contradicting itself.

## The whole idea

Most of what makes a task slow is not the task. It's finding the tab, hunting
for the account number, re-reading what the form wants, and deciding what to
do next after each one. That overhead is per-item and it is almost entirely
removable in advance.

So the sprint is organised by **who can act**, not by importance:

| lane | means | what happens |
|---|---|---|
| **CLOSE** | Codex can finish it outright | done immediately, in parallel, no confirmation round-trip |
| **STAGE** | only Ari can execute it, but the setup is removable | every tab open, every input listed, his part starts at the actual work |
| **HIS** | just needs his hands/time/brain | protect the block, get out of the way |

Importance already picked the five. Lane picks the *order of operations*
within the sprint, because CLOSE work costs Ari nothing and should never sit
behind something he has to do himself.

## Steps

### 1. Read the board (deterministic, cheap)

```bash
py -3.12 "C:\Users\aware\OneDrive\Desktop\wrproj\.Codex\skills\speedrun\triage.py"
```

Prints the whole sprint briefing: current time against today's plan, each Top
5 item's block and whether it's `live` / `past` / `ahead` / unscheduled, how
much runway is left before the next fixed anchor, what's checkable in Notion,
what's slipping, and how many refills sit in `topBacklog`. `--json` for the
same data machine-readable, `--at HH:MM` to reason about a later hour.

Do **not** read `docket_data.json` into context to re-derive this — the script
exists so that arithmetic doesn't cost tokens every invocation.

**If it prints `*** STALE ***`, stop.** The board is not today's; the 6 AM run
failed or hasn't fired. Say so and offer to rebuild before sprinting through
yesterday's priorities.

### 2. Assign each item a lane

One pass, using what the briefing tells you plus the item's `why`. Judgment,
not keywords.

- **CLOSE** — Notion property/row edits, corrections to the board itself,
  drafting an email or message for review, file and data work, research and
  summarising, calendar events, anything in this repo, pulling up an answer he
  otherwise has to go find.
- **STAGE** — needs his hands but not his setup. Web forms, portals, anything
  behind his login, phone calls, in-person errands.
- **HIS** — reading, lecture, gym, dance, practice, writing something only he
  can write. There is no shortcut and pretending otherwise wastes his time.

### 3. Clear the CLOSE lane first, without asking

Do them now, batched in parallel where independent. These cost Ari nothing,
so every one still sitting there while he works is pure waste. Report them as
a done-list, not as a plan.

**Write straight through to Notion when the item has a `notionId`** —
`notion-update-page`, `command: "update_properties"`, `properties: {Status:
"Done"}`, exactly as the board's own check-off does. An item finished but left
`To Do` will be back on tomorrow's carryover and will count as a slip, which
makes the anti-rot ledger lie.

Anything genuinely destructive or outward-facing (sending mail, publishing,
deleting) is **not** CLOSE — draft it and hold for his yes.

### 4. Stage the STAGE lane — gather-once, then open everything

This is where the real time is won.

- **Batch the inputs.** Three credit bureaus ask for the same name, DOB,
  address, and SSN. Tell him the full union of what all of tonight's forms
  will want, once, so he gathers it a single time instead of three.
- **Open every tab up front** via the Browser pane, so there's no navigating
  between items — he lands on each form ready to type.
- **Pre-write anything paste-able** — message drafts, reference numbers,
  confirmation text — into the chat or a scratch file so it's a copy, not a
  composition.
- **Say what "done" looks like** for each, in one line, so he isn't deciding
  whether he's finished.

**Hard boundary, and it is not negotiable:** Codex does not type his
passwords, does not enter SSN / DOB / account or card numbers, does not create
accounts, and does not submit forms carrying his personal data — including
when he asks directly, and including "just this once." On items like tonight's
email lockdown and credit freeze, that means **the speed comes from staging,
not from doing.** Say that plainly rather than implying the task will be
handled. Setting an expectation of "I'll take care of it" and then stalling at
the form is slower than being clear at the start.

### 5. Run him through it one at a time, wired to RIGHT NOW

Give him **one** item at a time. A sprint that hands over five things at once
is just the board again.

When he starts one, set it as `nowTask` in `docket_data.json` (`text`, `why`,
`area`, `notionId`, `since` = today's label), rebuild with `py -3.12
build_docket.py` from `Daily-Docket/`, and republish to the same artifact url
`https://Codex.ai/code/artifact/98bafd13-a2a6-4b05-83a8-84c357fa4dc1`
(`file_path` `docket_widget.html`, `favicon` 📋, `title` `The Docket`, omit
`capabilities` so the stored grants carry). Rebuilding without republishing
changes files on disk and nothing he looks at — they are two separate claims.

A non-zero exit from `build_docket.py` (`DOCKET BUILD FAILED:`) means **do not
republish**; fix what it names first.

When he says an item is done: write Notion `Status=Done`, advance `nowTask` to
the next lane-appropriate item, rebuild, republish, confirm in one line. When
the Top 5 empties, pull the next entry from `topBacklog` rather than declaring
victory — the board's own auto-refill does exactly this.

### 6. Respect the clock

The briefing names the next fixed anchor and the runway to it. Don't start a
1-hour block with 15 minutes left — use the gap for a CLOSE item or the
staging for what comes after the anchor. `past` blocks are the honest signal
that the day's plan has drifted; name it once, don't nag.

### 7. Close the sprint

One short summary: what's actually done, what's staged and waiting on him,
what he should drop. Be straight about anything left — a sprint that reports
five done when three are done is worse than no sprint.

## Notes

- Never bare `python` — `py -3.12`. See AGENTS.md.
- New information from Ari during the sprint follows the standing protocol:
  Notion first, then re-sync, then republish ([[docket-update-protocol]]).
- If he proposes a change to how the *sprint itself* should work, that's a
  routine idea — fold it into this file the same turn, per
  [[docket-right-now-module]].

Related: [[docket-artifact]], [[docket-right-now-module]],
[[docket-update-protocol]], [[notion-command-center]], `rerank-top5`
(the sibling that decides the five this one executes).
