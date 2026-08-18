---
name: rerank-top5
description: Re-judge Ari's Top 5 on The Docket right now, mid-day, without a full morning rebuild. Use when he says "re-rank my Top 5", "redo my top 5", "what should I actually focus on right now", "curate my day again", or asks Codex to reconsider what's most important today given something that's changed since the 6 AM run.
---

# Re-rank Top 5 — on-demand

A lighter, on-demand sibling of the `daily-docket` scheduled task. That task
rebuilds the whole board every morning; this one re-judges just
`topPriorities` / `topBacklog` against the current moment, without touching
the parts of the board that don't need touching.

**When Ari asks for this mid-day, something has usually changed** since 6 AM:
he finished something, a new fire came up, plans shifted, or the morning's
picks just don't feel right now that he's actually living the day.

## Steps

1. Read today's board: `C:\Users\aware\OneDrive\Desktop\wrproj\Daily-Docket\docket_data.json`
   and `slips.json` (read-only — the renderer owns writes to `slips.json`,
   never edit it here).
2. Fresh SQL read of the Command Center (same query as `daily-docket` step
   5): `SELECT url,"Task","Status","Priority","Area","date:Due Date:start" AS due,"Notes" FROM "collection://4f762363-ecdb-4c21-a570-da385077e117" WHERE "Status" != 'Done' ORDER BY due`.
   This is what catches anything Ari checked off since this morning (check-off
   writes `Status=Done` back to Notion) or anything new since the last run.
3. If Ari mentioned something new in this conversation that isn't in Notion
   yet, write it there FIRST per [[docket-update-protocol]] — Notion is the
   source of truth, never leave new info only on the board.
4. If NightOwl is running, read `C:\Users\aware\OneDrive\Desktop\wrproj\nightowl\data\state.json`
   for the current `mode` (work/game/anime/winddown/sleep) — a signal about
   where he actually is right now, not a hard rule. Late-mode or wind-down
   generally argues for fewer, smaller entries, not a fresh full five.
5. Re-derive `topPriorities` and `topBacklog` using the SAME judgment rubric
   as `daily-docket` step 7b — **read that file**
   (`C:\Users\aware\.Codex\scheduled-tasks\daily-docket\SKILL.md`) for the
   current rubric rather than duplicating it here, since it's the single
   source of truth for how Top 5 gets picked (real stakes weighed against
   each other, the 3+ slips and quiet-Area floors, verb-first/finishable,
   `why` states real reasoning, never pad to five). Anything now Done drops
   off; anything just added folds in.
6. Leave every other key in `docket_data.json` untouched — `plan`, `schedule`,
   `email`, `notionHub`, `exploration`, `crosscheck`, `trading`, `sources`,
   `carriedOver`, `dueToday`, `thisWeek`. This is a re-rank, not a rebuild;
   don't re-run Calendar/Gmail sweeps or step 5c's auto-scheduling.
7. Run `py build_docket.py` (from `Daily-Docket/`), then republish to the
   SAME live artifact: `url` `https://Codex.ai/code/artifact/98bafd13-a2a6-4b05-83a8-84c357fa4dc1`,
   `file_path` `docket_widget.html`, `favicon` `📋`, `title` `The Docket`.
   Omit `capabilities` so the stored Notion + Calendar grant carries forward.
8. Confirm in one line what changed and why — e.g. "Top 5 re-ranked as of
   2:15 PM — swapped the DMV call for the CHEM problem set, its due date is
   tighter than it looked this morning."

Related: [[docket-artifact]], [[docket-update-protocol]], [[nightowl-desk-system]].
