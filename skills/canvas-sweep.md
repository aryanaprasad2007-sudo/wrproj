---
name: canvas-sweep
description: >-
  Sweep Ari's UCSC Canvas and fold his classes into The Docket. Use on demand
  when Ari says things like "sweep my Canvas", "go through my classes", "update
  the Docket from Canvas", "process my classes", or "pull my Canvas assignments".
  Requires Ari to already be logged into Canvas in his browser (Duo cleared) —
  this is a live, read-only browser sweep, NOT a scheduled task.
---

# Canvas → Docket sweep

An **on-demand** routine. Ari opens Canvas in his browser and clears Duo SSO
himself, then asks you to run this. You drive the browser read-only, pull the
ground-truth state of each class, and merge it into The Docket (and the Notion
Command Center so tomorrow's 6 AM `daily-docket` run keeps it).

Why on-demand and not scheduled: a scheduled task can't open Ari's local browser
and can't clear Duo. Those are hard blockers — do not try to work around them.
See `[[canvas-ucsc]]` and `[[docket-artifact]]` in memory for background.

## Hard preconditions — check first

1. **Ari must be logged into Canvas already.** You cannot enter his CruzID Gold
   password or clear Duo. If a page shows a login/SSO/Duo screen, STOP and ask
   him to finish authenticating in the tab, then resume. Never touch credentials.
2. **A controllable browser must be connected.** Use the *Claude in Chrome*
   tools (`mcp__claude-in-chrome__*`; load via ToolSearch if deferred). Call
   `list_connected_browsers` / `select_browser`. The connected browser **is Ari's
   Brave** — the *Claude in Chrome* extension is installed in Brave (and only
   Brave). Brave is Chromium-based, so it reports `chrome://` URLs and the
   extension is named "Claude in Chrome"; that's expected and does NOT mean it's
   Google Chrome. Do not call it Chrome or offer a "Chrome fallback." See
   `[[brave-browser]]` in memory. If nothing connects, tell Ari to make sure the
   extension is active in Brave where Canvas is open, and stop.

If either precondition fails, report exactly what's missing and wait — don't
half-run the sweep.

## Step 1 — Discover current courses (don't hardcode)

Terms change, so read the live list. Front the Canvas tab, then
`read_page` / `get_page_text` on the dashboard (`https://canvas.ucsc.edu/`) or
`https://canvas.ucsc.edu/courses` to get each active course's name + numeric ID.

Known IDs (Summer 2026 — treat as **hints/fallback only**, verify against what's
actually shown, and expect them to change in a new term):
- **ANTH 1 — Intro to Biological Anthropology** → `94170`
- **Orientation Course (f26)** → `93332`
- **SHAPE Student Training 2026-27** → `3~2689010`

## Step 2 — Pull ground truth per course

For each active course, visit and extract with `read_page` / `get_page_text`
(prefer the accessibility tree over screenshots):

- **Grades** — `/courses/<id>/grades` — current overall %, and which items are
  already submitted/graded. This is the source of truth for what's *done*;
  module/assignment text alone does NOT reveal completion. Use it to avoid
  re-adding finished work.
- **Assignments / syllabus** — `/courses/<id>/assignments` or
  `/courses/<id>/assignments/syllabus` — upcoming items and due dates/times.
- **Announcements** — `/courses/<id>/announcements` — instructor changes,
  reminders, action items.

Also check the consolidated forward views: the dashboard **To-Do / "Coming Up"**
sidebar and `https://canvas.ucsc.edu/calendar` for anything not surfaced per
course.

If a page fails to load or the session expired mid-sweep, say so and pause for
re-auth — never guess a grade or a due date. Accuracy is the whole point of a
browser sweep.

## Step 3 — Normalize into Docket items

Get today's date first. For each unsubmitted assignment / open action item,
classify relative to today and build a row:

- **Overdue** (due date < today, not submitted) → `carriedOver` lane, with a
  `when` that states how overdue.
- **Due today** → `dueToday` lane.
- **Due within ~7 days** → `thisWeek` lane, with `due` as the date.
- Skip anything already submitted/graded (per the grades page).

Field conventions (match the existing `docket_data.json`):
- `area`: `"School"` always.
- `source`: `"Canvas sweep"`.
- `priority`: `"High"` for graded labs, exams, and hard deadlines within 48h;
  `"Medium"` for routine upcoming work; `"Low"` for optional/reading.
- `text`: course + item, e.g. `"ANTH 1 Lab 8: Genus Homo Comparative Analysis"`.
- `when` / `due`: human date + time, e.g. `"Due Fri Jul 24 at 11:59 PM"`.

## Step 4 — Persist and render

Data files live in `C:\Users\aware\OneDrive\Desktop\wrproj\Daily-Docket\`.

1. **Notion Command Center (durable).** Query the Command Center data source
   first (`mcp__bcfd450e-…__notion-query-data-sources`) to learn its properties
   and to check for an existing matching task. **Update** the match or **create**
   a new task — do not create duplicates. This is what makes the item survive
   into tomorrow's 6 AM `daily-docket` run. (If Notion isn't connected this
   session, still do the Docket merge below and tell Ari the Notion step was
   skipped.)
2. **Docket board (immediate).** Read `Daily-Docket/docket_data.json`, then
   **merge** the new rows into `carriedOver` / `dueToday` / `thisWeek`. Dedupe by
   fuzzy text match — the 6 AM run already pulls Calendar (ANTH DUE dates),
   Command Center, and Gmail, so items like an ANTH lab may already be present;
   prefer updating an existing row over adding a second one. Write the file back
   (preserve all other lanes and top-level fields exactly).
3. **Stamp the sweep.** Write `Daily-Docket/canvas_state.json`:
   ```json
   {"lastSweep": "2026-07-26", "courses": ["ANTH 1 (94170)", "..."], "note": "optional one-liner"}
   ```
   Do this **only after a sweep that actually read Canvas** — never on a run that
   stopped at the Duo/login gate, or the staleness check starts lying. The 6 AM
   `daily-docket` run reads this file (its step 4b) and raises a `watch` flag
   when the last sweep is more than 7 days old, which is the only thing keeping
   Canvas from being a silent blind spot between sweeps.
4. **Re-render.** Run `py build_docket.py` from the `Daily-Docket` folder.
5. **Show it.** `preview_start` with name `docket` (or reload the tab if the
   preview server is already up) so Ari sees the refreshed board.

## Step 5 — Report

Give Ari a tight per-course summary: current grade %, what's newly due / changed,
what got added or updated on the Docket, and what was already covered. Call out
anything that needs him — overdue items, blockers, or an expired Canvas session.

## Guardrails

- **Read-only in Canvas.** Never submit an assignment, never click send / submit
  / confirm / any irreversible control, never change Canvas or account settings.
- **No credentials, ever.** If SSO/Duo appears, hand it back to Ari.
- **No fabrication.** If a page didn't load, report the gap rather than guessing.
- **Dedupe before writing** to both Notion and the Docket.
