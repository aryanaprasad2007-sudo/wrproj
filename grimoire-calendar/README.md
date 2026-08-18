# Grimoire Calendar

A starry month calendar that opens as its own program. Google Calendar supplies
the events; you supply the margins.

Plum vellum, hairline foil, a real moon phase on every day, and a private note
and mood you can attach to any date that Google never sees.

---

## Run it

Double-click **`Grimoire-Calendar.bat`**.

That starts a small local Python server and opens the app in its own window — no
tabs, no address bar. Close the black console window to stop it.

From a terminal, if you prefer:

```bash
py -3 tools/serve.py
```

### Install it properly (recommended)

Once it's running, in Brave: **⋮ → Cast, save and share → Install page as app**.

You get a Start-menu entry, a taskbar icon, and an app window that survives
reboots. You still need the server running for it to load, so keep using the
`.bat` to launch — the installed shortcut is for pinning and the icon.

---

## Connect your calendars

**Primary is already connected** — `config.local.js` exists and holds it.
Canvas is still blank; paste its feed URL into the same file when you want it
(canvas.ucsc.edu → Calendar → *Calendar Feed*). A blank slot returns an empty
calendar rather than failing the sync, so there's no rush.

Starting from scratch elsewhere:

1. Copy `config.example.js` to **`config.local.js`**.
2. Paste your secret iCal URLs into it (the file explains where to find each).
3. Reload the page.

**Treat those URLs like passwords.** A Google "secret address in iCal format" is
a bearer token — anyone holding it can read that calendar forever without
logging in. `config.local.js` is git-ignored for exactly this reason. If one
leaks, hit *Reset private URLs* on the same Google settings page.

> Why a local server at all? Google's iCal endpoint sends no
> `Access-Control-Allow-Origin` header, so a browser flatly refuses to let a web
> page read it. `tools/serve.py` passes the feed through on the same origin at
> `/ics?cal=<n>`. That's the whole trick, and it's why opening `index.html`
> directly won't work.

---

## Using it

| Key | Does |
| --- | --- |
| `←` `→` `↑` `↓` | Move the selected day (follows across months) |
| `T` | Jump to today |
| `R` | Re-sync the feeds |

- Click any day to load it into the right-hand rail.
- **Your margin** is the private layer: a note and a mood, stored only on this
  machine, in `localStorage`.
- **Foil** toggles the metallic between antique gold and rose-violet.
- **Export notes** dumps your margins to JSON. Your events live in Google and
  your tasks live in Notion — these notes are the one thing here that exists
  nowhere else, so back them up occasionally.

Deliberately **not** a task list. Tasks belong in the Notion Command Center; a
second competing list is the thing to avoid.

---

## Make it yours

### The day mark — `js/local.js`

`dayMark()` is set to **mood mirror**: each day you've logged shows its mood
glyph in that mood's colour, and days you haven't logged show nothing.

The blanks are load-bearing. Moods only form a readable shape across a month if
they aren't competing with a mark on every single day — that's also why this
doesn't repeat what the dots already say. The dots are what the day *demanded*
of you; the mark is what it was actually *like*.

| Mood | Mark | |
| --- | --- | --- |
| Great day | `✦` | gold |
| Good day | `✧` | rose |
| Flat | `·` | lavender |
| Hard day | `☁` | blue |
| Worth remembering | `❋` | violet |

A note saved without a mood gets a faint neutral pip — otherwise you'd write
something on a Tuesday, skip the mood, and find no trace the day held anything.

The mood buttons in the rail are tinted to match, so the picker doubles as the
key. To change any of it, edit `dayMark()`; returning a plain string still
works, so a one-line `return '★'` is a valid rewrite.

### Month grid: dots or chips

`config.js` → `monthDetail`.

- **`'dots'`** (default) — one pip per event, coloured by area, with a key in the
  status bar. A month reads as a heat map: how full each day is, and what kind
  of full.
- **`'chips'`** — truncated event titles.

Dots are the default because of your actual data. With ~175 events in a month
and seven columns, a title chip is about 90px wide — `🌙 Wind Down / Creative`
renders as `9:45 pm …` and every cell becomes an identical grey wall. Chips are
only legible on a sparse calendar. Detail lives in the rail, one click away.

Colours come from `js/areas.js`, the same vocabulary The Docket uses, so an
event is the same colour on both boards.

### A wallpaper

Drop an image anywhere in the folder and point `config.local.js` at it:

```js
wallpaper: './icons/sakura-night.jpg',
wallpaperOpacity: 0.30,
```

Keep the opacity low. Around `0.30` is the ceiling before event titles start
losing their fight with the image — the calendar has to stay readable at a
glance or the whole thing is just a nice wallpaper you can't use.

### The palette

Everything is CSS custom properties at the top of `css/grimoire.css`. The
metallic is a single variable, `--foil`, with the rose variant defined in one
small block under `body[data-foil='rose']`.

### The icons

`py -3.12 tools/make_icons.py` regenerates them. Note **3.12**, not `py -3` —
Pillow and numpy are installed on 3.12 on this machine, not on the 3.14 default.

---

## Layout

```
index.html            shell
config.js             defaults (safe to commit)
config.local.js       your secret feed URLs (git-ignored, you create it)
css/grimoire.css      the entire theme
js/
  app.js              state and wiring
  render.js           month grid + agenda rail
  local.js            the private note/mood layer  ← dayMark() lives here
  moon.js             moon phase maths
  calendar.js         iCal fetch + recurrence expansion ┐ shared with
  store.js            cached feeds                      │ daily-docket-pwa,
  util.js             date/time formatting              │ copied not linked
  areas.js            event categorisation              ┘
vendor/ical.js        ical.js, vendored (no npm on this machine)
tools/serve.py        local server + iCal passthrough
tools/make_icons.py   icon generator
sw.js                 offline cache — only registers off-localhost, see below
```

### Two notes for future-you

**The service worker is off on localhost, on purpose.** Everything is already on
your disk, so there's nothing to be offline from — all a cache-first worker can
do here is serve you the *previous* version of `dayMark()` after you edit it.
It only registers if this ever gets deployed to a real URL, where offline
actually means something.

**The shared modules are copies, not imports.** `calendar.js`, `store.js`,
`util.js` and `areas.js` came from `daily-docket-pwa`. Fixing a parsing bug in
one does not fix it in the other. That's a deliberate trade — no build step and
no shared package on a machine with no npm — but it's worth knowing before you
go hunting for why a fix didn't take.
