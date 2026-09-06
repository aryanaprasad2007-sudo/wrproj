import Foundation
import WatchConnectivity

/// Receives the WidgetSnapshot the iPhone app pushes via
/// WatchConnectivityBridge.swift and drops it into this device's own copy of
/// the shared App Group storage — the same WidgetBridge.swift file the
/// complication reads from, unmodified, since UserDefaults(suiteName:) works
/// identically on watchOS.
final class WatchSessionDelegate: NSObject, WCSessionDelegate {
    static let shared = WatchSessionDelegate()
    private override init() { super.init() }

    func activate() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {}

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        guard let data = applicationContext["snapshot"] as? Data else { return }
        WidgetBridge.writeRawSnapshotData(data)
        WidgetBridge.reloadWidgets()
    }
}
