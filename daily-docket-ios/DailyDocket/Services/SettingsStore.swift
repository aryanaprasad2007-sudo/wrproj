import Foundation
import Combine

/// Persists AppConfig (everything except secret URLs) to UserDefaults as
/// JSON, and merges in each calendar's URL from the Keychain on read — the
/// same "non-secret file + secret store" split as config.js / config.local.js.
@MainActor
final class SettingsStore: ObservableObject {
    private static let defaultsKey = "docket.config.v1"

    @Published var config: AppConfig {
        didSet { persist() }
    }

    init() {
        if let data = UserDefaults.standard.data(forKey: Self.defaultsKey),
           let decoded = try? JSONDecoder().decode(AppConfig.self, from: data) {
            config = decoded
        } else {
            config = AppConfig()
        }
    }

    private func persist() {
        // Belt-and-suspenders: never let a stray URL slip into UserDefaults
        // even if something upstream forgot to clear it first.
        var toSave = config
        toSave.calendars = toSave.calendars.map { cal in
            var c = cal
            c.url = ""
            return c
        }
        if let data = try? JSONEncoder().encode(toSave) {
            UserDefaults.standard.set(data, forKey: Self.defaultsKey)
        }
    }

    /// Calendars with their Keychain-stored URL merged back in — what the
    /// networking layer actually needs.
    var calendarsWithURLs: [CalendarSource] {
        config.calendars.map { cal in
            var c = cal
            c.url = KeychainStore.urlString(for: cal.id) ?? cal.url
            return c
        }
    }

    func setURL(_ url: String, for calendarId: String) {
        KeychainStore.set(url, for: calendarId)
        objectWillChange.send()
    }

    func url(for calendarId: String) -> String {
        KeychainStore.urlString(for: calendarId) ?? ""
    }
}
