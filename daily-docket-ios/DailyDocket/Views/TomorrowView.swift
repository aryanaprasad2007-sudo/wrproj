import SwiftUI

struct TomorrowView: View {
    @EnvironmentObject private var settings: SettingsStore
    @EnvironmentObject private var store: DocketStore

    private var cfg: AppConfig { settings.config }

    var body: some View {
        let tomorrow = store.tomorrow()
        let dayStart = DateUtils.addDays(DateUtils.startOfDay(Date(), timeZone: cfg.timeZone), 1, timeZone: cfg.timeZone)

        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text(DateUtils.fmtDayLabel(dayStart, timeZone: cfg.timeZone))
                    .font(.title2.bold())
                    .padding(.top, 4)

                if !tomorrow.allDay.isEmpty {
                    allDayChips(tomorrow.allDay)
                }

                if let focus = tomorrow.focus {
                    focusCard(focus)
                }

                if tomorrow.timed.isEmpty && tomorrow.allDay.isEmpty {
                    Text("Nothing on the books yet.")
                        .foregroundStyle(.secondary)
                } else if !tomorrow.timed.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("TIMELINE")
                            .font(.caption.weight(.heavy))
                            .foregroundStyle(.secondary)
                        ForEach(tomorrow.timed) { item in
                            EventRowView(item: item, cfg: cfg)
                        }
                    }
                }
            }
            .padding()
        }
        .refreshable { await store.refresh() }
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
    private func focusCard(_ focus: Importance.Spotlight) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("TOMORROW'S FOCUS")
                .font(.caption.weight(.heavy))
                .foregroundStyle(.white.opacity(0.75))

            Text("\(Importance.iconFor(focus.item)) \(focus.item.title)")
                .font(.title3.weight(.bold))
                .foregroundStyle(.white)

            Text(DateUtils.fmtRange(focus.item, hour12: cfg.hour12, timeZone: cfg.timeZone))
                .font(.subheadline)
                .foregroundStyle(.white.opacity(0.85))

            if focus.isHardDeadline {
                CountdownText(target: focus.targetDate, font: .system(.title2, design: .monospaced).bold())
                    .foregroundStyle(.white)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(colors: [Color(hex: 0x7c3aed), Color(hex: 0x8b5cf6)], startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 20)
        )
    }
}
