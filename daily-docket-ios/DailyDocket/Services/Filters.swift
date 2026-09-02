import Foundation

/// Ported from js/filters.js — deciding what counts as a real commitment.
enum Filters {
    struct PrefixMatcher {
        let source: String
        let regex: NSRegularExpression
    }

    enum RejectReason {
        case prefix(String)
        case pattern(String)
        case cancelled
        case free
    }

    /// Separators people type between a tag and a title (mirrors SEP_CLASS in
    /// js/filters.js: middle dot, bullet, various dashes, punctuation, ~).
    private static let sepClassPattern = #"[·•‧∙・|/\\:;,~»>.–—−\s-]+"#
    private static let sepRegex = try! NSRegularExpression(pattern: sepClassPattern)

    private static func stripSeparators(_ s: String) -> String {
        let range = NSRange(s.startIndex..., in: s)
        return sepRegex.stringByReplacingMatches(in: s, range: range, withTemplate: "")
    }

    static func buildPrefixMatchers(_ prefixes: [String], lenient: Bool) -> [PrefixMatcher] {
        var out: [PrefixMatcher] = []
        for prefix in prefixes {
            let norm = prefix.precomposedStringWithCanonicalMapping.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !norm.isEmpty else { continue }

            if !lenient {
                let collapsedRange = NSRange(norm.startIndex..., in: norm)
                let collapser = try! NSRegularExpression(pattern: #"\s+"#)
                let collapsed = collapser.stringByReplacingMatches(in: norm, range: collapsedRange, withTemplate: " ")
                let escaped = NSRegularExpression.escapedPattern(for: collapsed).replacingOccurrences(of: " ", with: #"\s+"#)
                guard let re = try? NSRegularExpression(pattern: "^" + escaped, options: [.caseInsensitive]) else { continue }
                out.append(PrefixMatcher(source: prefix, regex: re))
                continue
            }

            let core = stripSeparators(norm)
            guard !core.isEmpty else { continue }
            let escapedCore = NSRegularExpression.escapedPattern(for: core)
            let lookahead = #"(?=$|[·•‧∙・|/\\:;,~»>.–—−\s-])"#
            guard let re = try? NSRegularExpression(pattern: "^" + escapedCore + lookahead, options: [.caseInsensitive]) else { continue }
            out.append(PrefixMatcher(source: prefix, regex: re))
        }
        return out
    }

    private static func matches(_ regex: NSRegularExpression, _ s: String) -> Bool {
        regex.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    static func rejectReason(_ item: EventItem, cfg: AppConfig, matchers: [PrefixMatcher]) -> RejectReason? {
        let title = item.title.precomposedStringWithCanonicalMapping.trimmingCharacters(in: .whitespacesAndNewlines)

        for m in matchers where matches(m.regex, title) {
            return .prefix(m.source)
        }
        for src in cfg.ignoreTitlePatterns {
            if let re = try? NSRegularExpression(pattern: src, options: [.caseInsensitive]), matches(re, title) {
                return .pattern(src)
            }
        }
        if cfg.skipCancelled, item.status == "CANCELLED" { return .cancelled }
        if cfg.skipTransparent, item.transparent {
            if !item.allDay || cfg.skipTransparentAllDay { return .free }
        }
        return nil
    }

    static func apply(_ items: [EventItem], cfg: AppConfig) -> (kept: [EventItem], dropped: [EventItem]) {
        let matchers = buildPrefixMatchers(cfg.ignoreTitlePrefixes, lenient: cfg.lenientPrefixMatch)
        var kept: [EventItem] = []
        var dropped: [EventItem] = []
        for item in items {
            if rejectReason(item, cfg: cfg, matchers: matchers) != nil {
                dropped.append(item)
            } else {
                kept.append(item)
            }
        }
        return (kept, dropped)
    }

    /// All-day items overlap the day; timed events belong to the day they
    /// start on, plus already-running ones when `includeRunning` is set.
    static func forDay(_ items: [EventItem], dayStart: Date, dayEnd: Date, includeRunning: Bool = false) -> (allDay: [EventItem], timed: [EventItem]) {
        let allDay = items.filter { $0.allDay && $0.start < dayEnd && max($0.end, $0.start.addingTimeInterval(1)) > dayStart }
        let timed = items
            .filter { item in
                guard !item.allDay else { return false }
                if item.start >= dayStart, item.start < dayEnd { return true }
                return includeRunning && item.start < dayStart && item.end > dayStart
            }
            .sorted { $0.start != $1.start ? $0.start < $1.start : $0.end < $1.end }
        return (allDay, timed)
    }

    static func splitByNow(_ timed: [EventItem], now: Date) -> (ahead: [EventItem], done: [EventItem]) {
        var ahead: [EventItem] = []
        var done: [EventItem] = []
        for item in timed {
            if item.end > now { ahead.append(item) } else { done.append(item) }
        }
        return (ahead, done)
    }
}
