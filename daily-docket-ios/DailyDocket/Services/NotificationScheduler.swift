import Foundation
import UserNotifications

/// The native answer to the web app's Web Push: instead of a server pushing
/// to a browser subscription, the app computes today's spotlight deadline
/// itself (same Importance.pickSpotlight() the UI uses) and schedules local
/// notifications ahead of it. No backend, no VAPID keys, works even if the
/// app was last opened hours ago as long as BackgroundRefresh got to run.
enum NotificationScheduler {
    private static let leadPrefix = "docket.lead."
    private static let digestId = "docket.morning-digest"

    static func requestAuthorization() async -> Bool {
        let center = UNUserNotificationCenter.current()
        // .timeSensitive here is what lets a hard-deadline reminder ask the
        // system to break through Focus/DND — see the interruptionLevel set
        // below. Without it in the initial request, iOS won't show the
        // "Time Sensitive" toggle at all, and content.interruptionLevel just
        // silently degrades to .active.
        return (try? await center.requestAuthorization(options: [.alert, .sound, .badge, .timeSensitive])) ?? false
    }

    static func authorizationStatus() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    /// Replaces all pending "spotlight is in N minutes" notifications with
    /// fresh ones computed from the current feed data.
    static func scheduleSpotlightReminders(items: [EventItem], cfg: AppConfig) async {
        let center = UNUserNotificationCenter.current()
        let pending = await center.pendingNotificationRequests()
        let leadIds = pending.map(\.identifier).filter { $0.hasPrefix(leadPrefix) }
        center.removePendingNotificationRequests(withIdentifiers: leadIds)

        guard await authorizationStatus() == .authorized else { return }

        let now = Date()
        let dayStart = DateUtils.startOfDay(now, timeZone: cfg.timeZone)
        let dayEnd = DateUtils.addDays(dayStart, 1, timeZone: cfg.timeZone)
        let (allDay, timed) = Filters.forDay(items, dayStart: dayStart, dayEnd: dayEnd, includeRunning: true)
        guard let spotlight = Importance.pickSpotlight(timed: timed, allDay: allDay, now: now, cfg: cfg) else { return }

        for minutes in cfg.notificationLeadMinutes {
            let fireDate = spotlight.targetDate.addingTimeInterval(-Double(minutes) * 60)
            guard fireDate > now else { continue }

            let content = UNMutableNotificationContent()
            content.title = "Daily Docket"
            let verb = spotlight.targetVerb.isEmpty ? "is coming up" : spotlight.targetVerb
            content.body = "\(spotlight.item.title) \(verb) \(DateUtils.relTime(spotlight.targetDate, now: fireDate))"
            content.sound = .default
            // Only a genuine hard deadline earns the right to cut through
            // Focus/DND — a "next up" soft suggestion shouldn't interrupt.
            content.interruptionLevel = spotlight.isHardDeadline ? .timeSensitive : .active
            if spotlight.isHardDeadline { content.relevanceScore = 1.0 }

            let interval = fireDate.timeIntervalSince(now)
            let trigger = UNTimeIntervalNotificationTrigger(timeInterval: max(1, interval), repeats: false)
            let request = UNNotificationRequest(identifier: "\(leadPrefix)\(minutes)", content: content, trigger: trigger)
            try? await center.add(request)
        }
    }

    /// A repeating "today's docket is ready" ping at cfg.morningDigestHour.
    static func scheduleMorningDigest(cfg: AppConfig) async {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [digestId])
        guard cfg.morningDigestEnabled, await authorizationStatus() == .authorized else { return }

        var comps = DateComponents()
        comps.hour = cfg.morningDigestHour
        comps.minute = 0

        let content = UNMutableNotificationContent()
        content.title = "Daily Docket"
        content.body = "Good morning — today's docket is ready."
        content.sound = .default

        let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: true)
        let request = UNNotificationRequest(identifier: digestId, content: content, trigger: trigger)
        try? await center.add(request)
    }

    static func sendTestNotification() async {
        let content = UNMutableNotificationContent()
        content.title = "Daily Docket"
        content.body = "Test notification — if you see this, it works. 🎉"
        content.sound = .default
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 2, repeats: false)
        let request = UNNotificationRequest(identifier: "docket.test.\(UUID().uuidString)", content: content, trigger: trigger)
        try? await UNUserNotificationCenter.current().add(request)
    }
}
