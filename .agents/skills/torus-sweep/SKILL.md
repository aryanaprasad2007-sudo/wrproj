---
name: torus-sweep
description: >-
  Sweep Ari's OLI Torus courseware (CHEM 3A) and reconcile it against the Notion
  Command Center and The Docket. Use when Ari says "sweep Torus", "/torus-sweep",
  "check OLI", "are my chem scores right", "what can I still retake", or wants
  the Docket's chemistry rows validated against ground truth. Requires Ari to
  already be logged into Torus in Brave — live, read-only browser sweep.
---

# OLI Torus → Notion → Docket sweep

Sibling of `canvas-sweep`, same architecture, different source. **Canvas and
Torus are not redundant**: Canvas carries the gradebook, the tests, and the
syllabus; Torus carries the courseware — checkpoints, attempts used, scoring
policy, page-completion. A fact like "3.59/7 with all 3 attempts used" exists
only in Torus. Run both; neither substitutes for the other.

## Preconditions

1. **Ari must already be logged in.** Never touch credentials or SSO.
2. **Brave must be connected** via `mcp__claude-in-chrome__*` (`list_connected_
   browsers` → `select_browser`). The extension is named "Codex in Chrome" but
   the browser is Brave — see `[[brave-browser]]`. Do not offer a Chrome fallback.

## Where things are (verified 2026-08-17)

- Instance: `https://proton.oli.cmu.edu` — **not** `oli.cmu.edu`, which is the
  marketing site and has no student data on it.
- `/sections` **auto-redirects** to the single enrolled section. That redirect is
  the course-discovery answer; don't enumerate.
- Section: `general_chemistry_0tuo5` — CHEM 3A General Chemistry.
- Routes: `/assignments` · `/student_schedule` (**not** `/schedule`, which 403s
  to `/unauthorized`) · `/learn` · `/explorations` · `/practice` ·
  `/discussions` (this is "Notes"; it was empty — announcements live in Canvas).

## Extraction gotchas — measured, do not re-derive

- **Torus is Phoenix LiveView.** Content arrives after first paint. Always
  `wait` ~3–4s before reading, or you get bare nav text.
- **The assignments list is virtualized.** `read_page` returns only ~10 links no
  matter how large `max_chars` is; the rest are not in the DOM. Use `find` +
  `scroll_to` + click, or read the page text (which *does* carry all 28 rows).
  Refs go stale after a scroll — re-`find` before clicking.
- **The leading integers (13, 27, 79, 97…) are course-sequence ordinals, NOT
  IDs.** The prologue renders them as "79.". The stable identity key is the
  **slug** in the URL (`lewis_structures_module_checkp_w239f`). Match on slug or
  canonical URL, never on the ordinal and never on title alone.
- UCSC-customized items drop the `bzvb3_` prefix and are suffixed with a random
  token, so slugs **cannot be constructed** — they must be read off the page.
- The list page shows **date only**. The exact time lives on the prologue page.

## The scoring policy — the single most important fact

Verified independently on two assessments, so it is course policy:

- Due at **11:59 PM PDT**, timezone `America/Los_Angeles` (stated on-page).
- **"Your final score will be your best attempt out of 3."**
- **"The due date has passed. If you start a new attempt, it will be marked
  late."** — late attempts are *accepted*.

Consequence: **a retake cannot lower a banked score.** Any item with attempts
remaining is live points regardless of how far past due it is. Explorations run
`Attempt 1 of ∞`. This is what makes a scraped score actionable — record the
attempts and the policy, never the bare number.

## Reading the data honestly

- **`Done` in the Command Center means SUBMITTED, not maxed.** Every checkpoint
  row is Done regardless of score. So a Done row at 25% is *not* a status error —
  it is a hidden opportunity. Say it that way; don't call Notion wrong.
- Torus does **not** publish points-possible until the first attempt. Any
  "(5 pts)" in a task title before then is a guess. Actual totals in this course
  range 4 → 100. Flag as unverified rather than inventing a correction.
- **Absence is not deletion.** An item missing from one view is not gone; check
  `/assignments` *and* `/student_schedule` before claiming anything vanished.

## Reconciliation

Command Center data source: `collection://4f762363-ecdb-4c21-a570-da385077e117`
(✅ Command Center). Properties: `Task`, `Status`, `Priority`, `Area`,
`Due Date`, `Notes`. **There is no source/source_id property** — put provenance
in `Notes` as `source: OLI Torus · slug <slug> · <url>`. Do not redesign the DB.

Match by slug → canonical URL → course+title+due. Append dated
`[Torus sweep YYYY-MM-DD]` blocks to `Notes`; **preserve prior history** rather
than overwriting it — the older lines carry provenance worth keeping.

Then: merge validity findings into `Daily-Docket/docket_data.json` `crosscheck`
(severities `conflict` / `watch` / `info`), write `Daily-Docket/torus_state.json`,
and re-render with `py -3.12 build_docket.py` (a deterministic renderer over
`docket_data.json` — it does not re-fetch and does not write back).

## Guardrails

- **Read-only.** Never click `Begin Attempt` / `Begin Nth Attempt` — that
  consumes one of a finite, valuable set. Navigating to a prologue is a safe GET;
  clicking the button is not. Report the opportunity, let Ari spend the attempt.
- Never delete rows. Never mark something `REMOVED_FROM_SOURCE` off one view.
- Verify writes by re-query + a duplicate check; an API 200 is not proof.
- If the count of Torus assignments diverges wildly from the last sweep, STOP
  and report rather than writing.

## `should_promote()` — decided 2026-08-17

When a sweep finds a **submitted-but-recoverable** item, promote it **only if
attempts remain** and the gap is real (~20%+ of the item unrecovered). Otherwise
annotate and stay silent.

Ari chose this rule directly. The attempts-remain clause is the whole point: the
Bohr Model checkpoint had a retake card reappear after he had closed it, and its
Notion note says it "should not reappear on a future rebuild." That card was
wrong because attempts were **3/3 exhausted** — the action it demanded was
impossible. Gating on remaining attempts kills that failure mode at the source
while still surfacing genuine opportunities.

Promote as a **separate retake row**; leave the original `Done` row alone. `Done`
correctly records that the work was submitted, and overwriting it loses that.

Rank promoted items by *fraction of the item unrecovered*, not raw points — an
item at 25% is a far better use of an hour than one at 98%, even when the 98%
item carries more absolute points. Prefer items whose module falls inside the
next exam's coverage; the retake then doubles as targeted review instead of
competing with it.

Worked example (2026-08-17): 11 items had attempts remaining, but only Lewis
Structures (1/4 = 25%, Module 6 / Unit 3, inside Test 2's Units 1–4 coverage)
cleared the bar and was promoted. Chemical Bonding Unit at 85% carried more raw
points (+9.5) and was still correctly left un-promoted.
