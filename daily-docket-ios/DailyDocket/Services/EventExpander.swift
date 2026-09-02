import Foundation

/// Turns ICSParser.RawEvent (one VEVENT, possibly recurring) into concrete
/// EventItem occurrences overlapping a window — the native equivalent of
/// parseEvents()/parseAllFeeds() in js/calendar.js.
enum EventExpander {

    /// FREQ=DAILY/WEEKLY/MONTHLY/YEARLY with INTERVAL, COUNT, UNTIL, and
    /// (weekly only) BYDAY. Anything fancier than that just doesn't repeat
    /// the way this expects — see the ICSParser doc comment for the tradeoff.
    private static func occurrenceStarts(
        dtstart: Date, rrule: [String: String], exdates: Set<Date>,
        windowStart: Date, windowEnd: Date, cap: Int, timeZone: TimeZone
    ) -> [Date] {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone

        let freq = rrule["FREQ"] ?? "DAILY"
        let interval = max(1, Int(rrule["INTERVAL"] ?? "1") ?? 1)
        let count = rrule["COUNT"].flatMap { Int($0) }
        let until = rrule["UNTIL"].flatMap { value -> Date? in
            ICSParser.parseStandaloneDate(value)
        }
        let hardStop = [until, windowEnd].compactMap { $0 }.min() ?? windowEnd

        var results: [Date] = []

        if freq == "WEEKLY", let byday = rrule["BYDAY"], !byday.isEmpty {
            let weekdayMap = ["SU": 1, "MO": 2, "TU": 3, "WE": 4, "TH": 5, "FR": 6, "SA": 7]
            let targets = Set(byday.split(separator: ",").compactMap { weekdayMap[String($0)] })
            guard !targets.isEmpty else { return [] }

            let time = calendar.dateComponents([.hour, .minute, .second], from: dtstart)
            var weekStart = calendar.date(from: calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: dtstart)) ?? dtstart

            var n = 0
            var daySteps = 0
            let maxDaySteps = min(cap * 8, 8000)

            dayLoop: while weekStart < hardStop {
                for wd in targets.sorted() {
                    guard let day = calendar.date(bySetting: .weekday, value: wd, of: weekStart) else { continue }
                    daySteps += 1
                    if daySteps > maxDaySteps { break dayLoop }

                    var comps = calendar.dateComponents([.year, .month, .day], from: day)
                    comps.hour = time.hour; comps.minute = time.minute; comps.second = time.second
                    guard let occ = calendar.date(from: comps), occ >= dtstart, occ < hardStop else { continue }
                    if exdates.contains(occ) { continue }

                    n += 1
                    if let count, n > count { break dayLoop }
                    if occ < windowEnd { results.append(occ) }
                }
                guard let next = calendar.date(byAdding: .weekOfYear, value: interval, to: weekStart) else { break }
                weekStart = next
            }
            return results
        }

        let component: Calendar.Component = {
            switch freq {
            case "DAILY": return .day
            case "MONTHLY": return .month
            case "YEARLY": return .year
            default: return .weekOfYear // WEEKLY without BYDAY repeats on DTSTART's own weekday
            }
        }()

