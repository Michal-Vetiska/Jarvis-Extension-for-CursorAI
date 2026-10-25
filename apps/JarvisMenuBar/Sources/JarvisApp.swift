import SwiftUI
import AppKit

@main
struct JarvisApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var bridge = JarvisBridge()

    var body: some Scene {
        MenuBarExtra {
            MenuBarView()
                .environmentObject(bridge)
                .frame(width: 380, height: 560)
        } label: {
            // Čistá textová ikona — SF Symbol v menu baru často vypadá rozbitě
            Text("A")
                .font(.system(size: 13, weight: .bold, design: .rounded))
                .foregroundStyle(bridge.listening ? Color.cyan : Color.primary)
        }
        .menuBarExtraStyle(.window)

        Settings {
            SettingsView()
                .environmentObject(bridge)
                .frame(width: 420, height: 360)
        }
    }
}
