import SwiftUI

/// The same area vocabulary the web app's js/areas.js uses (which itself
/// mirrors Daily-Docket/build_docket.py), so this app labels events the same
/// way the rest of wrproj does.
enum Areas {
    static let color: [String: Color] = [
        "School": Color(hex: 0x7fa8d9),
        "Pre-Med": Color(hex: 0xb57edc),
        "Trading": Color(hex: 0x4fb787),
        "Health": Color(hex: 0xe8829f),
        "Personal": Color(hex: 0xd97a4a),
        "Admin": Color(hex: 0xa98a95),
        "Interest": Color(hex: 0xf0c869),
    ]

    static let priorityColor: [String: Color] = [
        "High": Color(hex: 0xff5470),
        "Medium": Color(hex: 0xe0a458),
        "Low": Color(hex: 0x8a6a72),
    ]

    /// Checked in order — first match wins, so the specific rules come before
    /// the general ones. Ported verbatim from AREA_RULES in js/areas.js.
    private static let rules: [(area: String, pattern: String)] = [
        ("Admin", #"\b(ihss|dmv|soc ?426|live ?scan|instratix)\b"#),
        ("Trading", #"\b(market|trading|trade|swing|iape|pine ?script|watchlist|earnings|ticker|premarket|open(ing)? bell)\b"#),
        ("Pre-Med", #"\b(chem|chemistry|orgo|organic|bio(logy|logical)?|physics|mcat|pre-?med|clinical|shadow(ing)?|anatomy|physio)\b"#),
        ("Health", #"\b(doctor|dentist|clinic|kaiser|therapy|therapist|gym|workout|lift|cardio|immuni[sz]ation|vaccine|uc ?ship|physical)\b"#),
        ("School", #"\b(ucsc|canvas|class|lecture|lab|exam|midterm|final|quiz|assignment|homework|pset|problem set|essay|course|session|registrar|tuition|financial aid|slug|anth|summer edge|professor|discussion|orientation)\b"#),
        ("Admin", #"\b(ihss|dmv|insurance|paperwork|form|soc ?426|live ?scan|bank|budget(ing)?|savings|taxes|tax|invoice|bill|rent|business|client|instratix|commission)\b"#),
        ("Interest", #"\b(fragrance|cologne|fashion|outfit|brand|pinterest|inspo|model(ing)?|beat ?saber|draw(ing)?|language)\b"#),
        ("Personal", #"\b(birthday|bday|dance|rehearsal|dinner|lunch|breakfast|friends?|family|wind ?down|creative|hangout|party|movie|read(ing)?)\b"#),
    ]

    private static func matchRules(_ text: String) -> String? {
        guard !text.isEmpty else { return nil }
        for (area, pattern) in rules {
            if text.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil {
                return area
            }
        }
        return nil
    }

    /// An area set on the calendar source always wins. After that the title
    /// gets first vote; the description is only consulted if the title says
    /// nothing (matches areaFor() in js/areas.js).
    static func areaFor(title: String, description: String, calendarArea: String?) -> String? {
        if let calendarArea, !calendarArea.isEmpty { return calendarArea }
        return matchRules(title.lowercased()) ?? matchRules(description.lowercased())
    }

    static func priorityFor(score: Double, threshold: Double) -> String {
        if score >= threshold + 25 { return "High" }
        if score >= threshold { return "Medium" }
        return "Low"
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xff) / 255,
            green: Double((hex >> 8) & 0xff) / 255,
            blue: Double(hex & 0xff) / 255
        )
    }
}
