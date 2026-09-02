---
name: google-accounts-sweep
description: >-
  Sweep Ari's secondary Google accounts (Gmail, Drive, Calendar — not his
  primary account, which already flows into the 6 AM daily-docket run via
  connector) and fold anything actionable into The Docket. Use when Ari says
  "sweep my other accounts", "check my other Gmail", "pull my second/work
  account", "what's going on in my other Google accounts", or wants Drive/
  Calendar/Gmail checked for an account beyond his main one. Requires Ari to
  already be logged into those accounts in Brave — this is a live, read-only
  browser sweep, NOT a scheduled task.
---

# Secondary Google accounts → Docket sweep

Sibling of `canvas-sweep` / `torus-sweep`, same architecture, different source
— and a narrower job than it sounds. **This skill does not touch Ari's
primary Google account.** That account's Gmail and Calendar already flow into
`docket_data.json` unattended every morning via the connector-based
`search_threads` / `list_events` MCP calls the 6 AM run uses — no browser
involved, no re-doing that work here. This skill exists only for the
accounts that have no connector: the ones reachable *exclusively* by being
logged into Brave.

## Why on-demand and not scheduled

Same hard limit as Canvas/Torus: a scheduled cloud run can't drive Ari's
local Brave. Unlike Canvas, these accounts don't have a Duo gate — sessions
just sit logged in — so in principle this *could* run unattended if Ari
starts it from a Claude Code session already alive on his own machine (e.g.
he messages that session from his phone while getting ready). But it cannot
run from a session that has no access to his desktop's browser. Don't try to
route around that; tell him plainly which case he's in if it comes up.

## Preconditions — check first

1. **Ari must already be logged into each secondary account in Brave.** You
   cannot enter a password or clear any verification step. If a page shows a
   login/verification screen for an account, skip that account, log it, and
   move on — don't stop the whole sweep for one account.
2. **A controllable browser must be connected.** Use the *Codex in Chrome*
   tools (`mcp__claude-in-chrome__*`; load via ToolSearch if deferred). Call
   `list_connected_browsers` / `select_browser`. The connected browser **is
   Ari's Brave**. Do not call it Chrome or offer a "Chrome fallback." See
   `[[brave-browser]]` in memory.

If either precondition fails, report exactly what's missing and wait.

## Step 1 — Map accounts to `authuser` indices, and verify, don't assume

Google distinguishes accounts on the same Brave profile via the `authuser`
index in the URL, not via separate logins:
- Gmail: `https://mail.google.com/mail/u/{i}/#search/<query>`
- Drive: `https://drive.google.com/drive/u/{i}/recent`
- Calendar: `https://calendar.google.com/calendar/u/{i}/r`

Indices are **not guaranteed stable** across sessions. Before trusting index
`i` for a given account, read the account-switcher avatar/email on the page
itself and confirm it matches the email you expect. If the expected account
isn't present at that index, or fewer accounts show up than expected, skip
it, log a warning, and continue with the rest.

Ari's secondary accounts: [fill in — email addresses, or "discover from the
account switcher, skip the primary/connector-covered one"].

## Step 2 — Pull per account, read-only

For each secondary account index `i`:

- **Gmail** — use the search bar (`is:unread`, `newer_than:1d` or `2d`, not
  manual inbox scraping). For each result, extract subject, sender, snippet,
  message link. Judge actionability yourself (does it need a reply, contain
  a deadline/date/request) — don't keyword-match.
- **Drive** — check "Recent" / activity for items modified, commented on, or
  shared with this account in the last 24–48h. Extract filename, who
  touched it, what changed if visible, link. Only surface items that
  actually need Ari's input (a comment addressed to him, a share needing
  review) — a file merely modified by someone else with nothing for him to
  do is noise, not a Docket row.
- **Calendar** — pull events for [target date] on this account. Extract
  title, start/end time, location if present, link.

## Step 3 — Merge into `Daily-Docket/docket_data.json`

Read the file first; preserve every other lane and top-level field exactly.

- **Actionable email** → append to the `email` array, matching the existing
  shape exactly: `{"subject", "who", "action", "priority"}`. Tag the account
  into `who` so it's traceable without a schema change, e.g.
  `"who": "Jane Doe <jane@work.com — acct 2>"`.
- **Actionable Drive item** → append to `thisWeek` (or `dueToday` if the
  deadline is today) using the existing row shape: `text`, `area`
  (`"Personal"` unless obviously school/work), `priority`, `source`:
  `"Drive sweep (acct i)"`, and `due`/`when` if a date is visible.
- **Secondary-account calendar events** → merge into `schedule` by time
  slot. If a secondary event overlaps a `schedule` slot already populated
  from the primary account, do NOT silently pick one — add a `crosscheck`
  entry with `severity: "conflict"` describing both, and leave both rows in
  place.
- **Dedup** — before adding anything, check it isn't already present from
  the 6 AM primary-account pull or from a person emailing Ari at two
  addresses. Fuzzy-match by subject+sender or event title+time; prefer
  updating/skipping over creating a duplicate row.

## Step 4 — Stamp, rebuild, publish

1. Write `Daily-Docket/google_accounts_state.json`:
   ```json
   {"lastSweep": "2026-09-02", "accounts": ["jane@work.com (acct 1)", "..."], "note": "optional one-liner"}
   ```
   Only after a sweep that actually read at least one account — never on a
   run that hit only login walls.
2. Rebuild: `py -3.12 build_docket.py` from `Daily-Docket/`. A non-zero exit
   (`DOCKET BUILD FAILED:`) means fix what it names before republishing.
3. Republish to the same Docket artifact Ari already uses (see
   `speedrun`/`docket-artifact` in memory for the URL and `file_path`),
   preserving `capabilities`.

## Step 5 — Report

Per secondary account: what was skipped (login wall, empty), what got added
to the Docket, any conflict flagged. Be plain about accounts that couldn't
be reached — don't imply a sweep happened if it hit a login wall.

## Guardrails

- **Read-only, hard constraint.** Never click send, delete, archive, share,
  trash, or respond to a calendar invite. Interact only via navigation and
  read-only extraction (`read_page`/`get_page_text`). If getting the data
  seems to require any write action, stop and ask Ari first.
- **No credentials, ever.** If a login/verification screen appears for an
  account, skip it — don't attempt to authenticate.
- **No fabrication.** If a page didn't load, report the gap rather than
  guessing.
- **Verify the `authuser` index against the visible account** before
  trusting any data pulled at that index — a stale mapping silently attributes
  one person's email to another account.
- **Dedupe before writing**, and never duplicate what the 6 AM connector run
  already covers for the primary account.
