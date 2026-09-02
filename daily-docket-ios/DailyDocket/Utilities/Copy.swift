import Foundation

/// The warm-fuzzy copy from js/util.js, ported verbatim.
enum Copy {
    static func greeting(_ date: Date, name: String, timeZone: TimeZone) -> (text: String, emoji: String) {
        let h = DateUtils.calendar(for: timeZone).component(.hour, from: date)
        let who = name.isEmpty ? "" : ", \(name)"
        if h < 5 { return ("Still up\(who)?", "🌙") }
        if h < 12 { return ("Good morning\(who)", "☀️") }
        if h < 17 { return ("Good afternoon\(who)", "🌤️") }
        if h < 21 { return ("Good evening\(who)", "🌆") }
        return ("Winding down\(who)", "🌙")
    }

    private static let motivations = [
        "One thing at a time. That's the whole trick. 💜",
        "You don't have to do it all today — just the next thing. ✨",
        "Small, boring consistency beats brilliant bursts. Keep going. 🌱",
        "Future you is going to be so glad you showed up. 🌟",
        "Progress counts even when it's quiet. 🕯️",
        "You've done harder days than this one. 💪",
        "Protect the deep work. The rest can wait. 🎧",
        "Drink some water, stretch your back, then carry on. 💧",
        "Done is kinder than perfect. 🫶",
        "The plan is not the boss of you — it's a tool. Use it gently. 🧸",
        "Momentum is built, not found. Start tiny. 🐢",
        "You're allowed to be proud of an ordinary good day. 🌸",
        "Deadlines are just dates. You're the one with the plan. 📌",
        "Half a task done today is a head start tomorrow. 🌗",
        "Breathe. Then pick the first line on the list. 🌬️",
        "Consistency is a love letter to future you. 💌",
        "Rest is part of the work, not a break from it. 🛏️",
        "Nothing on this list is bigger than you are. 🏔️",
    ]

    /// Stable for a whole day, so it doesn't change on every refresh.
    static func motivation(_ date: Date, timeZone: TimeZone) -> String {
        let p = DateUtils.calendar(for: timeZone).dateComponents([.year, .month, .day], from: date)
        let seed = (p.year ?? 0) * 10000 + (p.month ?? 0) * 100 + (p.day ?? 0)
        return motivations[((seed % motivations.count) + motivations.count) % motivations.count]
    }
}
