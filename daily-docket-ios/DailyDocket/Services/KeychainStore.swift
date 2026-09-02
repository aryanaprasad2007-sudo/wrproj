import Foundation
import Security

/// Secret iCal URLs are a password (same warning as the web app's README) —
/// they go in the Keychain, not UserDefaults, and never in a JSON blob.
enum KeychainStore {
    private static let service = "com.aryanprasad.dailydocket.calendar-urls"

    static func urlString(for calendarId: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: calendarId,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func set(_ urlString: String, for calendarId: String) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: calendarId,
        ]

        if urlString.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            SecItemDelete(base as CFDictionary)
            return
        }

        let data = Data(urlString.utf8)
        let attributesToUpdate: [String: Any] = [kSecValueData as String: data]

        let updateStatus = SecItemUpdate(base as CFDictionary, attributesToUpdate as CFDictionary)
        if updateStatus == errSecItemNotFound {
            var addQuery = base
            addQuery[kSecValueData as String] = data
            SecItemAdd(addQuery as CFDictionary, nil)
        }
    }
}
