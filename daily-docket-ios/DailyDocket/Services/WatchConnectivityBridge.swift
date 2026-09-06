import Foundation
import WatchConnectivity

/// Pushes the same WidgetSnapshot the Home Screen widget reads over to a
/// paired Apple Watch. An App Group is per-device storage, so it can't reach
/// the watch on its own — WatchConnectivity is the actual bridge between the
/// two devices.
///
/// Uses `updateApplicationContext` rather than `sendMessage` or
/// `transferUserInfo`: this is WatchConnectivity's "the watch only ever
/// needs the latest state, never a backlog" transfer, which matches a
/// spotlight snapshot exactly — the watch complication has no use for last
/// hour's spotlight once a new one exists, so there's nothing to queue.
/// Delivery is best-effort and only happens promptly while both devices are
/// reachable; the watch app's own periodic complication reload is the
/// fallback for "watch was out of range when this last ran."
final class WatchConnectivityBridge: NSObject, WCSessionDelegate {
    static let shared = WatchConnectivityBridge()
    private override init() { super.init() }

    func activate() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func send(_ snapshot: WidgetSnapshot) {
        guard WCSession.isSupported(), WCSession.default.activationState == .activated else { return }
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        try? WCSession.default.updateApplicationContext(["snapshot": data])
    }

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {}
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) {
        // Required for multi-watch support — reactivate for the newly paired watch.
        WCSession.default.activate()
    }
}