        var occurrence = dtstart
        var n = 0
        var steps = 0
        while steps < cap {
            steps += 1
            if occurrence >= hardStop { break }
            if !exdates.contains(occurrence) {
                n += 1
                if let count, n > count { break }
                if occurrence >= windowStart.addingTimeInterval(-86400 * 366), occurrence < windowEnd {
                    results.append(occurrence)
                }
            }
            guard let next = calendar.date(byAdding: component, value: interval, to: occurrence) else { break }
            occurrence = next
        }
        return results
    }

    private static func toItem(
        uid: String, start: Date, end: Date, allDay: Bool,
        summary: String, description: String, location: String,
        status: String, transparent: Bool, recurring: Bool, source: CalendarSource
    ) -> EventItem {
        let title = summary.trimmingCharacters(in: .whitespacesAndNewlines)
        let item = EventItem(
            key: "\(source.id)|\(uid)|\(start.timeIntervalSince1970)",
            uid: uid,
            title: title.isEmpty ? "(untitled)" : title,
            description: description.trimmingCharacters(in: .whitespacesAndNewlines),
            location: location.trimmingCharacters(in: .whitespacesAndNewlines),
            start: start, end: end, allDay: allDay,
            transparent: transparent, status: status, recurring: recurring,
            calendarLabel: source.label, calendarId: source.id,
            area: Areas.areaFor(title: title, description: description, calendarArea: source.area)
        )
        return item
    }

    static func expand(rawEvents: [ICSParser.RawEvent], source: CalendarSource, windowStart: Date, windowEnd: Date, cfg: AppConfig) -> [EventItem] {
        var masters: [ICSParser.RawEvent] = []
        var exceptionsByUID: [String: [ICSParser.RawEvent]] = [:]

        for ev in rawEvents {
            guard ev.dtstart != nil else { continue }
            if ev.recurrenceId != nil {
                exceptionsByUID[ev.uid, default: []].append(ev)
            } else {
                masters.append(ev)
            }
        }

        func overlaps(_ start: Date, _ end: Date) -> Bool {
            start < windowEnd && max(end, start.addingTimeInterval(1)) > windowStart
        }

        var consumedExceptionKeys = Set<String>() // "uid|recurrenceId"
        var items: [EventItem] = []

        for master in masters {
            guard let dtstart = master.dtstart else { continue }
            let duration: TimeInterval = {
                if let dtend = master.dtend { return dtend.timeIntervalSince(dtstart) }
                if let d = master.duration { return d }
                return master.allDay ? 86400 : 0
            }()

            let exdateSet = Set(master.exdates)
            let exceptions = exceptionsByUID[master.uid] ?? []

            func override(for occStart: Date) -> ICSParser.RawEvent? {
                exceptions.first { $0.recurrenceId.map { abs($0.timeIntervalSince(occStart)) < 1 } ?? false }
            }

            if let rrule = master.rrule {
                let starts = occurrenceStarts(
                    dtstart: dtstart, rrule: rrule, exdates: exdateSet,
                    windowStart: windowStart, windowEnd: windowEnd,
                    cap: cfg.maxOccurrenceIterations, timeZone: cfg.timeZone
                )
                for occStart in starts {
                    if let ex = override(for: occStart) {
                        consumedExceptionKeys.insert("\(master.uid)|\(occStart.timeIntervalSince1970)")
                        guard let exStart = ex.dtstart else { continue }
                        let exDuration: TimeInterval = ex.dtend.map { $0.timeIntervalSince(exStart) } ?? duration
                        let exEnd = exStart.addingTimeInterval(exDuration)
                        guard overlaps(exStart, exEnd) else { continue }
                        items.append(toItem(
                            uid: master.uid, start: exStart, end: exEnd, allDay: ex.allDay,
                            summary: ex.summary, description: ex.description, location: ex.location,
                            status: ex.status, transparent: ex.transparent, recurring: true, source: source
                        ))
                        continue
                    }
                    let occEnd = occStart.addingTimeInterval(duration)
                    guard overlaps(occStart, occEnd) else { continue }
                    items.append(toItem(
                        uid: master.uid, start: occStart, end: occEnd, allDay: master.allDay,
                        summary: master.summary, description: master.description, location: master.location,
                        status: master.status, transparent: master.transparent, recurring: true, source: source
                    ))
                }
            } else {
                let end = dtstart.addingTimeInterval(duration)
                guard overlaps(dtstart, end) else { continue }
                items.append(toItem(
                    uid: master.uid, start: dtstart, end: end, allDay: master.allDay,
                    summary: master.summary, description: master.description, location: master.location,
                    status: master.status, transparent: master.transparent, recurring: false, source: source
                ))
            }
        }

        // Orphan exceptions: a moved occurrence whose master lives outside this feed,
        // or whose recurrenceId didn't line up with a generated occurrence.
        for (uid, exList) in exceptionsByUID {
            for ex in exList {
                guard let recurrenceId = ex.recurrenceId else { continue }
                let key = "\(uid)|\(recurrenceId.timeIntervalSince1970)"
                if consumedExceptionKeys.contains(key) { continue }
                guard let exStart = ex.dtstart else { continue }
                let exDuration: TimeInterval = ex.dtend.map { $0.timeIntervalSince(exStart) } ?? (ex.allDay ? 86400 : 0)
                let exEnd = exStart.addingTimeInterval(exDuration)
                guard overlaps(exStart, exEnd) else { continue }
                items.append(toItem(
                    uid: uid, start: exStart, end: exEnd, allDay: ex.allDay,
                    summary: ex.summary, description: ex.description, location: ex.location,
                    status: ex.status, transparent: ex.transparent, recurring: true, source: source
                ))
            }
        }

        var dedup: [String: EventItem] = [:]
        for item in items { dedup[item.key] = item }
        return Array(dedup.values)
    }
}
