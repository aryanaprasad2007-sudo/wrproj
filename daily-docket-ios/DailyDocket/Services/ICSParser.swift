import Foundation

/// A small hand-rolled iCal parser — the native counterpart to the web app's
/// vendored ical.js. It covers what Google Calendar / Canvas feeds actually
/// emit: VEVENT, DTSTART/DTEND (or DURATION), all-day (VALUE=DATE), TZID
/// (resolved straight from the system's IANA database — Google exports use
/// Olson IDs like "America/Los_Angeles", so no VTIMEZONE parsing is needed),
/// RRULE (DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL, BYDAY),
/// EXDATE, and RECURRENCE-ID overrides.
///
/// What it deliberately does NOT handle: BYMONTHDAY/BYSETPOS/BYWEEKNO and
/// other advanced RRULE parts, or non-Olson (e.g. "Pacific Standard Time")
/// TZIDs from non-Google sources. Same tradeoff the web app's README makes
/// for its own edge cases — good enough for a personal calendar, not a
/// general-purpose calendar client.
enum ICSParser {

    struct RawEvent {
        var uid: String = ""
        var summary: String = ""
        var description: String = ""
        var location: String = ""
        var status: String = ""
        var transparent: Bool = false
        var allDay: Bool = false
        var dtstart: Date?
        var dtend: Date?
        var duration: TimeInterval?
        var rrule: [String: String]?
        var exdates: [Date] = []
        var recurrenceId: Date?
    }

    // MARK: - Line unfolding + property parsing

    private struct Property {
        var name: String
        var params: [String: String]
        var value: String
    }

    private static func unfold(_ text: String) -> [String] {
        var lines: [String] = []
        for raw in text.components(separatedBy: "\n") {
            let line = raw.hasSuffix("\r") ? String(raw.dropLast()) : raw
            if (line.hasPrefix(" ") || line.hasPrefix("\t")), !lines.isEmpty {
                lines[lines.count - 1] += line.dropFirst()
            } else if !line.isEmpty {
                lines.append(line)
            }
        }
        return lines
    }

    private static func parseProperty(_ line: String) -> Property? {
        guard let colonIndex = line.firstIndex(of: ":") else { return nil }
        let head = String(line[line.startIndex..<colonIndex])
        let value = String(line[line.index(after: colonIndex)...])

        let parts = head.split(separator: ";", omittingEmptySubsequences: false)
        guard let name = parts.first?.uppercased(), !name.isEmpty else { return nil }

        var params: [String: String] = [:]
        for part in parts.dropFirst() {
            guard let eq = part.firstIndex(of: "=") else { continue }
            let key = String(part[part.startIndex..<eq]).uppercased()
            var val = String(part[part.index(after: eq)...])
            if val.hasPrefix("\""), val.hasSuffix("\""), val.count >= 2 {
                val = String(val.dropFirst().dropLast())
            }
            params[key] = val
        }
        return Property(name: name, params: params, value: value)
    }

    private static func unescapeText(_ s: String) -> String {
        s.replacingOccurrences(of: "\\n", with: "\n")
            .replacingOccurrences(of: "\\N", with: "\n")
            .replacingOccurrences(of: "\\,", with: ",")
            .replacingOccurrences(of: "\\;", with: ";")
            .replacingOccurrences(of: "\\\\", with: "\\")
    }

    // MARK: - Date/time values

    private static func gmtCalendar() -> Calendar {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        return cal
    }

    /// Parses a DATE ("20260901") or DATE-TIME ("20260901T093000" / "...Z") value.
    private static func parseDateValue(_ value: String, tzid: String?, valueIsDate: Bool) -> (date: Date, isAllDay: Bool)? {
        let digits = value
        if valueIsDate || (digits.count == 8 && !digits.contains("T")) {
            var comps = DateComponents()
            guard digits.count >= 8,
                  let y = Int(digits.prefix(4)),
                  let m = Int(digits.dropFirst(4).prefix(2)),
                  let d = Int(digits.dropFirst(6).prefix(2))
            else { return nil }
            comps.year = y; comps.month = m; comps.day = d
            guard let date = gmtCalendar().date(from: comps) else { return nil }
            return (date, true)
        }

        // DATE-TIME: YYYYMMDDTHHMMSS, optionally suffixed Z (UTC).
        let isUTC = digits.hasSuffix("Z")
        let core = isUTC ? String(digits.dropLast()) : digits
        guard core.count >= 15 else { return nil }
        let y = Int(core.prefix(4)) ?? 1970
        let mo = Int(core.dropFirst(4).prefix(2)) ?? 1
        let d = Int(core.dropFirst(6).prefix(2)) ?? 1
        let h = Int(core.dropFirst(9).prefix(2)) ?? 0
        let mi = Int(core.dropFirst(11).prefix(2)) ?? 0
        let s = Int(core.dropFirst(13).prefix(2)) ?? 0

        var comps = DateComponents()
        comps.year = y; comps.month = mo; comps.day = d
        comps.hour = h; comps.minute = mi; comps.second = s

        var cal = Calendar(identifier: .gregorian)
        if isUTC {
            cal.timeZone = TimeZone(identifier: "UTC")!
        } else if let tzid, let tz = TimeZone(identifier: tzid) {
            cal.timeZone = tz
        } else {
            cal.timeZone = .current // floating time — best effort
        }
        guard let date = cal.date(from: comps) else { return nil }
        return (date, false)
    }

