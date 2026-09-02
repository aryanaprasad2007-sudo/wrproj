import SwiftUI

struct TodayView: View {
    @EnvironmentObject private var settings: SettingsStore
    @EnvironmentObject private var store: DocketStore
    @State private var showDone = false

    private var cfg: AppConfig { settings.config }

    var body: some View {
        let today = store.today()
        let greeting = Copy.greeting(Date(), name: cfg.ownerName, timeZone: cfg.timeZone)

        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("\(greeting.emoji) \(greeting.text)")
                    .font(.title2.bold())
                    .padding(.top, 4)

                if let error = store.lastError {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                }

                if !today.allDay.isEmpty {
                    allDayChips(today.allDay)
                }

                if let spotlight = today.spotlight {
                    spotlightCard(spotlight)
                } else {
                    Text("Nothing urgent on the books — enjoy the calm. 🕊️")
                        .foregroundStyle(.secondary)
                }

                if !today.ahead.isEmpty {
                    section("Still ahead") {
                        ForEach(today.ahead) { item in
                            EventRowView(item: item, cfg: cfg, inProgress: isInProgress(item))
                        }
                    }
                }

                if !today.done.isEmpty {
                    DisclosureGroup(isExpanded: $showDone) {
                        VStack(alignment: .leading) {
                            ForEach(today.done) { item in
                                EventRowView(item: item, cfg: cfg)
                                    .opacity(0.55)
                            }
                        }
                    } label: {
                        Text("Already done (\(today.done.count))")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.secondary)
                    }
                }

                Text(Copy.motivation(Date(), timeZone: cfg.timeZone))
                    .font(.footnote.italic())
                    .foregroundStyle(.secondary)
                    .padding(.top, 8)
            }
            .padding()
        }
        .refreshable { await store.refresh() }
        .onAppear { showDone = !cfg.showDoneCollapsed } // collapsed by default, per config
    }

    private func isInProgress(_ item: EventItem) -> Bool {
        let now = Date()
        return item.start <= now && item.end > now
    }

    @ViewBuilder
    private func allDayChips(_ items: [EventItem]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack {
                ForEach(items) { item in
                    Text("\(Importance.iconFor(item)) \(item.title)")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(.thinMaterial, in: Capsule())
                }
            }
        }
    }

    @ViewBuilder
    private func spotlightCard(_ spotlight: Importance.Spotlight) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(spotlight.isHardDeadline ? "TODAY'S SPOTLIGHT" : "NEXT UP")
                .font(.caption.weight(.heavy))
                .foregroundStyle(.black.opacity(0.6))

            Text("\(Importance.iconFor(spotlight.item)) \(spotlight.item.title)")
                .font(.title3.weight(.bold))
                .foregroundStyle(.black)

            Text("\(spotlight.targetVerb) · \(DateUtils.fmtRange(spotlight.item, hour12: cfg.hour12, timeZone: cfg.timeZone))")
                .font(.subheadline)
                .foregroundStyle(.black.opacity(0.75))

            CountdownText(target: spotlight.targetDate, font: .system(.title, design: .monospaced).bold())
                .foregroundStyle(.black)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(colors: [Color(hex: 0xffe6a3), Color(hex: 0xffd580)], startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 20)
        )
    }

    @ViewBuilder
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.caption.weight(.heavy))
                .foregroundStyle(.secondary)
            content()
        }
    }
}
