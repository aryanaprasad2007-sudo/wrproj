import SwiftUI
import UserNotifications

struct SettingsView: View {
    @EnvironmentObject private var settings: SettingsStore
    @EnvironmentObject private var store: DocketStore
    @Environment(\.dismiss) private var dismiss

    @State private var urlDrafts: [String: String] = [:]
    @State private var notificationStatus: UNAuthorizationStatus = .notDetermined
    @State private var statusMessage = ""
    @State private var showResetConfirm = false

    var body: some View {
        NavigationStack {
            Form {
                calendarsSection
                preferencesSection
                notificationsSection
                dangerSection
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .task {
                for cal in settings.config.calendars {
                    urlDrafts[cal.id] = settings.url(for: cal.id)
                }
                notificationStatus = await NotificationScheduler.authorizationStatus()
            }
        }
    }

    // MARK: - Sections

    private var calendarsSection: some View {
        Section {
            ForEach(settings.config.calendars) { cal in
                VStack(alignment: .leading, spacing: 6) {
                    Toggle(cal.label, isOn: enabledBinding(cal.id))
                    if enabledBinding(cal.id).wrappedValue {
                        TextField("Secret iCal URL", text: urlBinding(cal.id))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("Your calendars")
        } footer: {
            Text("Secret URLs live in this device's Keychain, never in a settings file. Google Calendar → ⚙ Settings → pick a calendar → “Integrate calendar” → Secret address in iCal format.")
        }
    }

    private var preferencesSection: some View {
        Section("Preferences") {
            TextField("Your name", text: nameBinding)
            Toggle("24-hour clock", isOn: notHour12Binding)
        }
    }

    private var notificationsSection: some View {
        Section {
            switch notificationStatus {
            case .authorized, .provisional:
                Text("On — this iPhone gets local notifications for today's spotlight deadline and (optionally) a morning digest.")
                    .font(.footnote)
                Toggle("Remind me before deadlines", isOn: leadRemindersBinding)
                Toggle("Morning digest", isOn: Binding(
                    get: { settings.config.morningDigestEnabled },
                    set: { settings.config.morningDigestEnabled = $0; Task { await reschedule() } }
                ))
                if settings.config.morningDigestEnabled {
                    Stepper(value: Binding(
                        get: { settings.config.morningDigestHour },
                        set: { settings.config.morningDigestHour = $0; Task { await reschedule() } }
                    ), in: 4...11) {
                        Text("At \(settings.config.morningDigestHour):00")
                    }
                }
                Button("Send test notification") {
                    Task { await NotificationScheduler.sendTestNotification() }
                }
            case .denied:
                Text("Notifications are off for Daily Docket. Enable them in iOS Settings → Daily Docket → Notifications.")
                    .font(.footnote)
                    .foregroundStyle(.orange)
            default:
                Button("Enable notifications") {
                    Task {
                        _ = await NotificationScheduler.requestAuthorization()
                        notificationStatus = await NotificationScheduler.authorizationStatus()
                        await reschedule()
                    }
                }
            }
            if !statusMessage.isEmpty {
                Text(statusMessage).font(.footnote).foregroundStyle(.secondary)
            }
        } header: {
            Text("Notifications")
        } footer: {
            Text("This app schedules notifications locally on the device — no push server, no VAPID keys, works as long as background refresh has recently run.")
        }
    }

    private var dangerSection: some View {
        Section {
            Button("Reset & clear cache", role: .destructive) { showResetConfirm = true }
                .confirmationDialog("Reset Daily Docket?", isPresented: $showResetConfirm, titleVisibility: .visible) {
                    Button("Reset", role: .destructive) { reset() }
                    Button("Cancel", role: .cancel) {}
                }
        }
    }

    // MARK: - Bindings

    private func enabledBinding(_ id: String) -> Binding<Bool> {
        Binding(
            get: { settings.config.calendars.first(where: { $0.id == id })?.enabled ?? true },
            set: { newValue in
                if let idx = settings.config.calendars.firstIndex(where: { $0.id == id }) {
                    settings.config.calendars[idx].enabled = newValue
                }
            }
        )
    }

    private func urlBinding(_ id: String) -> Binding<String> {
        Binding(
            get: { urlDrafts[id] ?? "" },
            set: { newValue in
                urlDrafts[id] = newValue
                settings.setURL(newValue, for: id)
            }
        )
    }

    private var nameBinding: Binding<String> {
        Binding(get: { settings.config.ownerName }, set: { settings.config.ownerName = $0 })
    }

    private var notHour12Binding: Binding<Bool> {
        Binding(get: { !settings.config.hour12 }, set: { settings.config.hour12 = !$0 })
    }

    private var leadRemindersBinding: Binding<Bool> {
        Binding(
            get: { !settings.config.notificationLeadMinutes.isEmpty },
            set: { on in
                settings.config.notificationLeadMinutes = on ? [60, 15] : []
                Task { await reschedule() }
            }
        )
    }

    // MARK: - Actions

    private func reschedule() async {
        statusMessage = "Updating…"
        await store.refresh()
        statusMessage = "Saved."
    }

    private func reset() {
        for cal in settings.config.calendars { settings.setURL("", for: cal.id) }
        settings.config = AppConfig()
        urlDrafts = [:]
        Task { await store.refresh() }
    }
}
