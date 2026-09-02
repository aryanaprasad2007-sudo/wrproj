# Daily Docket (iOS)

A native SwiftUI rewrite of [`daily-docket-pwa`](../daily-docket-pwa) — same
Today/Tomorrow spotlight-and-focus logic, same calendar filtering and area
lanes, but a real iPhone app instead of a Home Screen web app. Built as
**source only** — there's no Mac/Xcode in the environment this was written
in, so none of this has been compiled or run. Treat it as a strong first
draft to open in Xcode and fix forward from, not a finished, tested app.

## What it does

- **Today** — gold spotlight card with a live countdown to the most
  important hard deadline, "still ahead", and a foldable "already done".
- **Tomorrow** — a timeline plus a violet focus card for the biggest thing
  on the day.
- Multiple calendars merged and de-duplicated, filtered the same way as the
  web app (`WR ·` prefix, transparent/cancelled events, custom deadline
  keywords, the 🚨/(mandatory)/(blocks X) conventions).
- **Local notifications** ahead of today's spotlight deadline, and an
  optional daily "your docket is ready" digest — see [Notifications](#notifications-not-web-push)
  below for why this isn't the same mechanism as the PWA's Web Push.
- Secret calendar URLs live in the iOS **Keychain**, never in a settings
  file — same "a secret URL is a password" rule as the web app's README.

## What's genuinely different from the web app

| | Web app (`daily-docket-pwa`) | This app |
|---|---|---|
| Calendar fetch | Same-origin `/ics` proxy (Google blocks direct CORS reads from a browser) | Fetches ICS URLs **directly** — native networking isn't subject to CORS, so no proxy/Netlify function needed |
| ICS parsing | `vendor/ical.js`, full-featured | A hand-rolled parser in `Services/ICSParser.swift` + `EventExpander.swift` — covers DAILY/WEEKLY/MONTHLY/YEARLY RRULEs with INTERVAL/COUNT/UNTIL/BYDAY, EXDATE, RECURRENCE-ID overrides. Doesn't handle BYMONTHDAY/BYSETPOS or non-Olson TZIDs. Good enough for Google Calendar/Canvas exports, not a general-purpose ICS client |
| Notifications | Web Push (VAPID + a Netlify function + a browser subscription) | **Local notifications**, scheduled on-device from the same spotlight-scoring logic the UI uses |
| Settings storage | `localStorage` + `config.js`/`config.local.js` | `UserDefaults` (non-secret settings) + **Keychain** (calendar URLs) |

## Notifications: not Web Push

The web app's push (in `daily-docket-pwa/netlify/functions/push-*.mjs`) uses
Web Push: a browser subscription plus a server holding a VAPID key that signs
each push. A native iOS app's equivalent would be **APNs** — which needs a
paid Apple Developer Program membership, a `.p8` auth key, and a server that
calls Apple's push API. None of that can be set up or tested from here, so
this app takes a simpler, fully-local path instead:

`Services/NotificationScheduler.swift` runs the *same* `Importance.pickSpotlight()`
scoring the UI uses, and schedules `UNUserNotificationCenter` local
notifications directly on-device — no server, no APNs certs, works the
moment you grant notification permission. `Services/BackgroundRefresh.swift`
uses `BGTaskScheduler` to periodically re-fetch and re-schedule so the
reminder stays accurate even if you haven't opened the app in a while (iOS
controls the actual cadence — treat "every `refreshMinutes`" as a request,
not a guarantee).

If you later want real push-while-force-quit (local notifications still fire
even if the app was force-quit, for what it's worth, since iOS owns the
schedule — the gap is *accuracy* after a long idle stretch, not delivery),
wiring up APNs is the next step, using the same VAPID-adjacent pattern as
the web app's Netlify functions but swapped for `p8`/APNs HTTP/2.

## Building it

