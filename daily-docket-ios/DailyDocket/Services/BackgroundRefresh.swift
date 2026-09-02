import Foundation
import BackgroundTasks

/// Periodic background refresh so notifications stay accurate (and the
/// morning digest is meaningful) even when the app hasn't been opened.
/// iOS decides the actual cadence — this only ever *requests* roughly every
/// refreshMinutes; expect it to run less often than that in practice,
/// especially if the app is rarely foregrounded (iOS learns your usage
/// pattern and budgets background time accordingly).
enum BackgroundRefresh {
    static let taskIdentifier = "com.aryanprasad.dailydocket.refresh"

    /// Call once, before `application(_:didFinishLaunchingWithOptions:)`
    /// returns — BGTaskScheduler requires registration before app launch
    /// finishes. `onRefresh` should fetch, re-filter, and reschedule
    /// notifications, returning once it's safe for iOS to suspend the app.
    static func register(onRefresh: @escaping () async -> Void) {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskIdentifier, using: nil) { task in
            guard let task = task as? BGAppRefreshTask else { return }
            schedule() // always queue the next run before this one finishes

            let work = Task {
                await onRefresh()
                task.setTaskCompleted(success: true)
            }
            task.expirationHandler = { work.cancel() }
        }
    }

    static func schedule(minutes: Int = 60) {
        let request = BGAppRefreshTaskRequest(identifier: taskIdentifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: Double(minutes) * 60)
        try? BGTaskScheduler.shared.submit(request)
    }
}
