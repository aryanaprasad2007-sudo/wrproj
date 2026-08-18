---
name: docket-to-calendar
description: Sync Ari's open Docket tasks onto Google Calendar and Todoist for the coming week, fitting each one into a real free block instead of leaving it as a line on a list. Use when he says "sync my docket to calendar", "schedule my week", "plan my week from the docket", "put my tasks on the calendar", "block time for my to-dos", or anything asking Codex to turn the Docket's worklist into an actual weekly schedule (and mirror it to Todoist).
---

# Docket → Calendar → Todoist sync

The Docket ([[docket-artifact]]) is a great worklist but a flat one — it says
*what* needs doing, not *when*. This skill takes that list and drops each
open task into a real free slot on Ari's Google Calendar over the next 7
days, then mirrors the same schedule into Todoist so both tools agree. It's
an on-demand weekly planning pass, not part of the 6 AM automation — run it
whenever Ari asks, and re-run it whenever the Docket has changed enough that
the calendar has drifted from it.

**Why scheduling (not just listing) matters to Ari:** a task with no time
attached competes for attention with everything else all day. Giving it a
slot is what actually gets it done — see [[daily-routine]] for how deliberately
he shapes his day around fixed anchors (gym, dance, deep work). This skill
respects those anchors rather than paving over them.

## The tagging contract (read this before touching the calendar)

Every event this skill creates carries a hidden marker in its **description**:
`[docket-sync:<task-id>]` where `<task-id>` is the Command Center page id (or
a stable hash of the task text if it has no Notion page). This is the *only*
way the skill tells "an event I created" apart from "an event Ari made
himself" — matching on title alone risks silently deleting or rewriting a
manual event that happens to share a name. **Never touch, move, or delete a
calendar event that doesn't carry this marker.** When updating a task that
moved, find its old event by searching for its marker, not its old title.

## Steps

1. **Pull the open task list.**
   - Read the live Docket data at `Daily-Docket/docket_data.json` — Top 5,
     Carried Over, Due Today/Overdue, This Week — for the current picture.
   - Cross-check with a fresh Command Center SQL read (same query pattern as
     `rerank-top5` step 2:
     `SELECT url,"Task","Status","Priority","Area","date:Due Date:start" AS due,"Notes" FROM "collection://4f762363-ecdb-4c21-a570-da385077e117" WHERE "Status" != 'Done' ORDER BY due`)
     so a task Ari checked off since the last Docket rebuild doesn't get
     scheduled by mistake.
   - Note each task's Priority (High/Medium/Low), Area, and Due Date — these
     drive both slot placement and calendar color (below).

2. **Estimate duration per task**, since the Docket doesn't record one. Use
   this default-by-type heuristic unless a task's Notes/title states a real
   duration:
   - Quick admin (email, a call, a form, a single errand) → **30 min**
   - A normal task (problem set section, a chore, most Personal/Admin items) → **60 min**
   - Deep-work or project-shaped work (studying a chapter, trading research,
     writing something substantial) → **120 min**
   Areas that are inherently deep-work-shaped (School, Pre-Med, Trading) lean
   toward the 60/120 end; quick Admin/Personal items lean toward 30. When
   genuinely unsure, 60 min is the safer default than guessing short and
   under-booking the day.

3. **Scan Calendar for free blocks over the next 7 days.** Use
   `list_events`/`search_events` on the primary calendar
   (your primary Google account — see [[google-calendars]], **not** the
   abandoned "Daily Routine" calendar) to get every existing event, then
   compute the gaps. A usable slot is:
   - **At least 30 minutes**, between existing events
   - **Never before 6:00 AM or after 8:00 PM** local time — clip or skip any
     gap that would push a task outside that window
   - Not overlapping a fixed routine anchor from [[daily-routine]] (gym, meals,
     class blocks) unless the gap tool already shows it as free — those
     appear as real calendar events, so they're naturally excluded once
     pulled in this step, not something to re-derive from memory.

