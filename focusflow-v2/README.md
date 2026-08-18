# FocusFlow v2 — Enchanted Garden

A single self-contained `index.html`. No build step, no npm, no external
frameworks or fonts. Double-click to open; works fully offline. Gains a
Docket task pull, calendar-overrun warnings, and a Spotify now-playing
widget only when opened as a Cowork artifact (`window.cowork.callMcpTool`
present) — everything else works identically either way.

See [`DATA-CONTRACT.md`](../DATA-CONTRACT.md)
(in `wrproj/`) for why the Docket/Grimoire/NightOwl integrations are shaped
the way they are — short version: `localStorage` is scoped per browser
*origin*, and none of those three apps share an origin with a
double-clicked `file://` page, so this isn't a shared-storage reader.

## Storage — all under `localStorage`, same keys as v1

FocusFlow v2 deliberately reuses v1's exact key names. In Chromium-based
browsers (Brave included), `file://` pages share one storage bucket
regardless of folder, so v1's data carries forward automatically the first
time v2 runs — `Store.migrate()` (called once on load) only ever *adds*
fields via `Object.assign`, it never drops or overwrites what's already
there. If nothing carries forward (e.g. a browser that partitions `file://`
storage per file, such as Firefox), v2 just starts clean with defaults —
it never throws, and it never wipes existing data.

| Key | Shape | Notes |
|---|---|---|
| `ff.settings` | see below | `ver` field drives future migrations |
| `ff.tasks` | `[Task]` | see below |
| `ff.stats` | see below | |
| `ff.name` | `string` | greeting name, shown in the daily message |
| `ff.activeTask` | `string \| null` | id of the task shown inside the ring |

### `ff.settings`

```js
{
  focus: 25, short: 10, long: 30,        // minutes
  interval: 4,                            // long break after N focus sessions
  autoBreak: true, autoFocus: false,      // auto-start next mode
  notify: false,                          // desktop notifications
  volume: 0.5,                            // ambient master volume, 0..1
  repeatAlarm: true,                      // repeat chime until dismissed
  ambient: { rain:0, wind:0, crickets:0, stream:0, thunder:0, brown:0 }, // 0..1 each
  integrations: { docket:true, grimoire:false, nightowl:true },
  nightMode: { enabled:true, bedtime:"20:00", windDownMinutes:60 },
  ver: 3
}
```

`nightMode` mirrors NightOwl's `config.json` defaults at build time — it is
**not** a live sync. If you change `wake`/`bedtime` in NightOwl's own
config, update it here too; nothing keeps them in sync automatically
(nothing *can*, per the data contract above).

### `ff.tasks`

```js
[{ id:"...", text:"...", done:false, source:"user"|"docket",
   focusSeconds:0, docketId?:"..." }]
```

`source:"docket"` and `docketId` are only ever set by `GardenBridge` when
pulling from Todoist inside a Cowork session — never by hand-added tasks.
`focusSeconds` accrues every time a completed focus session had this task
active, regardless of source.

### `ff.stats`

```js
{
  days: { "YYYY-MM-DD": { focus: <seconds>, sessions: <count> } },
  totalSeconds: 0, totalSessions: 0,
  longestStreak: 0,                 // best streak ever recorded
  taskTotals: { "<taskId>": <seconds> }
}
```

A day counts toward a streak once it has ≥1 completed focus session.
Skipped sessions (the `S` shortcut) are never recorded here.

## Garden growth stages

Driven entirely by `totalSeconds` — lifetime focused time, never reset by
anything except "Reset all data."

| Stage | Threshold |
|---|---|
| 🌱 Sprout | 0h |
| 🌿 Sapling | 3h |
| 🌸 Flowering | 15h |
| 🌳 Grove | 50h |

## Integrations at a glance

- **Daily Docket** — only active when `window.cowork.callMcpTool` exists.
  Calls the same Todoist (`find-tasks-by-date`) and Calendar (`list_events`)
  MCP tools Docket itself uses, directly — it does not read Docket's
  storage (there isn't any). Checking off a Docket-sourced task calls
  `complete-tasks`; finishing a focus session on one adds a Todoist comment
  via `add-comments` logging the minutes. Both are best-effort — a failure
  is swallowed silently, never shown as an error toast.
- **Grimoire Calendar** — genuinely unreachable from a `file://` page (it
  deliberately runs on its own `http://localhost` origin, a hard browser
  security boundary, not a "sometimes missing" case). The Settings panel
  reports it honestly as "unreachable" rather than faking a Connected
  check that can never actually succeed.
- **NightOwl** — one-way, write-only. On completing a focus session,
  FocusFlow best-effort navigates a hidden iframe to
  `nightowl://focus/complete/<minutes>` — the same protocol verb NightOwl's
  own Solo Leveling System bridge already uses. If the protocol isn't
  registered on this machine, the navigation just does nothing; there's no
  way to detect that in advance, so the Settings status always reads
  "write-only" rather than a real Connected/Not-found check.

## Modules (all in one `<script>`, wrapped in an IIFE, `"use strict"`)

`Store` → `Timer` → `Tasks` → `Stats` → `Audio_` → `Scene` → `GardenBridge` → `UI`.
Each is a self-contained factory function; nothing leaks to `window`.
`Timer` is wall-clock accurate — it always derives the countdown from a
target epoch timestamp, never accumulates `setInterval` ticks, so it can't
drift and survives tab backgrounding or laptop sleep (it also recomputes
immediately on `visibilitychange` instead of waiting for the next tick).

## Keyboard shortcuts

`Space` start/pause · `R` reset · `S` skip · `T` tasks · `A` sounds ·
`,` settings · `Esc` close the open drawer.
