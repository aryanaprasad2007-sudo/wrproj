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
- A **Home Screen widget** (small + medium) showing today's spotlight with a
  live countdown — see [Widget](#widget) below.
- An **Apple Watch complication** mirroring the same spotlight — see [Apple
  Watch complication](#apple-watch-complication), including its risk flag.

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

**Time-sensitive delivery.** The one thing local notifications are
genuinely worse at than real push is that iOS treats them as easy to
silence — a Focus/DND session can quietly suppress a reminder that arrives
right when you needed it. A hard-deadline spotlight reminder now sets
`content.interruptionLevel = .timeSensitive`, which asks the system to
break through Focus/DND the same way a phone call or a Calendar alert does
(a "next up" soft suggestion stays at `.active` — it hasn't earned that).
This needs:
- The **Time Sensitive Notifications** entitlement
  (`com.apple.developer.usernotifications.time-sensitive`), already added
  to `project.yml`'s `DailyDocket` entitlements.
- `.timeSensitive` included in the `requestAuthorization(options:)` call
  (already done) — without it in the *initial* permission prompt, iOS never
  shows you the "Time Sensitive" toggle at all.
- For **App Store distribution** specifically (not needed to build and run
  on your own device), Apple requires a one-time capability request —
  search the Apple Developer site for "Time Sensitive Notifications
  entitlement request" — before this entitlement is honored in a released
  build. I'm intentionally not linking a specific URL here since I can't
  verify one from this environment and Apple has moved these request forms
  before.

**Notification actions.** Every spotlight reminder carries two buttons —
"Snooze 15 min" and "Mark done" (long-press or swipe on the notification to
see them) — handled entirely on-device, no app launch required:
- **Snooze** reschedules the same title/body 15 minutes out. It doesn't
  recompute anything; the next real refresh replaces it as usual.
- **Mark done** cancels the rest of today's reminders for that specific
  occurrence and remembers not to bring them back before the day rolls over
  — otherwise the very next background refresh would just recompute the
  same spotlight and re-schedule it. This is deliberately per-occurrence
  (keyed on `EventItem.key`, which encodes the calendar + UID + start time),
  so marking today's 9am standup done doesn't suppress tomorrow's.

`Services/NotificationScheduler.registerCategories()` defines the button set
(called once at launch, before `UNUserNotificationCenter.delegate` is even
set, in `DailyDocketApp.init()`); `Services/NotificationDelegate.swift`
receives the tap and does the actual work. The delegate is a `static let
shared` precisely because `UNUserNotificationCenter.delegate` holds its
delegate **weakly** — anything else would risk it being deallocated and
silently stopping receiving actions.

If you later want real push-while-force-quit (local notifications still fire
even if the app was force-quit, for what it's worth, since iOS owns the
schedule — the gap is *accuracy* after a long idle stretch, not delivery),
wiring up APNs is the next step, using the same VAPID-adjacent pattern as
the web app's Netlify functions but swapped for `p8`/APNs HTTP/2.

## Widget

`DailyDocketWidgetExtension` is a separate app-extension target
(`DailyDocketWidget/`) showing a small/medium Home Screen widget with
today's spotlight and a live-ticking countdown.

**It deliberately doesn't fetch or parse calendars itself.** WidgetKit
heavily throttles a widget's own refresh budget and discourages real network
work inside a `TimelineProvider` — duplicating `CalendarService`/`ICSParser`/
`Filters`/`Importance` into a second process just to fight that budget would
be a bad trade. Instead:

1. Every time `DocketStore.refresh()` runs (foreground, background task, or
   app becoming active), it computes a tiny `WidgetSnapshot` — just today's
   spotlight and tomorrow's focus, title/icon/verb/target date — and writes
   it to **App Group** storage (`WidgetBridge.swift`), then calls
   `WidgetCenter.shared.reloadAllTimelines()`.
2. The widget's `SpotlightProvider` only ever reads that snapshot. No
   Keychain access, no networking, no ICS parsing in the extension at all —
   `DailyDocketWidgetExtension`'s `sources` in `project.yml` pulls in exactly
   two shared files (`WidgetSnapshot.swift`, `WidgetBridge.swift`), nothing
   else from the app.
3. The countdown itself (`Text(date, style: .timer)`) updates continuously
   on-device via the system, the same mechanism Lock Screen timers use — no
   polling, no extra timeline entries needed for it to tick.

**This needs an App Group**, which — like the bundle identifier — has to be
registered on your Apple Developer account, not just typed into a file:

1. In Xcode, select **both** the `DailyDocket` and `DailyDocketWidgetExtension`
   targets → **Signing & Capabilities** → confirm **App Groups** is present
   (generated from `project.yml`'s `entitlements.properties`) and that
   `group.com.aryanprasad.dailydocket` is checked/registered for your team.
   If Xcode can't auto-register it (free accounts sometimes can't), create
   the group manually at developer.apple.com → Identifiers → App Groups,
   then make sure the identifier matches **exactly** in both
   `project.yml` entitlements blocks and `WidgetBridge.appGroupId`.
2. Build once, open the app so it writes a snapshot at least one time, then
   long-press the Home Screen → **+** → **Daily Docket** to add the widget.
   Before that first snapshot exists it shows a "open the app to sync"
   empty state rather than nothing.

The widget extension targets **iOS 17** (for `containerBackground(for:)`,
the current non-deprecated widget background API) even though the app
itself targets iOS 16 — a widget extension is allowed a higher minimum than
its host app; it just won't be offered on older devices.

## Apple Watch complication

⚠️ **This is the least-verified part of the whole project.** Everything
else here reuses one Xcode project and one set of conventions I'd already
exercised once (the app target, then the widget target following the same
pattern). This is a second *physical device* with its own pairing state,
its own App Group registration, and a project-structure convention (a
single-target watchOS 10 app hosting a WidgetKit complication) I have not
built or even seen built in this environment. Budget real time for this one
specifically, and don't be surprised if the watch-side project.yml targets
need more correction than everything before them combined.

**What it is:** `DailyDocketWatch` (a minimal companion app — see its
`WatchContentView.swift` doc comment for why it barely does anything on its
own) plus `DailyDocketWatchWidgetExtension` (the actual complication:
circular/rectangular/inline faces showing today's spotlight with a live
countdown, same `Text(date, style: .timer)` trick as the phone widget).

**Why it's a second data path, not a reused one:** an App Group is
per-device storage — it does NOT sync between an iPhone and its paired
Watch, only between an app and its own extensions on the *same* device. So
getting the spotlight from the phone to the watch needs an actual transport:
`Services/WatchConnectivityBridge.swift` (iOS) pushes the same
`WidgetSnapshot` via `WCSession.updateApplicationContext` — WatchConnectivity's
"only the latest state matters, no backlog" transfer, which matches a
spotlight snapshot exactly — and `DailyDocketWatch/WatchSessionDelegate.swift`
receives it on the watch side and writes it into the watch's own copy of
the App Group, which the complication reads from via the same unmodified
`WidgetBridge.swift`/`WidgetSnapshot.swift` files used everywhere else.
Delivery is best-effort (only prompt while both devices are reachable); the
complication's own 30-minute timeline reload is the fallback.

**Setup, in addition to everything in [Widget](#widget) above:**
1. The App Group needs registering for the **watchOS** app ID too, not just
   the iOS one (Apple treats them as separate app IDs even though they
   share a group identifier string).
2. `DailyDocketWatch/Info.plist` sets `WKCompanionAppBundleIdentifier` to
   `com.aryanprasad.dailydocket` — if you change the iOS bundle ID (step 2
   under Building it), update this too or the watch app won't link to its
   companion.
3. `Assets.xcassets/AppIcon.appiconset` under `DailyDocketWatch/` is a
   placeholder like the iOS one — needs a real 1024×1024 icon before it'll
   install cleanly on a device.
4. Realistically needs a paired physical Apple Watch to test end-to-end.
   The `#Preview` in `SpotlightComplication.swift` previews the complication
   in isolation against `WidgetSnapshot.placeholder`, which doesn't exercise
   WatchConnectivity at all — I'm not confident enough in Simulator's watch
   pairing support to claim it'll cover the real transport, so treat a
   physical Watch as the only real test here.

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
4. **The widget target's App Group wiring** — this is new project-config
   surface (a second target, entitlements, a shared identifier string in
   three places) rather than a code-logic risk, so it's the kind of thing
   that's more likely to show up as an Xcode signing error than a crash.
   If the widget shows the empty state forever even after opening the app,
   check the App Group identifier matches exactly in both targets'
   entitlements and in `WidgetBridge.appGroupId` first.
5. **Everything under [Apple Watch complication](#apple-watch-complication)**
   — see that section's own warning. Two more targets, a second device, and
   the least-familiar project-structure convention here.

None of the above were run through an actual compiler — "traced by hand" is
the ceiling of what's verifiable without Xcode. Still budget for the usual
first-build churn: import fixes, an API signature that drifted between SDK
versions, maybe a regex escaping edge case in `Filters.swift`/`Importance.swift`
(ported from JS regex — ICU and JS regex are close but not identical).

## File structure

```
daily-docket-ios/
├── project.yml                    XcodeGen spec — the source of truth for all five targets
├── DailyDocket/                   App target (iOS)
│   ├── DailyDocketApp.swift       App entry, background task + delegate + WCSession wiring
│   ├── Info.plist
│   ├── DailyDocket.entitlements   Generated by xcodegen from project.yml (App Groups, time-sensitive)
│   ├── Assets.xcassets/           AppIcon (placeholder) + AccentColor
│   ├── Models/
│   │   ├── Config.swift           Ported from config.js DEFAULTS
│   │   ├── CalendarSource.swift
│   │   ├── EventItem.swift
│   │   ├── Areas.swift            Ported from js/areas.js (lane colours + rules)
│   │   └── WidgetSnapshot.swift   Shared with both widget/complication targets (see below)
│   ├── Services/
│   │   ├── ICSParser.swift        Hand-rolled ICS parser
│   │   ├── EventExpander.swift    RRULE occurrence expansion
│   │   ├── CalendarService.swift  Fetch + on-disk cache per calendar
│   │   ├── Filters.swift          Ported from js/filters.js
│   │   ├── Importance.swift       Ported from js/importance.js (spotlight/focus scoring)
│   │   ├── DocketStore.swift      Refresh orchestration + published state + snapshot fan-out
│   │   ├── SettingsStore.swift    UserDefaults + Keychain-backed settings
│   │   ├── KeychainStore.swift    Secret calendar URL storage
│   │   ├── NotificationScheduler.swift   Local notifications (the "push" story)
│   │   ├── NotificationDelegate.swift    Handles Snooze/Mark done taps
│   │   ├── BackgroundRefresh.swift       BGTaskScheduler wiring
│   │   ├── WidgetBridge.swift     Shared with both widget/complication targets (see below)
│   │   └── WatchConnectivityBridge.swift Pushes the snapshot to a paired Watch
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
├── DailyDocketWidget/              iOS Home Screen widget extension target
│   ├── DailyDocketWidgetBundle.swift   @main WidgetBundle
│   ├── SpotlightWidget.swift            Provider + views for the small/medium widget
│   ├── Info.plist                       NSExtensionPointIdentifier = widgetkit-extension
│   └── DailyDocketWidget.entitlements   Generated by xcodegen from project.yml (App Groups)
├── DailyDocketWatch/               watchOS companion app target
│   ├── DailyDocketWatchApp.swift  @main App — activates WatchSessionDelegate
│   ├── WatchSessionDelegate.swift Receives the snapshot over WatchConnectivity
│   ├── WatchContentView.swift     Minimal fallback UI; the complication is the real interface
│   ├── Info.plist                 WKApplication + WKCompanionAppBundleIdentifier
│   ├── Assets.xcassets/           AppIcon (placeholder, watch-marketing size)
│   └── DailyDocketWatch.entitlements   Generated by xcodegen from project.yml (App Groups)
└── DailyDocketWatchWidget/         watchOS complication extension target
    ├── DailyDocketWatchWidgetBundle.swift   @main WidgetBundle
    ├── SpotlightComplication.swift            circular/rectangular/inline complication views
    ├── Info.plist                             NSExtensionPointIdentifier = widgetkit-extension
    └── DailyDocketWatchWidget.entitlements   Generated by xcodegen from project.yml (App Groups)
```
