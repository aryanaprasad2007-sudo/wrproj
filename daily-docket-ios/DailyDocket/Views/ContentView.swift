import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: DocketStore
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            TabView {
                TodayView()
                    .tabItem { Label("Today", systemImage: "sun.max") }
                TomorrowView()
                    .tabItem { Label("Tomorrow", systemImage: "sunrise") }
            }
            .navigationTitle("Daily Docket")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: store.loading ? "arrow.triangle.2.circlepath" : "gearshape")
                    }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
        }
    }
}
