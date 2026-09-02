import Foundation

/// Ties fetching, parsing, filtering and scoring together, and republishes
/// the result for the views — the native equivalent of state + refresh() in
/// js/app.js.
@MainActor
final class DocketStore: ObservableObject {
    @Published var items: [EventItem] = []
    @Published var loading = false
    @Published var lastError: String?
    @Published var lastRefreshed: Date?
    /// calendarId -> (reached it, serving a stale/cached copy)
    @Published var feedStatus: [String: (ok: Bool, stale: Bool)] = [:]

    let settings: SettingsStore

    init(settings: SettingsStore) {
        self.settings = settings
    }

    func refresh() async {
        loading = true
        defer { loading = false }

        let cfg = settings.config
        let sources = settings.calendarsWithURLs
        let results = await CalendarService.shared.fetchAll(sources)

        let now = Date()
        let windowStart = DateUtils.startOfDay(now, timeZone: cfg.timeZone)
        let windowEnd = DateUtils.addDays(windowStart, 2, timeZone: cfg.timeZone)

        var merged: [EventItem] = []
        var status: [String: (ok: Bool, stale: Bool)] = [:]
        var anyUsable = false

        for r in results {
            status[r.source.id] = (r.text != nil, r.stale)
            guard let text = r.text else { continue }
            anyUsable = true
            let raw = ICSParser.parseEvents(from: text)
            merged += EventExpander.expand(rawEvents: raw, source: r.source, windowStart: windowStart, windowEnd: windowEnd, cfg: cfg)
        }

        // The same event subscribed on two calendars shouldn't render twice.
        var seen: [String: EventItem] = [:]
        for item in merged {
            let dupKey = "\(item.title)|\(item.start.timeIntervalSince1970)|\(item.end.timeIntervalSince1970)"
            if seen[dupKey] == nil { seen[dupKey] = item }
        }

        let (kept, _) = Filters.apply(Array(seen.values), cfg: cfg)
        items = kept.sorted { a, b in
            if a.allDay != b.allDay { return a.allDay }
            if a.start != b.start { return a.start < b.start }
            if a.end != b.end { return a.end < b.end }
            return a.title < b.title
        }

        feedStatus = status
        lastRefreshed = now
        lastError = (!results.isEmpty && !anyUsable) ? "Could not reach any calendar, and there's no cached copy." : nil

        await NotificationScheduler.scheduleSpotlightReminders(items: items, cfg: cfg)
        await NotificationScheduler.scheduleMorningDigest(cfg: cfg)

        writeWidgetSnapshot(cfg: cfg, now: now)
    }

    /// Hands the Home Screen widget exactly what it needs to render, nothing
    /// more — see WidgetBridge.swift for why the widget doesn't fetch its
    /// own data.
    private func writeWidgetSnapshot(cfg: AppConfig, now: Date) {
        let todaySnap = today(now: now)
        let tomorrowSnap = tomorrow(now: now)

        var snapshot = WidgetSnapshot(updatedAt: now, ownerName: cfg.ownerName)

        if let spotlight = todaySnap.spotlight {
            snapshot.todayTitle = spotlight.item.title
            snapshot.todayIcon = Importance.iconFor(spotlight.item)
            snapshot.todayVerb = spotlight.targetVerb
            snapshot.todayTargetDate = spotlight.targetDate
            snapshot.todayIsHardDeadline = spotlight.isHardDeadline
        }
        if let focus = tomorrowSnap.focus {
            snapshot.tomorrowTitle = focus.item.title
            snapshot.tomorrowIcon = Importance.iconFor(focus.item)
            snapshot.tomorrowTargetDate = focus.isHardDeadline ? focus.targetDate : nil
            snapshot.tomorrowIsHardDeadline = focus.isHardDeadline
        }
        snapshot.error = lastError

        WidgetBridge.write(snapshot)
        WidgetBridge.reloadWidgets()
    }

    // Named *Snapshot, not *View, so this doesn't collide with the SwiftUI
    // views of nearly the same name in Views/TodayView.swift & TomorrowView.swift.
    struct TodaySnapshot {
        var allDay: [EventItem]
        var ahead: [EventItem]
        var done: [EventItem]
        var spotlight: Importance.Spotlight?
    }

    func today(now: Date = Date()) -> TodaySnapshot {
        let cfg = settings.config
        let dayStart = DateUtils.startOfDay(now, timeZone: cfg.timeZone)
        let dayEnd = DateUtils.addDays(dayStart, 1, timeZone: cfg.timeZone)
        let (allDay, timed) = Filters.forDay(items, dayStart: dayStart, dayEnd: dayEnd, includeRunning: true)
        let (ahead, done) = Filters.splitByNow(timed, now: now)
        let spotlight = Importance.pickSpotlight(timed: timed, allDay: allDay, now: now, cfg: cfg)
        return TodaySnapshot(allDay: allDay, ahead: ahead, done: done, spotlight: spotlight)
    }

    struct TomorrowSnapshot {
        var allDay: [EventItem]
        var timed: [EventItem]
        var focus: Importance.Spotlight?
    }

    func tomorrow(now: Date = Date()) -> TomorrowSnapshot {
        let cfg = settings.config
        let dayStart = DateUtils.addDays(DateUtils.startOfDay(now, timeZone: cfg.timeZone), 1, timeZone: cfg.timeZone)
        let dayEnd = DateUtils.addDays(dayStart, 1, timeZone: cfg.timeZone)
        let (allDay, timed) = Filters.forDay(items, dayStart: dayStart, dayEnd: dayEnd)
        let focus = Importance.pickFocus(timed: timed, allDay: allDay, dayStart: dayStart, cfg: cfg)
        return TomorrowSnapshot(allDay: allDay, timed: timed, focus: focus)
    }
}