You need a Mac with Xcode. This repo ships **source, not an `.xcodeproj`** —
generating Xcode's project file by hand is exactly the kind of thing that
silently corrupts without a compiler to check it, so instead this uses
[XcodeGen](https://github.com/yonaskolb/XcodeGen) to build the project file
from `project.yml`:

```bash
brew install xcodegen
cd daily-docket-ios
xcodegen generate
open DailyDocket.xcodeproj
```

Then in Xcode:

1. Select the `DailyDocket` target → **Signing & Capabilities** → pick your
   own Team (a free Apple ID works for running on your own device; it just
   can't do real push/App Store distribution).
2. Change `PRODUCT_BUNDLE_IDENTIFIER` in `project.yml` (or in Xcode) if
   `com.aryanprasad.dailydocket` collides with anything, then re-run
   `xcodegen generate`.
3. Add a real app icon — `Assets.xcassets/AppIcon.appiconset` only has a
   placeholder `Contents.json`; drop a 1024×1024 PNG onto the AppIcon slot in
   Xcode's asset editor before building for a real device.
4. Build & run on your iPhone (Simulator works for everything except actual
   push notification delivery — test notifications on a real device).
5. On first launch, open ⚙ **Settings**, paste your three secret calendar
   URLs (same ones from the web app's README → "Your calendars"), then tap
   **Enable notifications**.

## What almost certainly needs a fix pass in Xcode

This was written without a compiler, so budget time for the usual first
build: import fixes, an API signature that drifted between SDK versions,
maybe a regex escaping edge case in `Filters.swift`/`Importance.swift`
(ported from JS regex — ICU and JS regex are close but not identical).
Likely trouble spots, ranked by how much I'd bet on them:

1. **Time zone edge cases** around DST transitions in `ICSParser`'s
   DATE-TIME parsing — it trusts `TimeZone(identifier:)`/`Calendar` to
   resolve wall-clock times within a zone, which is the right call, but
   wasn't exercised against a real feed spanning a DST change. This is the
   one item on this list I couldn't verify by reading — it depends on
   `Calendar`'s actual runtime behavior.
2. **`EventExpander.swift`'s weekly BYDAY expansion** — the trickiest piece
   here, walking week-by-week to place recurring MWF/TTh classes. I traced
   the COUNT/n-increment logic by hand against RFC 5545 and it's correct
   (Nth occurrence included, N+1th excluded, chronological ordering within
   each week), but "correct on paper" isn't "tested against your actual
   Canvas/School feed" — do that first.
3. ~~Notification scheduling races~~ — re-checked: `NotificationScheduler`
   always removes-then-adds against fixed identifiers, so a foreground and
   background refresh overlapping is idempotent by construction, not a race.
   Not actually a concern; struck through rather than deleted so it's clear
   this was checked, not just optimistic.

None of the above were run through an actual compiler — "traced by hand" is
the ceiling of what's verifiable without Xcode. Still budget for the usual
first-build churn: import fixes, an API signature that drifted between SDK
versions, maybe a regex escaping edge case in `Filters.swift`/`Importance.swift`
(ported from JS regex — ICU and JS regex are close but not identical).

## File structure

```
daily-docket-ios/
├── project.yml                    XcodeGen spec — the source of truth for the Xcode project
├── DailyDocket/
│   ├── DailyDocketApp.swift       App entry, background task registration
│   ├── Info.plist
│   ├── Assets.xcassets/           AppIcon (placeholder) + AccentColor
│   ├── Models/
│   │   ├── Config.swift           Ported from config.js DEFAULTS
│   │   ├── CalendarSource.swift
│   │   ├── EventItem.swift
│   │   └── Areas.swift            Ported from js/areas.js (lane colours + rules)
│   ├── Services/
│   │   ├── ICSParser.swift        Hand-rolled ICS parser
│   │   ├── EventExpander.swift    RRULE occurrence expansion
│   │   ├── CalendarService.swift  Fetch + on-disk cache per calendar
│   │   ├── Filters.swift          Ported from js/filters.js
│   │   ├── Importance.swift       Ported from js/importance.js (spotlight/focus scoring)
│   │   ├── DocketStore.swift      Refresh orchestration + published state
│   │   ├── SettingsStore.swift    UserDefaults + Keychain-backed settings
│   │   ├── KeychainStore.swift    Secret calendar URL storage
│   │   ├── NotificationScheduler.swift   Local notifications (the "push" story)
│   │   └── BackgroundRefresh.swift       BGTaskScheduler wiring
│   ├── Utilities/
│   │   ├── DateUtils.swift        Time-zone aware formatting/countdown
│   │   └── Copy.swift             Greeting + motivation lines, ported from js/util.js
│   └── Views/
│       ├── ContentView.swift      TabView (Today/Tomorrow) + settings sheet
│       ├── TodayView.swift
│       ├── TomorrowView.swift
│       ├── EventRowView.swift
│       ├── SettingsView.swift
│       └── CountdownText.swift
```
