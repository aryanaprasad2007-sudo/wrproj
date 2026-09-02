import Foundation

/// Ported from config.js / js/settings.js DEFAULTS. Calendar URLs are the
/// one field intentionally missing here — those are "a password" (per the
/// web app's own README) and live in the Keychain via KeychainStore, never
/// in this Codable struct that gets serialized to UserDefaults.
struct AppConfig: Codable, Equatable {
    var ownerName: String = "Ari"
    var calendars: [CalendarSource] = AppConfig.defaultCalendars

    var ignoreTitlePrefixes: [String] = ["WR ·"]
    var lenientPrefixMatch: Bool = true
    var ignoreTitlePatterns: [String] = []

    var skipTransparent: Bool = true
    var skipTransparentAllDay: Bool = false
    var skipCancelled: Bool = true

    var extraDeadlineKeywords: [String: Double] = [
        "pset": 80,
        "lab report": 75,
        "canvas": 60,
        "ihss": 70,
        "instratix": 65,
    ]
    var pinMarker: String = "★"
    var deadlineScoreThreshold: Double = 60

    var refreshMinutes: Int = 15
    var hour12: Bool = true
    var showDoneCollapsed: Bool = true
    /// nil = follow the device's time zone, like config.js's `timeZone: null`.
    var timeZoneIdentifier: String?

    /// Minutes-before-deadline at which a local notification fires for
    /// today's spotlight event. No equivalent in the web app — this is the
    /// native app's answer to Web Push.
    var notificationLeadMinutes: [Int] = [60, 15]
    var morningDigestEnabled: Bool = true
    /// Local hour (0-23) the "today's docket is ready" notification fires.
    var morningDigestHour: Int = 7

    /// Lower than the web app's 15000 — this runs on a phone's background
    /// refresh budget, not a browser tab you already have open.
    var maxOccurrenceIterations: Int = 2000

    static let defaultCalendars: [CalendarSource] = [
        CalendarSource(id: "school", label: "School", area: nil, enabled: true, url: ""),
        CalendarSource(id: "routine", label: "Daily Routine", area: nil, enabled: true, url: ""),
        CalendarSource(id: "canvas", label: "Canvas", area: "School", enabled: true, url: ""),
        CalendarSource(
            id: "holidays", label: "Holidays", area: "Personal", enabled: false,
            url: "https://calendar.google.com/calendar/ical/en.usa%23holiday%40group.v.calendar.google.com/public/basic.ics"
        ),
        CalendarSource(
            id: "moreau", label: "Moreau", area: "School", enabled: false,
            url: "https://calendar.google.com/calendar/ical/moreaucatholic.org_qke2v53rrqfem5c91v5p9aeo4c%40group.calendar.google.com/public/basic.ics"
        ),
    ]

    var timeZone: TimeZone {
        (timeZoneIdentifier.flatMap(TimeZone.init(identifier:))) ?? .current
    }
}
