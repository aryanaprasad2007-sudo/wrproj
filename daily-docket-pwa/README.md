# 🗓️ Daily Docket

A small, installable PWA that shows **today** and **tomorrow**, read live from
your Google Calendar iCal feeds. No backend, no build step, no accounts, no
database. Plain HTML/CSS/JS modules, parsed in the browser with
[ical.js](https://github.com/kewisch/ical.js).

- **Today** — a gold spotlight card with a live countdown to your most important
  hard deadline, then "still ahead" and a folded-up "already done".
- **Tomorrow** — a chronological timeline plus one violet focus card for the
  biggest thing on the day. Countdown only if it's a genuine deadline.
- **All five of your calendars at once**, merged and de-duplicated, each event
  tagged with which feed it came from.
- Events titled `WR · …` are ignored, and so is anything marked free/transparent.
- All-day items (birthdays, milestones) become chips at the top.
- Every event gets one of **The Docket's lanes** — School · Pre-Med · Trading ·
  Health · Personal · Admin · Interest — in the same colours
  `Daily-Docket/build_docket.py` uses, so both boards agree.
- Works offline on the last sync. Install it to your phone or desktop home screen.

---

## File structure

```
daily-docket-pwa/
├── index.html                  app shell
├── config.js                   ← the only file you need to edit
├── config.example.js           template for config.local.js (git-ignored)
├── manifest.webmanifest        PWA manifest
├── sw.js                       service worker (offline + install)
│
├── css/styles.css              the whole look
├── fonts/                      Quicksand + Nunito, self-hosted for offline
│
├── js/
│   ├── app.js                  boot, state, view toggle, refresh timers
│   ├── settings.js             merges config.js + config.local.js + ⚙ panel
│   ├── calendar.js             fetch every feed, parse, expand recurrences
│   ├── areas.js                The Docket's lane vocabulary + colours
│   ├── filters.js              "WR ·" prefix, free/busy, day bucketing
│   ├── importance.js           scores events, picks the spotlight and focus
│   ├── countdown.js            one timer driving every live clock
│   ├── render.js               event objects → DOM
│   ├── store.js                localStorage cache, one entry per calendar
│   └── util.js                 dates, formatting, escaping, the nice words
│
├── vendor/ical.js              ical.js 2.2.1, vendored (no CDN, works offline)
├── icons/                      generated PNGs + SVG favicon
│
├── tools/
│   ├── serve.py                dev server + /ics proxy (stdlib only)
│   └── make_icons.ps1          regenerates the icon set
│
├── netlify.toml + netlify/functions/ics.mjs     Netlify deploy
├── vercel.json  + api/ics.js                    Vercel deploy
└── .nojekyll                                    GitHub Pages deploy
```

---

## Run it locally

You need Python 3.8+. On this machine that's `py -3` (the bare `python`
command is the Microsoft Store stub and won't work).

```bash
py -3 tools/serve.py --open
```

Then open <http://localhost:8080>. **Don't** double-click `index.html` — ES
modules and service workers both need a real `http://` origin.

With no calendar URLs filled in, `/ics` serves a **generated demo feed** built
around the current time, so you can see the whole app working immediately.

```bash
py -3 tools/serve.py --port 5173          # different port
py -3 tools/serve.py --demo               # force demo data
py -3 tools/serve.py --host 0.0.0.0       # reach it from your phone on the same wifi
py -3 tools/serve.py --ics "https://..."  # one-off single calendar
py -3 tools/serve.py --ics-file cal.ics   # serve a local .ics export
```

---

## Your calendars

Your schedule is spread across five Google calendars, and **one secret iCal URL
only covers one calendar** — there's no "whole account" feed. `config.js` is
pre-filled with all five; three still need a URL from you:

| # | Calendar | Status |
|---|---|---|
| 0 | **School** (your primary) | ⬅ needs your secret iCal URL |
| 1 | **Daily Routine** | ⬅ needs your secret iCal URL |
| 2 | **Canvas** — assignments and exams | ⬅ needs a feed URL |
| 3 | Holidays in United States | ✅ public URL already filled in, `enabled: false` |
| 4 | Moreau (Web School Calendar) | ✅ public URL already filled in, `enabled: false` |

Holidays and Moreau are off by default — 317 and 4008 events respectively, and
you've graduated from the second one. Flip `enabled: true` if you want either.

**Getting the three URLs.** Google Calendar → ⚙ Settings → click the calendar in
the left sidebar → "Integrate calendar" → **Secret address in iCal format**.
Repeat per calendar.

For Canvas, prefer **Canvas → Calendar → "Calendar Feed"** over Google's
re-export — it's the original source, so it updates sooner.

Keep the order in `config.js` stable: the proxy addresses feeds positionally as
`/ics?cal=0`, `/ics?cal=1`, and so on. A calendar with no URL yet returns an
empty-but-valid feed, so the others keep working.

---

## Where do I put the URLs?

> ⚠️ **One important catch.** Google serves `.ics` files **without an
> `Access-Control-Allow-Origin` header**, so a browser will refuse to read them
> directly from another origin. This isn't something the app can work around in
> JavaScript — the request is blocked before your code sees it. Every option
> below therefore routes the feeds through a **same-origin `/ics` path**. The
> parsing is still 100% client-side; the only thing the server does is pass the
> bytes through.
>
> Treat a secret URL like a password: anyone holding it can read that calendar.

| Where you host it | How `/ics` works | Do the URLs end up in your repo? |
|---|---|---|
| Local dev | `tools/serve.py` reads `config.js` and proxies each feed | No — they can live in `config.local.js` |
| **Netlify** | `netlify/functions/ics.mjs` reads the `ICS_URLS` env var | **No** ✅ |
| **Vercel** | `api/ics.js` reads the `ICS_URLS` env var | **No** ✅ |
| GitHub Pages | no server at all — needs a public CORS relay | **Yes**, unless the repo is private |

**Recommended:** deploy to Netlify or Vercel, set `ICS_URLS`, and leave every
`url` blank in `config.js`. The app falls through `/ics?cal=N` → the `url` in
config → cached copy automatically, so nothing else changes.

Two other ways to supply them if you'd rather not use env vars:

- **`config.local.js`** — copy `config.example.js` to it and put the URLs there.
  It's git-ignored, and `tools/serve.py` reads it too.
- **The ⚙ Settings panel** — one field per calendar, with a dot showing each
  feed's last sync. Stored in that device's `localStorage` only, keyed by
  calendar id. Note this alone doesn't solve CORS: it works if you're on a host
  with the `/ics` proxy, or if you also tick "use a public CORS relay" (which
  means a third party sees your calendars — off by default, and I'd leave it off).

---

## Deploy it free

### Netlify (recommended)

```bash
git init && git add -A && git commit -m "Daily Docket"
```

1. Push to GitHub, then **Add new site → Import an existing project** on
   [netlify.com](https://netlify.com) and pick the repo.
2. Build command: *(leave empty)* · Publish directory: `.` — `netlify.toml`
   already sets this.
3. **Site configuration → Environment variables → Add `ICS_URLS`**, one line per
   calendar **in the same order as `config.js`**. The `Label|` prefix is optional
   and only shows up in error messages:

   ```
   School|https://calendar.google.com/calendar/ical/.../basic.ics
   Daily Routine|https://calendar.google.com/calendar/ical/.../basic.ics
   Canvas|https://canvas.ucsc.edu/feeds/calendars/user_....ics
   ```

4. Deploy. Check `https://your-site.netlify.app/ics?cal=0` returns text starting
   with `BEGIN:VCALENDAR`.

### Vercel

Same idea: import the repo on [vercel.com](https://vercel.com), framework preset
**Other**, then **Settings → Environment Variables → `ICS_URLS`**. `vercel.json`
rewrites `/ics` to `api/ics.js`.

### GitHub Pages

Push the folder to a repo, then **Settings → Pages → Deploy from a branch →
`main` / root**. `.nojekyll` is already there so the `js/` and `fonts/` folders
get served.

Pages can't proxy anything, so you must either:

- put the URLs directly in `config.js` **and make the repo private**, or
- open ⚙ Settings in the app and tick **"Use a public CORS relay"**, accepting
  that the relay operator can read your calendars.

If it's a project page (`you.github.io/daily-docket-pwa/`) everything still
works — all paths in the manifest and service worker are relative.

---

## Add it to your home screen

- **Brave / Chrome / Edge (desktop or Android)** — an install button (⬇︎)
  appears in the top bar once the browser decides it's installable; or use the
  browser menu → *Install app*.
- **iPhone / iPad** — Safari only. Share → **Add to Home Screen**. (iOS ignores
  `beforeinstallprompt`, so no in-app button will show up there.)
- **Desktop** — the installed window is standalone, no address bar.

Requires HTTPS in production (Netlify/Vercel/Pages all give you that free) or
`localhost` in dev.

---

## Tweaking it

Everything below lives in `config.js`.

| Setting | What it does |
|---|---|
| `calendars` | The feed list. Each entry takes `id`, `label`, `url`, `enabled`, and an optional `area` that tags every event from that feed. |
| `ignoreTitlePrefixes` | Titles starting with these never show. Default `['WR ·']`. |
| `lenientPrefixMatch` | Also catches `WR -`, `WR:`, `WR •`… so a typo'd separator can't leak an overlay through. Set `false` for exact matching. |
| `skipTransparent` | Hide events marked free. All-day items are exempt (Google marks birthdays free — you'd lose every chip). |
| `extraDeadlineKeywords` | `{ 'pset': 80 }` — merged into the built-in scoring. |
| `pinMarker` | Put `★` in an event title to force it into the spotlight. |
| `deadlineScoreThreshold` | How deadline-ish something must be to earn a countdown. Default `60`. |
| `showAreaChips` / `showCalendarLabels` | Turn the lane tags and the `🗂 Calendar` labels off if they feel noisy. |
| `refreshMinutes`, `hour12`, `timeZone`, `locale` | Behaviour and formatting. `timeZone: null` uses the device's zone. |

**Which event wins the spotlight?** `js/importance.js` scores each event on
deadline words (*due, exam, submit, deadline, interview, flight, pay…*), then
adds urgency the closer it gets. Your own conventions are wired in as first-class
signals: a leading **🚨** scores 94, **"(mandatory)"** 86, and **"(blocks X)"**
90 — so `🚨 Finish UCSC Orientation Course (blocks Fall enrollment)` outranks an
ordinary appointment without you doing anything. Highest score that clears the
threshold wins. If nothing qualifies, Today still spotlights the next thing up —
just worded "Next up" and without the gold treatment.

**Which lane does an event land in?** `js/areas.js`, using the same seven areas
and hex colours as the routine. The event's **title** votes first; the
description is only consulted if the title says nothing. (Descriptions name
other things constantly — "Session 1 ENDS" mentions next week's CHEM 3A in its
notes, which filed a School event under Pre-Med until the title got priority.)
A calendar-level `area` in `config.js` overrides both.

To see what got filtered out, open the console and run `docket.dropped`; for
per-feed sync state, `docket.feeds`.

**Colours and fonts** are CSS variables at the top of `css/styles.css`
(`--plum-800`, `--lav-300`, `--violet-500`, `--gold-300`). Lane colours live in
`js/areas.js`.

**Icons:** edit and re-run `powershell -ExecutionPolicy Bypass -File tools/make_icons.ps1`.

### After you change a file

An installed copy holds the old files in its service worker cache. Bump
`CACHE_VERSION` at the top of `sw.js` (`'v2'` → `'v3'`) and redeploy — the new
worker wipes the old cache on activate. On `localhost` this doesn't apply: the
service worker uses network-first there so your edits always show up.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| "Couldn't load the calendar", every attempt says *Failed to fetch* | That's CORS. You're loading URLs directly with no `/ics` proxy — see the table above. |
| One calendar is stale, the rest are fine | The sync line names it. Check that feed's URL; the others keep working regardless. |
| `/ics` returns *Neither ICS_URLS nor ICS_URL is set* | Add the env var on Netlify/Vercel and redeploy (env changes need a new deploy). |
| Events show under the wrong calendar name | `ICS_URLS` order must match the `calendars` order in `config.js`. |
| Setup screen even though `config.js` has URLs | You opened `index.html` from the filesystem. Serve over `http://`. |
| Nothing shows for today but the calendar has events | They may all be filtered. Run `docket.dropped` in the console. |
| An event is in the wrong lane | Add a keyword to `js/areas.js`, or set `area` on that calendar in `config.js`. |
| Wrong times | Set `timeZone` in `config.js` (e.g. `'America/Los_Angeles'`), or leave `null` to follow the device. |
| Edits don't appear on your phone | Bump `CACHE_VERSION` in `sw.js`. |
| Repeating events missing | Only occurrences overlapping today/tomorrow are expanded, capped by `maxOccurrenceIterations`. |

---

Fonts: Quicksand and Nunito, [SIL Open Font License 1.1](https://scripts.sil.org/OFL).
Calendar parsing: [ical.js](https://github.com/kewisch/ical.js), MPL 2.0.
