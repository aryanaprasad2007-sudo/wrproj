import Foundation

/// One calendar feed, ported 1:1 from a `calendars[]` entry in the web app's
/// config.js. `area` overrides the title-matching rules in Areas.swift.
struct CalendarSource: Identifiable, Codable, Equatable {
    var id: String
    var label: String
    var area: String?
    var enabled: Bool
    var url: String

    var normalizedURL: String {
        url.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "webcal://", with: "https://", options: .caseInsensitive)
    }
}
