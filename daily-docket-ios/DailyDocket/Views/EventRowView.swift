import SwiftUI

struct EventRowView: View {
    let item: EventItem
    let cfg: AppConfig
    var showAreaChip: Bool = true
    var showCalendarLabel: Bool = false
    var inProgress: Bool = false

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text(Importance.iconFor(item))
                .font(.title3)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(.body.weight(.semibold))
                    .strikethrough(item.status == "CANCELLED")

                HStack(spacing: 6) {
                    Text(DateUtils.fmtRange(item, hour12: cfg.hour12, timeZone: cfg.timeZone))
                    if inProgress {
                        Text("· now")
                            .foregroundStyle(.orange)
                    }
                    if showCalendarLabel, let label = item.calendarLabel {
                        Text("· \(label)")
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer()

            if showAreaChip, let area = item.area, let color = Areas.color[area] {
                Text(area)
                    .font(.caption2.weight(.bold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(color.opacity(0.22), in: Capsule())
                    .foregroundStyle(color)
            }
        }
        .padding(.vertical, 4)
    }
}
