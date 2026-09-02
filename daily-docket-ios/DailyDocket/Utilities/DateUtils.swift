import Foundation

/// Time-zone aware date helpers. Native Foundation's Calendar already does
/// the DST-safe "start of day" / "add N days" work that js/util.js had to
/// hand-roll for the browser, so this file is much shorter than its origin.
enum DateUtils {
    static func calendar(for timeZone: TimeZone) -> Calendar {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = timeZone
        return cal
    }

    static func startOfDay(_ date: Date, timeZone: TimeZone) -> Date {
        calendar(for: timeZone).startOfDay(for: date)
    }

    static func addDays(_ date: Date, _ n: Int, timeZone: TimeZone) -> Date {
        calendar(for: timeZone).date(byAdding: .day, value: n, to: date) ?? date
    }

    static func clamp(_ n: Double, _ lo: Double, _ hi: Double) -> Double { min(hi, max(lo, n)) }

    static func fmtTime(_ date: Date, hour12: Bool, timeZone: TimeZone) -> String {
        let f = DateFormatter()
        f.timeZone = timeZone
        f.locale = Locale.autoupdatingCurrent
        f.setLocalizedDateFormatFromTemplate(hour12 ? "h:mm a" : "HH:mm")
        return f.string(from: date)
            .replacingOccurrences(of: "AM", with: "am")
            .replacingOccurrences(of: "PM", with: "pm")
    }

    static func fmtDayLabel(_ date: Date, timeZone: TimeZone) -> String {
        let f = DateFormatter()
        f.timeZone = timeZone
        f.locale = Locale.autoupdatingCurrent
        f.setLocalizedDateFormatFromTemplate("EEEE MMMM d")
        return f.string(from: date)
    }

    static func fmtRange(_ item: EventItem, hour12: Bool, timeZone: TimeZone) -> String {
        if item.allDay { return "all day" }
        let start = fmtTime(item.start, hour12: hour12, timeZone: timeZone)
        if item.end.timeIntervalSince(item.start) < 60 { return start }
        let end = fmtTime(item.end, hour12: hour12, timeZone: timeZone)
        return "\(start) – \(end)"
    }

    static func humanDuration(_ seconds: TimeInterval) -> String {
        let mins = max(0, Int((seconds / 60).rounded()))
        if mins < 60 { return "\(mins) min" }
        let h = mins / 60
        let m = mins % 60
        if h >= 24 {
            let d = h / 24
            return "\(d) day\(d == 1 ? "" : "s")"
        }
        return m > 0 ? "\(h)h \(m)m" : "\(h)h"
    }

    /// "in 3h 20m" / "5 min ago" / "now"
    static func relTime(_ target: Date, now: Date = Date()) -> String {
        let diff = target.timeIntervalSince(now)
        let a = abs(diff)
        if a < 60 { return "now" }
        let label = humanDuration(a)
        return diff > 0 ? "in \(label)" : "\(label) ago"
    }

    /// Big ticking clock: "2d 04:31:07", "4:31:07", "31:07".
    static func fmtCountdown(_ seconds: TimeInterval) -> String {
        if seconds <= 0 { return "00:00" }
        let total = Int(seconds)
        let d = total / 86400
        let h = (total % 86400) / 3600
        let m = (total % 3600) / 60
        let s = total % 60
        func p(_ n: Int) -> String { String(format: "%02d", n) }
        if d > 0 { return "\(d)d \(p(h)):\(p(m)):\(p(s))" }
        if h > 0 { return "\(h):\(p(m)):\(p(s))" }
        return "\(p(m)):\(p(s))"
    }
}
