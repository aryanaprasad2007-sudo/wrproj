import SwiftUI

/// A deliberately minimal companion screen — the complication is the real
/// interface here. This view exists mostly because a watchOS complication
/// extension can't exist without a companion watch app to host it; it just
/// mirrors whatever the complication is already showing, plus a manual
/// refresh in case WatchConnectivity hasn't delivered a context update yet.
struct WatchContentView: View {
    @State private var snapshot: WidgetSnapshot?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                if let snapshot, let title = snapshot.todayTitle {
                    Text(snapshot.todayIsHardDeadline ? "SPOTLIGHT" : "NEXT UP")
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.secondary)
                    Text("\(snapshot.todayIcon ?? "") \(title)")
                        .font(.headline)
                    if let target = snapshot.todayTargetDate {
                        Text(target, style: .timer)
                            .font(.system(.title3, design: .monospaced))
                            .monospacedDigit()
                    }
                } else {
                    Text("Daily Docket")
                        .font(.headline)
                    Text("Open the iPhone app to sync.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding()
        }
        .onAppear { snapshot = WidgetBridge.read() }
    }
}
