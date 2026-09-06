import WidgetKit
import SwiftUI

// Same read-only-snapshot pattern as the iPhone Home Screen widget
// (DailyDocketWidget/SpotlightWidget.swift) — this complication never
// fetches or parses calendars itself, only ever reads what
// WatchSessionDelegate last wrote via WidgetBridge.

struct ComplicationEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot?
}

struct ComplicationProvider: TimelineProvider {
    func placeholder(in context: Context) -> ComplicationEntry {
        ComplicationEntry(date: .now, snapshot: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (ComplicationEntry) -> Void) {
        completion(ComplicationEntry(date: .now, snapshot: context.isPreview ? .placeholder : WidgetBridge.read()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<ComplicationEntry>) -> Void) {
        let entry = ComplicationEntry(date: .now, snapshot: WidgetBridge.read())
        let nextCheck = Calendar.current.date(byAdding: .minute, value: 30, to: .now) ?? .now.addingTimeInterval(1800)
        completion(Timeline(entries: [entry], policy: .after(nextCheck)))
    }
}

struct SpotlightComplicationView: View {
    @Environment(\.widgetFamily) private var family
    let entry: ComplicationEntry

    var body: some View {
        switch family {
        case .accessoryCircular:
            circular
        case .accessoryInline:
            inline
        default:
            rectangular
        }
    }

    @ViewBuilder
    private var circular: some View {
        Gauge(value: progress) {
            Text("🗓️")
        } currentValueLabel: {
            if let target = entry.snapshot?.todayTargetDate {
                Text(target, style: .timer)
                    .font(.system(size: 12, design: .monospaced))
                    .minimumScaleFactor(0.5)
            } else {
                Text("--")
            }
        }
        .gaugeStyle(.accessoryCircularCapacity)
    }

    @ViewBuilder
    private var rectangular: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let title = entry.snapshot?.todayTitle {
                Text(title).font(.headline).lineLimit(1)
                if let target = entry.snapshot?.todayTargetDate {
                    Text(target, style: .timer)
                        .font(.system(.caption, design: .monospaced))
                }
            } else {
                Text("Daily Docket").font(.headline)
                Text("No spotlight").font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private var inline: some View {
        if let title = entry.snapshot?.todayTitle, let target = entry.snapshot?.todayTargetDate {
            Text("\(title) · \(target, style: .relative)")
        } else {
            Text("Daily Docket")
        }
    }

    /// Purely decorative — how "used up" the last-3-hours lead window looks,
    /// not a precise measure of anything.
    private var progress: Double {
        guard let target = entry.snapshot?.todayTargetDate else { return 0 }
        let remaining = target.timeIntervalSinceNow
        return remaining <= 0 ? 1 : min(1, max(0, 1 - remaining / (3 * 3600)))
    }
}

struct SpotlightComplication: Widget {
    let kind = "SpotlightComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: ComplicationProvider()) { entry in
            SpotlightComplicationView(entry: entry)
        }
        .configurationDisplayName("Today's Spotlight")
        .description("Your most important deadline today.")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

#Preview(as: .accessoryRectangular) {
    SpotlightComplication()
} timeline: {
    ComplicationEntry(date: .now, snapshot: .placeholder)
}
