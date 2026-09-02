import SwiftUI

/// A ticking "2d 04:31:07" clock, refreshed once a second via TimelineView
/// (no manual Timer/invalidate bookkeeping needed).
struct CountdownText: View {
    let target: Date
    var font: Font = .system(.largeTitle, design: .monospaced).bold()

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            Text(DateUtils.fmtCountdown(target.timeIntervalSince(context.date)))
                .font(font)
                .monospacedDigit()
        }
    }
}
