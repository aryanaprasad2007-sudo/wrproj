import WidgetKit
import SwiftUI

// MARK: - Timeline

struct SpotlightEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot?
}

struct SpotlightProvider: TimelineProvider {
    func placeholder(in context: Context) -> SpotlightEntry {
        SpotlightEntry(date: .now, snapshot: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (SpotlightEntry) -> Void) {
        completion(SpotlightEntry(date: .now, snapshot: context.isPreview ? .placeholder : WidgetBridge.read()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SpotlightEntry>) -> Void) {
        let entry = SpotlightEntry(date: .now, snapshot: WidgetBridge.read())
        // The countdown itself updates live on-device via Text(date, style: .timer)
        // — this reload is only a fallback in case the app hasn't run in a while
        // (WidgetBridge.reloadWidgets() is what normally drives fresher updates,
        // called right after every app refresh).
        let nextCheck = Calendar.current.date(byAdding: .minute, value: 30, to: .now) ?? .now.addingTimeInterval(1800)
        completion(Timeline(entries: [entry], policy: .after(nextCheck)))
    }
}

// MARK: - View

struct SpotlightWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: SpotlightEntry

    var body: some View {
        Group {
            if let snapshot = entry.snapshot, snapshot.todayTitle != nil || snapshot.tomorrowTitle != nil {
                content(snapshot)
            } else {
                emptyState
            }
        }
        .containerBackground(for: .widget) {
            LinearGradient(
                colors: [Color(red: 0.102, green: 0.063, blue: 0.188), Color(red: 0.184, green: 0.122, blue: 0.31)],
                startPoint: .topLeading, endPoint: .bottomTrailing
            )
        }
    }

    @ViewBuilder
    private func content(_ snapshot: WidgetSnapshot) -> some View {
        switch family {
        case .systemMedium:
            HStack(alignment: .top, spacing: 16) {
                todayColumn(snapshot)
                if snapshot.tomorrowTitle != nil {
                    Divider().overlay(.white.opacity(0.2))
                    tomorrowColumn(snapshot)
                }
            }
            .padding()
        default:
            todayColumn(snapshot)
                .padding()
        }
    }

    @ViewBuilder
    private func todayColumn(_ snapshot: WidgetSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(snapshot.todayIsHardDeadline ? "TODAY'S SPOTLIGHT" : "NEXT UP")
                .font(.system(size: 10, weight: .heavy))
                .foregroundStyle(.white.opacity(0.6))

            if let title = snapshot.todayTitle {
                Text("\(snapshot.todayIcon ?? "") \(title)")
                    .font(.headline)
                    .foregroundStyle(.white)
                    .lineLimit(2)

                if let target = snapshot.todayTargetDate {
                    Text(target, style: .timer)
                        .font(.system(.title2, design: .monospaced).bold())
                        .foregroundStyle(.white)
                        .minimumScaleFactor(0.6)
                }
                if let verb = snapshot.todayVerb, family != .systemSmall {
                    Text(verb)
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.7))
                }
            } else {
                Text("Nothing urgent today 🕊️")
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.85))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func tomorrowColumn(_ snapshot: WidgetSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("TOMORROW")
                .font(.system(size: 10, weight: .heavy))
                .foregroundStyle(.white.opacity(0.6))

            if let title = snapshot.tomorrowTitle {
                Text("\(snapshot.tomorrowIcon ?? "") \(title)")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white)
                    .lineLimit(2)

                if let target = snapshot.tomorrowTargetDate {
                    Text(target, style: .relative)
                        .font(.caption)
                        .foregroundStyle(.white.opacity(0.8))
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var emptyState: some View {
        VStack(spacing: 6) {
            Text("🗓️").font(.title2)
            Text("Daily Docket")
                .font(.headline)
                .foregroundStyle(.white)
            Text("Open the app to sync your calendar.")
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.7))
                .multilineTextAlignment(.center)
        }
        .padding()
    }
}

// MARK: - Widget

struct SpotlightWidget: Widget {
    let kind = "SpotlightWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SpotlightProvider()) { entry in
            SpotlightWidgetView(entry: entry)
        }
        .configurationDisplayName("Today's Spotlight")
        .description("Your most important deadline today, with a live countdown.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

#Preview(as: .systemSmall) {
    SpotlightWidget()
} timeline: {
    SpotlightEntry(date: .now, snapshot: .placeholder)
}

#Preview(as: .systemMedium) {
    SpotlightWidget()
} timeline: {
    SpotlightEntry(date: .now, snapshot: .placeholder)
}
