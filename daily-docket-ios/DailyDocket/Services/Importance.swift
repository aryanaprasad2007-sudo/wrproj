import Foundation

/// Ported from js/importance.js — deciding what deserves the gold spotlight
/// card. `hay` (title + description, lowercased) is matched against a fixed
/// list of deadline words; your own conventions (🚨, "(mandatory)",
/// "(blocks X)") score like keywords, same as the web app.
enum Importance {
    struct Score {
        var score: Double
        var pinned: Bool
        var isHardDeadline: Bool
        var matched: Int
    }

    struct Spotlight {
        var item: EventItem
        var score: Double
        var pinned: Bool
        var isHardDeadline: Bool
        var targetDate: Date
        var targetVerb: String
    }

    private static let deadlineRules: [(pattern: String, weight: Double)] = [
        (#"\bdue\b"#, 100),
        (#"\bdeadlines?\b"#, 100),
        ("🚨|‼️|❗", 94),
        (#"\bblocks?\b|\bblocking\b|\bblocker\b|\bgates?\b"#, 90),
        (#"\bmandatory\b|\brequired\b|\bnon-?negotiable\b"#, 86),
        ("⏰|⌛|⏳", 84),
        (#"\borientation\b"#, 70),
        (#"\bends?\b(?!\s*(?:up|with|the day))"#, 68),
        (#"\bfinal exam\b|\bmidterm\b|\bfinals?\b(?!\s*(?:fantasy|four))"#, 98),
        (#"\bexams?\b"#, 95),
        (#"\bsubmit(?:s|ted|ting|ssion)?\b|\bturn in\b|\bhand in\b"#, 92),
        (#"\binterviews?\b"#, 90),
        (#"\bflight\b|\bboarding\b|\bdepart(?:s|ure)?\b|\bcheck[- ]?in\b"#, 88),
        (#"\bpay(?:ment|able)?\b|\bbill\b|\binvoice\b|\bdeposit\b|\btuition\b|\brent\b"#, 86),
        (#"\bclos(?:es|ing)\b|\bexpires?\b|\blast day\b|\bcut ?off\b|\bends today\b"#, 85),
        (#"\bapply\b|\bapplications?\b"#, 82),
        (#"\bregist(?:er|ration)\b|\benroll(?:ment)?\b|\bsign ?up\b"#, 78),
        (#"\bquiz(?:zes)?\b"#, 76),
        (#"\bappointments?\b|\bappt\b|\bdoctor\b|\bdentist\b|\bclinic\b|\bdr\.\s"#, 74),
        (#"\bpresent(?:ation)?\b|\bdefen[cs]e\b|\bdemo\b|\bpitch\b"#, 72),
        (#"\bessays?\b|\bpapers?\b|\bproblem set\b|\bhomework\b|\bassignments?\b"#, 68),
        (#"\bshift\b|\bwork\b(?!out)"#, 62),
        (#"\btests?\b"#, 60),
        ("📌|🔴|⚠️", 58),
    ]

    private static let urgentWords = try! NSRegularExpression(pattern: #"\burgent\b|\basap\b|\bfinal notice\b|\bdon'?t forget\b|\blast chance\b"#, options: [.caseInsensitive])

    private static func test(_ pattern: String, _ s: String) -> Bool {
        guard let re = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { return false }
        return re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    static func scoreItem(_ item: EventItem, cfg: AppConfig) -> Score {
        let title = item.title
        let hay = "\(title) \(item.description)".lowercased()

        var rules = deadlineRules
        for (word, weight) in cfg.extraDeadlineKeywords {
            let escaped = NSRegularExpression.escapedPattern(for: word.lowercased())
            rules.append((#"\b"# + escaped + #"\b"#, weight))
        }

        var best: Double = 0
        var hits: [Double] = []
        for (pattern, weight) in rules where test(pattern, hay) {
            hits.append(weight)
            if weight > best { best = weight }
        }

        var score = best + DateUtils.clamp(Double(hits.count - 1) * 5, 0, 15)

        if urgentWords.firstMatch(in: hay, range: NSRange(hay.startIndex..., in: hay)) != nil { score += 20 }
        if title.contains("!!") { score += 12 }
        if title.count > 3, title == title.uppercased(), title.rangeOfCharacter(from: .letters) != nil { score += 10 }
        if item.allDay { score -= 10 }

        let pin = !cfg.pinMarker.isEmpty && title.contains(cfg.pinMarker)
        if pin { score += 1000 }

        return Score(score: score, pinned: pin, isHardDeadline: score >= cfg.deadlineScoreThreshold, matched: hits.count)
    }

    /// When the clock should count down to, and how to label it.
    static func deadlineTarget(_ item: EventItem, now: Date, hard: Bool) -> (at: Date, verb: String) {
        if item.allDay {
            return (item.end, hard ? "due by end of day" : "all day")
        }
        if item.start > now {
            let isMoment = item.end.timeIntervalSince(item.start) <= 15 * 60
            return (item.start, hard && isMoment ? "due in" : "starts in")
        }
        return (item.end, "ends in")
    }

    private static func urgencyBonus(_ item: EventItem, now: Date, hard: Bool) -> Double {
        let target = deadlineTarget(item, now: now, hard: hard).at
        let hours = target.timeIntervalSince(now) / 3600
        return DateUtils.clamp(48 - hours * 2, 0, 48)
    }

    private static func rank(_ items: [EventItem], now: Date, cfg: AppConfig, durationWeight: Double = 0) -> [(item: EventItem, score: Score, priority: Double)] {
        items.map { item in
            let s = scoreItem(item, cfg: cfg)
            let durMins = item.end.timeIntervalSince(item.start) / 60
            var priority = s.score + urgencyBonus(item, now: now, hard: s.isHardDeadline)
            if durationWeight != 0 {
                priority += DateUtils.clamp(durMins / 6, 0, 40) * durationWeight
            }
            return (item, s, priority)
        }.sorted { a, b in
            if a.priority != b.priority { return a.priority > b.priority }
            return a.item.start < b.item.start
        }
    }

    /// Today's gold card: the most important hard deadline still ahead.
    static func pickSpotlight(timed: [EventItem], allDay: [EventItem], now: Date, cfg: AppConfig) -> Spotlight? {
        var pool = timed.filter { $0.end > now }
        pool += allDay.filter { $0.end > now && scoreItem($0, cfg: cfg).isHardDeadline }
        guard !pool.isEmpty else { return nil }

        let ranked = rank(pool, now: now, cfg: cfg)
        let hard = ranked.filter { $0.score.isHardDeadline }
        guard let winner = (hard.isEmpty ? ranked : hard).first else { return nil }

        let target = deadlineTarget(winner.item, now: now, hard: winner.score.isHardDeadline)
        return Spotlight(
            item: winner.item, score: winner.score.score, pinned: winner.score.pinned,
            isHardDeadline: winner.score.isHardDeadline, targetDate: target.at, targetVerb: target.verb
        )
    }

    /// Tomorrow's focus card: the biggest thing on the day.
    static func pickFocus(timed: [EventItem], allDay: [EventItem], dayStart: Date, cfg: AppConfig) -> Spotlight? {
        let pool = timed.isEmpty ? allDay : timed + allDay.filter { scoreItem($0, cfg: cfg).isHardDeadline }
        guard !pool.isEmpty else { return nil }

        let ranked = rank(pool, now: dayStart, cfg: cfg, durationWeight: 1)
        guard let winner = ranked.first else { return nil }

        let target = winner.score.isHardDeadline ? deadlineTarget(winner.item, now: Date(), hard: true) : nil
        return Spotlight(
            item: winner.item, score: winner.score.score, pinned: winner.score.pinned,
            isHardDeadline: winner.score.isHardDeadline,
            targetDate: target?.at ?? winner.item.start, targetVerb: target?.verb ?? ""
        )
    }

    // MARK: - A little visual shorthand (ported from ICONS in js/importance.js)

    private static let icons: [(pattern: String, emoji: String)] = [
        (#"\bgym\b|\blift\b|\bworkout\b|\btrain(?:ing)?\b|\bcardio\b|\brun\b"#, "🏋️"),
        (#"\bdance|\bchoreo|\bballet|\bhip ?hop|\brehearsal\b"#, "💃"),
        (#"\blab\b|\bchem\b|\bbio(?:logy)?\b|\bexperiment\b"#, "🧪"),
        (#"\bexam\b|\bmidterm\b|\bfinal\b|\bquiz\b|\btest\b"#, "📝"),
        (#"\blecture\b|\bclass\b|\bcourse\b|\bseminar\b|\bdiscussion\b"#, "📚"),
        (#"\bstudy\b|\breview\b|\bread(?:ing)?\b|\bflashcards?\b|\banki\b"#, "📖"),
        (#"\bmarket\b|\btrade\b|\btrading\b|\bopen(?:ing)? bell\b|\bearnings\b|\bswing\b"#, "📈"),
        (#"\bdoctor\b|\bdentist\b|\bclinic\b|\bappointment\b|\bappt\b|\btherapy\b"#, "🩺"),
        (#"\bflight\b|\bairport\b|\bdepart\b|\bboarding\b"#, "✈️"),
        (#"\bbirthday\b|\bbday\b|🎂"#, "🎂"),
        (#"\bcall\b|\bzoom\b|\bmeet(?:ing)?\b|\bsync\b|\b1:1\b|\bstandup\b"#, "🤝"),
        (#"\binterview\b"#, "🎤"),
        (#"\blunch\b|\bdinner\b|\bbreakfast\b|\bcoffee\b|\bmeal\b|\beat\b"#, "🍽️"),
        (#"\bsleep\b|\bbed\b|\bwind ?down\b|\brest\b"#, "😴"),
        (#"\bpay\b|\bbill\b|\brent\b|\btuition\b|\binvoice\b|\bdeposit\b"#, "💳"),
        (#"\bdue\b|\bdeadline\b|\bsubmit\b"#, "⏰"),
        (#"\bshift\b|\bwork\b|\bihss\b"#, "💼"),
        (#"\bdrive\b|\bcommute\b|\bbus\b|\btrain\b"#, "🚗"),
    ]

    static func hasLeadingEmoji(_ title: String) -> Bool {
        guard let first = title.trimmingCharacters(in: .whitespaces).unicodeScalars.first else { return false }
        return first.properties.isEmojiPresentation || (first.properties.isEmoji && first.value > 0x2100)
    }

    static func iconFor(_ item: EventItem) -> String {
        if hasLeadingEmoji(item.title) { return "" }
        let hay = item.title.lowercased()
        for (pattern, emoji) in icons where test(pattern, hay) { return emoji }
        return item.allDay ? "🗓️" : "•"
    }
}
