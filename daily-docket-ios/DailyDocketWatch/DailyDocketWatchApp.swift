import SwiftUI

@main
struct DailyDocketWatchApp: App {
    init() {
        WatchSessionDelegate.shared.activate()
    }

    var body: some Scene {
        WindowGroup {
            WatchContentView()
        }
    }
}
