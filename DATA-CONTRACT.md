# FocusFlow v2 — Data Contract

Findings from reading the three existing apps, before writing any FocusFlow v2 code. No source files were modified.

## 1. FocusFlow v1 — `C:\Users\aware\Claude\Artifacts\focusflow\index.html`

All persistence goes through a tiny `store` helper (`store.get/set`, JSON in/out of `localStorage`, try/catch, default fallback). Keys:

| Key | Shape | Notes |
|---|---|---|
| `ff.settings` | `{focus:25, short:10, long:30, interval:4, autoBreak:bool, autoFocus:bool, notify:bool, volume:0.5, repeatAlarm:bool, ver:2}` | `ver` drives a one-time migration (pre-v2 saves get `short`/`long` reset to 10/30 and `ver` bumped to 2). v2 needs its own bump. |
| `ff.tasks` | `[{id:"<timestamp+rand string>", text:"...", done:bool}]` | `id` generated as `Date.now()+''+Math.floor(Math.random()*999)` — string, not numeric. |
| `ff.stats` | `{days:{"YYYY-MM-DD":{focus:<seconds>, sessions:<count>}}, totalSeconds, totalSessions}` | Matches what the build prompt already stated. |
| `ff.name` | plain string, default `''` (falls back to `'Aryan'` at render time) | Used for the daily-message greeting. |
| `ff.activeTask` | task `id` string or `null` | Which task is shown inside the ring. |

**Reset button** (`#resetData`) removes `ff.tasks`, `ff.stats`, `ff.settings`, `ff.activeTask` — but *not* `ff.name`. Worth preserving that asymmetry or deciding deliberately not to.

**Cowork-only calls** (both feature-detect `window.cowork && window.cowork.callMcpTool`, and render an inert "open this in Cowork" message otherwise — exactly the pattern the build prompt already specifies):
- `mcp__f8f8675f-d173-480c-a4aa-70563862fbc4__list_events` — today's calendar, for the side panel.
- `mcp__255a1d9a-f031-401d-85f2-4bed88fff239__get_currently_playing` — Spotify now-playing widget.

**Weather is fake in v1** — `WEATHER` is a hardcoded object (`Union City, CA`, dated `2026-06-17`) with no `fetch()` anywhere in the file. There is no existing weather contract to migrate; v2's "free no-key API, hide panel on failure" requirement is new work, not a port.

## 2. Daily Docket — `C:\Users\aware\Claude\Artifacts\docket\index.html`

**No `localStorage` use at all.** The Docket is a pure live-render: on load it fires four MCP calls directly —
`mcp__f8f8675f-d173-480c-a4aa-70563862fbc4__list_events` (Calendar), `mcp__479a401b-6abf-414c-a640-637153ee1d92__find-tasks-by-date` (Todoist), `mcp__8062f5ab-72a8-402f-ba79-d25da259fb37__search_threads` (Gmail), `mcp__bcfd450e-dc9b-4089-8ceb-a25de1da3841__notion-search` (Notion) — and renders straight into the DOM. Nothing persists between loads, so there is no key for GardenBridge to read.

