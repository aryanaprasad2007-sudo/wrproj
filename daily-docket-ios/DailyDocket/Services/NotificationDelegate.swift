import Foundation
import UserNotifications

/// Handles the Snooze/Mark done action buttons (registered in
/// NotificationScheduler.registerCategories()) and makes sure alerts still
/// show while the app is open in the foreground — iOS suppresses banners
/// for a foregrounded app unless a delegate explicitly opts back in.
///
/// `UNUserNotificationCenter.delegate` is a weak reference, so this needs a
/// long-lived owner: `shared` is retained for the whole process lifetime,
/// independent of DailyDocketApp's own (struct) lifecycle. Assigned in
/// DailyDocketApp.init(), same "before launch finishes" timing requirement
/// as BackgroundRefresh.register — otherwise an action tapped while the app
/// was killed can be missed.
final class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationDelegate()
    private override init() {}

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .list])
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let content = response.notification.request.content
        let actionId = response.actionIdentifier

        Task {
            switch actionId {
            case NotificationScheduler.snoozeActionId:
                await NotificationScheduler.snoozeSpotlight(title: content.title, body: content.body)

            case NotificationScheduler.doneActionId:
                if let itemKey = content.userInfo["itemKey"] as? String {
                    let settings = await SettingsStore()
                    let cfg = await settings.config
                    await NotificationScheduler.markSpotlightDone(itemKey: itemKey, cfg: cfg)
                }

            default:
                // Includes UNNotificationDefaultActionIdentifier (a plain tap) —
                // nothing to do here, the system already brings the app forward.
                break
            }
            completionHandler()
        }
    }
}