4. **Match tasks to slots.** Sort tasks by priority: hard-deadline-within-72h
   first, then High priority, then Medium, then Low — same instinct as the
   Docket's own Top-5 rubric ([[docket-artifact]] step 7b), just applied
   across the whole week instead of five slots. For each task in that order,
   place it in the earliest free slot that both fits its estimated duration
   and lands on or before its Due Date (tasks with no due date can go
   anywhere in the week). Consume the slot (split the remainder into a new
   smaller gap if the task didn't fill it entirely) before moving to the next
   task.

5. **Create the calendar events.** For each scheduled task, call `create_event`
   with:
   - `summary`: the task text, verb-first as it appears in the Docket/Command Center
   - `description`: one short line of context (why it matters / its Area —
     e.g. "Pre-Med · problem set due Fri") **plus** the hidden marker
     `[docket-sync:<task-id>]` on its own line at the end
   - `start`/`end`: the matched slot, `timeZone` matching Ari's local zone
   - `colorId`: a **Y2K pastel** mapped by Area so the week reads at a glance
     (Google Calendar's named colorId palette — pick the closest match, these
     are the good pastel/candy ones, not the muddy defaults):
     - School → Lavender (`1`)
     - Pre-Med → Flamingo (`4`, soft coral-pink)
     - Trading → Banana (`5`, soft yellow)
     - Health → Sage (`2`, soft mint)
     - Personal → Grape (`3`, soft purple)
     - Admin → Peacock (`7`, soft aqua)
     - Interest → Tangerine (`6`, soft orange)
   This lines up with [[ui-design-preference]]'s Y2K-cute standing direction —
   bright, candy, legible colors, not washed-out or dark.

6. **Reconcile events that already exist.** Search existing events for the
   `[docket-sync:` marker (across the 7-day window) before creating anything
   new:
   - If a task's marker-tagged event still matches its current priority/due
     date/existence in the Docket, leave it alone.
   - If the task's timing should change (priority shifted, due date moved) or
     its estimated slot changed, `update_event` the existing tagged event
     rather than creating a duplicate.
   - If the task was completed or removed from the Docket/Command Center
     since it was last scheduled, `delete_event` its tagged event.
   This is what keeps a re-run idempotent — running the sync twice in a row
   should converge, not double-book the week.

7. **Mirror the schedule to Todoist.** For each task that got a calendar slot:
   - If a matching Todoist task doesn't exist yet (search by content, or by a
     `docket-sync` label if you're adding one), create it with `add-tasks` —
     `content` = task text, `due` = the scheduled date (and time, if Todoist's
     due-datetime is available), `priority` mapped from the Docket priority
     (High→4, Medium→3, Low→2), and the project set to whichever Todoist
     project best matches the task's Area (create one per Area the first time
     if none exists yet — School, Pre-Med, Trading, Health, Personal, Admin,
     Interest).
   - If it already exists, use **`reschedule-tasks`** to move its due date —
     never `update-tasks` for a date change, since that overwrites the whole
     due string and can silently strip recurrence off a recurring task.
   - If a task's calendar event was deleted in step 6 (done/removed), mark the
     matching Todoist task complete via `complete-tasks` rather than leaving
     it stale.

8. **Report back.** Summarize in one message:
   - What got scheduled (task → day/time), grouped by day for readability
   - What got rescheduled or removed and why
   - Any tasks that **could not fit** in the week — the week ran out of free
     6am–8pm room before the list did. Name them explicitly; don't silently
     drop them. Flag whether that's because the week is genuinely full, or
     because the task's own due date is too soon for its size to fit — those
     call for different responses from Ari (accept a busy week vs. renegotiate
     the deadline).

## Notes

- This is read/write against both Calendar and Todoist by design — unlike
  the Docket's own unattended 6 AM run (which never writes to Calendar
  automatically, see [[docket-artifact]] "+ Cal"), this skill is **explicitly
  invoked by Ari**, so creating/moving/deleting events on his behalf is the
  point, not a risk to gate behind a button tap.
- If Todoist tools aren't connected, or Calendar isn't, say so plainly and
  scope the run to whichever side is available rather than failing silently.
- Don't schedule anything already Done, and don't schedule reference/dashboard
  Notion pages that aren't real actionable tasks (see [[notion-command-center]]
  on what belongs in Command Center vs. reference pages).
