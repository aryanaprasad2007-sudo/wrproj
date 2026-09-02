import Foundation

/// One expanded occurrence of a calendar event — the Swift equivalent of the
/// plain objects `js/calendar.js`'s `toItem()` builds.
struct EventItem: Identifiable, Hashable {
    var key: String
    var uid: String
    var title: String
    var description: String
    var location: String
    var start: Date
    var end: Date
    var allDay: Bool
    var transparent: Bool
    var status: String
    var recurring: Bool
    var calendarLabel: String?
    var calendarId: String?
    var area: String?

    var id: String { key }

    var durationMinutes: Double { end.timeIntervalSince(start) / 60 }
}
