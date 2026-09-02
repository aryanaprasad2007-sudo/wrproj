import Foundation

/// The one thing the widget extension is allowed to know. Deliberately tiny
/// and pre-computed — the widget never fetches calendars or scores events
/// itself (see WidgetBridge.swift for why), it just renders whatever the
/// main app last wrote here.
struct WidgetSnapshot: Codable {
    var updatedAt: Date
    var ownerName: String

    var todayTitle: String?
    var todayIcon: String?
    var todayVerb: String?
    var todayTargetDate: Date?
    var todayIsHardDeadline: Bool = false

    var tomorrowTitle: String?
    var tomorrowIcon: String?
    var tomorrowTargetDate: Date?
    var tomorrowIsHardDeadline: Bool = false

    var error: String?

    static let placeholder = WidgetSnapshot(
        updatedAt: .now,
        ownerName: "friend",
        todayTitle: "Finish problem set",
        todayIcon: "📝",
        todayVerb: "due in",
        todayTargetDate: Date().addingTimeInterval(3 * 3600),
        todayIsHardDeadline: true
    )
}
