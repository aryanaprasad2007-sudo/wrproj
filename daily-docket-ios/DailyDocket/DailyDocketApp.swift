import SwiftUI
import UserNotifications

@main
struct DailyDocketApp: App {
    @StateObject private var settings: SettingsStore
    @StateObject private var store: DocketStore
    @Environment(\.scenePhase) private var scenePhase

    init() {
        let settingsStore = SettingsStore()
        _settings = StateObject(wrappedValue: settingsStore)
        _store = StateObject(wrappedValue: DocketStore(settings: settingsStore))

        // Must happen before launch finishes, so a Snooze/Mark done tap on a
        // notification delivered while the app was killed still reaches the
        // delegate when iOS relaunches it.
        UNUserNotificationCenter.current().delegate = NotificationDelegate.shared
        NotificationScheduler.registerCategories()

        // Must be registered before applicationDidFinishLaunching returns.
        // A fresh SettingsStore re-reads UserDefaults/Keychain, so this picks
        // up anything changed on the Settings screen since the last refresh.
        BackgroundRefresh.register {
            let freshSettings = await SettingsStore()
            let backgroundStore = await DocketStore(settings: freshSettings)
            await backgroundStore.refresh()
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
                .environmentObject(store)
                .task {
                    await store.refresh()
                    BackgroundRefresh.schedule(minutes: settings.config.refreshMinutes)
                }
        }
        .onChange(of: scenePhase) { phase in
            if phase == .active {
                Task { await store.refresh() }
            } else if phase == .background {
                BackgroundRefresh.schedule(minutes: settings.config.refreshMinutes)
            }
        }
    }
}