    /// "PT1H30M" style durations, the subset ICS actually uses.
    private static func parseDuration(_ value: String) -> TimeInterval? {
        var v = value
        guard v.hasPrefix("P") else { return nil }
        v.removeFirst()
        var days = 0.0, seconds = 0.0
        var inTime = false
        var numberBuffer = ""
        for ch in v {
            if ch == "T" { inTime = true; continue }
            if ch.isNumber { numberBuffer.append(ch); continue }
            let n = Double(numberBuffer) ?? 0
            numberBuffer = ""
            switch ch {
            case "W": days += n * 7
            case "D": days += n
            case "H": seconds += n * 3600
            case "M": seconds += inTime ? n * 60 : 0 // month-duration isn't a thing ICS uses in practice
            case "S": seconds += n
            default: break
            }
        }
        return days * 86400 + seconds
    }

    /// Public entry point for parsing a bare DATE/DATE-TIME value outside of
    /// a property line — used for RRULE's UNTIL=.
    static func parseStandaloneDate(_ value: String) -> Date? {
        parseDateValue(value, tzid: nil, valueIsDate: value.count == 8 && !value.contains("T"))?.date
    }

    // MARK: - Top-level parse

    static func parseEvents(from icsText: String) -> [RawEvent] {
        let lines = unfold(icsText)
        var events: [RawEvent] = []
        var current: RawEvent?
        var inEvent = false
        var inSubcomponent = false // VALARM etc. — its SUMMARY/DESCRIPTION must not clobber the event's

        for line in lines {
            guard let prop = parseProperty(line) else { continue }

            if prop.name == "BEGIN" {
                if prop.value == "VEVENT" { inEvent = true; current = RawEvent() }
                else if inEvent { inSubcomponent = true }
                continue
            }
            if prop.name == "END" {
                if prop.value == "VEVENT" {
                    if let ev = current { events.append(ev) }
                    current = nil; inEvent = false; inSubcomponent = false
                } else if inEvent {
                    inSubcomponent = false
                }
                continue
            }

            guard inEvent, !inSubcomponent, current != nil else { continue }

            let isDateOnly = prop.params["VALUE"] == "DATE"
            let tzid = prop.params["TZID"]

            switch prop.name {
            case "UID": current!.uid = prop.value
            case "SUMMARY": current!.summary = unescapeText(prop.value)
            case "DESCRIPTION": current!.description = unescapeText(prop.value)
            case "LOCATION": current!.location = unescapeText(prop.value)
            case "STATUS": current!.status = prop.value.uppercased()
            case "TRANSP": current!.transparent = prop.value.uppercased() == "TRANSPARENT"
            case "DTSTART":
                if let parsed = parseDateValue(prop.value, tzid: tzid, valueIsDate: isDateOnly) {
                    current!.dtstart = parsed.date
                    current!.allDay = parsed.isAllDay
                }
            case "DTEND":
                if let parsed = parseDateValue(prop.value, tzid: tzid, valueIsDate: isDateOnly) {
                    current!.dtend = parsed.date
                }
            case "DURATION":
                current!.duration = parseDuration(prop.value)
            case "RECURRENCE-ID":
                current!.recurrenceId = parseDateValue(prop.value, tzid: tzid, valueIsDate: isDateOnly)?.date
            case "EXDATE":
                for piece in prop.value.split(separator: ",") {
                    if let parsed = parseDateValue(String(piece), tzid: tzid, valueIsDate: isDateOnly) {
                        current!.exdates.append(parsed.date)
                    }
                }
            case "RRULE":
                var rule: [String: String] = [:]
                for pair in prop.value.split(separator: ";") {
                    let kv = pair.split(separator: "=", maxSplits: 1)
                    if kv.count == 2 { rule[String(kv[0]).uppercased()] = String(kv[1]) }
                }
                current!.rrule = rule
            default: break
            }
        }

        return events
    }
}