The richer, actively-maintained Docket described in memory ([[docket-artifact]]) is a **different, newer artifact** (`Daily-Docket/build_docket.py` → `docket.html`, served via `python -m http.server` on port 4321, or the live claude.ai capability-enabled artifact). It writes one relevant thing to `localStorage`: `docketChecks_v1` (per-row checked state, keyed to the board's day) — but that board's task rows are keyed by Notion `data-nid` (page id), not by a stable task-id contract, and the write-back to Notion happens through `window.claude.mcp.callTool`, which only exists inside that specific artifact's runtime.

**Bottom line: there is no Docket-side localStorage contract a plain double-clicked file can read.** See §4 for what this means for integration design.

## 3. Grimoire Calendar — `C:\Users\aware\OneDrive\Desktop\wrproj\grimoire-calendar\`

(Not in `Claude\Artifacts`; found under the wrproj home directory — this is "Grimore.")

`localStorage` keys (all under the `grimoire-calendar` app):

| Key | Shape | Notes |
|---|---|---|
| `grimoire.feed.v1:<calendarId>` | `{text:"<raw .ics text>", via:"...", fetchedAt:"<ISO>"}` | Raw ICS per calendar feed, **not parsed events** — reading "next event" requires ICS parsing (the app vendors `vendor/ical.js` for this). |
| `grimoire.local.v1` | `{"YYYY-MM-DD": {note, mood, updated}}` | Private diary layer; deliberately not events or tasks. |
| `grimoire.view.v1` | string | Last view (month/etc). |
| `grimoire.foil` | string | Cosmetic theme toggle. |

**Critical blocker: origin isolation.** Grimoire is explicitly *not* opened via `file://` — its README states this directly: Google's iCal endpoint sends no `Access-Control-Allow-Origin` header, so `Grimoire-Calendar.bat` starts a local Python server (`tools/serve.py`) and the app runs at `http://localhost:<port>`. `localStorage` is scoped per origin. A FocusFlow v2 file opened by double-click runs at a `file://` origin — a browser will never let it read `http://localhost:<port>`'s storage, regardless of what keys exist. **This isn't a "data not present" case GardenBridge can detect and skip gracefully — it's a hard browser security boundary.** Even knowing the exact keys above, FocusFlow cannot reach them.

## 4. NightOwl — `C:\Users\aware\OneDrive\Desktop\wrproj\nightowl\`

(Also not in `Claude\Artifacts`; the desk/circadian system, confirmed via memory + source.)

**No browser `localStorage` anywhere in NightOwl.** It's a PowerShell/Python backend: `config.json` (static settings incl. `bedtime`, `windDownMinutes`), `data/state.json` (`{mode, modeSince, sessions, kelvinOffset, ...}`), `data/focus_sessions.json` (append-only log), all written by `core/NightOwl.psm1` / `bin/no.ps1`. The Hub (`hub/index.html`) is a **static file generated by `python/build_hub.py`** with data baked in at generation time — it does not fetch anything live, so even the Hub itself can't tell you NightOwl's *current* mode without being regenerated.

**What does exist and is genuinely usable: the `nightowl://` protocol, one-way, write-only.** It's registered as a real Windows URL-protocol handler (`nightowl:// → bin\nourl.exe → bin\nohandler.ps1 → bin\no.ps1`). Confirmed live in `nightowl.log` (real invocations logged, e.g. `uri: nightowl://mode/work`). Relevant verb, already shipped and used by another integration (Solo Leveling System EXP credit):

```
nightowl://focus/complete/<minutes>
```
- `no.ps1`'s `"focus"` case requires exactly `Value="complete"`, `Extra=<positive integer minutes>`.
- Appends an entry to `nightowl/data/focus_sessions.json`, which the Solo Leveling System's `system_bridge.py` picks up.
- Triggered from a browser via `location.href = "nightowl://focus/complete/25"` (or a plain `<a href>` click — that's how `hub/index.html`'s own `go()` helper does it, line 437-438). First-ever click makes Brave show an "open NightOwl?" prompt once; "always allow" clears it permanently.

There is **no equivalent read verb** — nothing returns state back to the caller (it's fire-and-forget, like all the other `nightowl://` actions).

## 5. What this means for GardenBridge — needs your call before I build it

The build prompt assumes all three companion apps expose readable `localStorage` FocusFlow can pull from. In practice:

- **Docket:** no persisted data to read, in either version. The only way to show "today's Docket items" live would be for FocusFlow to make the *same* MCP calls Docket makes (Todoist `find-tasks-by-date`, Calendar `list_events`) itself, gated behind `hasCowork` — i.e. not reading Docket at all, but re-deriving the same view. Writing minutes back to a Todoist task is possible the same way (`update-tasks`/`complete-tasks` MCP tools), but again only when `hasCowork` is true — never from a plain double-clicked file.
- **Grimoire:** real keys exist, but they live behind a `localhost:<port>` origin FocusFlow can never reach from `file://`. There's no partial win here — it's fully unreachable, not "sometimes empty."
- **NightOwl:** no readable live state, but a real, already-proven write channel (`nightowl://focus/complete/<min>`) for logging completed focus sessions. For the "shift to night-mode palette after wind-down" feature, the only honest option is to bake in NightOwl's *documented default* (`bedtime: "20:00"`, `windDownMinutes: 60`, i.e. dim from ~19:00) as FocusFlow's own configurable setting — clearly labeled as a mirrored default, not a live sync, since it can silently drift from whatever Ari changes in `nightowl/config.json` later.

Given that, here's how I'd propose scoping "GardenBridge" — want me to proceed on this basis, or handle it differently?

1. **Drop the localStorage-read approach entirely** for Docket and Grimoire (it cannot work, not just "usually empty").
2. **Docket "From your Docket" section:** only appears when `hasCowork` is true, calling the Todoist/Calendar MCP tools directly (same tools Docket itself uses). Fails silently (section just doesn't render) when `hasCowork` is false — which covers the offline double-click case entirely, correctly.
3. **Grimoire "next event + countdown":** cut, since it's provably unreachable from `file://`. (Alternative if you want it later: Grimoire's own `serve.py` could add a small read-only JSON endpoint FocusFlow could `fetch()` if *also* served from `http://localhost:<same-port>` — but that breaks "double-click to open," so it's out of scope here unless you say otherwise.)
4. **NightOwl:** one-way write only. On focus-session completion, best-effort `location.href = "nightowl://focus/complete/<min>"` (silently no-ops if the protocol isn't registered on this machine — can't detect that in advance, only that the navigation didn't error, which `location.href` never reports either way). Night-mode palette driven by a FocusFlow setting seeded from NightOwl's current documented defaults, editable independently.
5. Settings panel still lists all three with a status line — but "Connected" for Docket means *"Cowork MCP available,"* not *"Docket detected,"* and Grimoire's toggle is honestly labeled "not reachable from a local file" rather than a live Connected/Not-found check, since no live check is possible.

Confirm this direction (or tell me to change it) and I'll move on to step 2 (core timer + settings + v1 migration).
