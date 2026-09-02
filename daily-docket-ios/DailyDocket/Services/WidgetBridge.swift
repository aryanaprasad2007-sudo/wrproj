import Foundation
import WidgetKit

/// The hand-off point between the app and the widget extension. WidgetKit
/// heavily throttles how often a widget's own TimelineProvider may run and
/// discourages it from doing real network work — so instead of teaching the
/// widget to fetch and parse calendars itself (which would mean duplicating
/// Keychain access, CalendarService, ICSParser, Filters, and Importance into
/// a second process, and fighting the widget refresh budget the whole way),
/// the app computes one WidgetSnapshot after every refresh and drops it in
/// App Group storage. The widget only ever reads that.
///
/// Requires the "group.com.aryanprasad.dailydocket" App Group capability on
/// BOTH the DailyDocket and DailyDocketWidgetExtension targets — see
/// project.yml. If that group isn't registered on your Apple Developer
/// account yet, change the identifier here (and in project.yml) to one you
/// own before building.
enum WidgetBridge {
    static let appGroupId = "group.com.aryanprasad.dailydocket"
    private static let snapshotKey = "docket.widget.snapshot.v1"

    private static var sharedDefaults: UserDefaults? {
        UserDefaults(suiteName: appGroupId)
    }

    static func write(_ snapshot: WidgetSnapshot) {
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        sharedDefaults?.set(data, forKey: snapshotKey)
    }

    static func read() -> WidgetSnapshot? {
        guard let data = sharedDefaults?.data(forKey: snapshotKey) else { return nil }
        return try? JSONDecoder().decode(WidgetSnapshot.self, from: data)
    }

    /// Call after `write` so the Home Screen widget picks up the change
    /// immediately instead of waiting for its own next scheduled reload.
    static func reloadWidgets() {
        WidgetCenter.shared.reloadAllTimelines()
    }
}
