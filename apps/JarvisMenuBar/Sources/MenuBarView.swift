import SwiftUI

struct MenuBarView: View {
    @EnvironmentObject var bridge: JarvisBridge
    @State private var showSettings = false
    @ObservedObject private var audio = AudioPreferences.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            Divider().overlay(Color.cyan.opacity(0.4))
            statusGrid
            Divider().overlay(Color.cyan.opacity(0.25))
            timeline
            Divider().overlay(Color.cyan.opacity(0.25))
            transcript
            Spacer(minLength: 0)
            controls
            if !bridge.lastError.isEmpty {
                Text(bridge.lastError)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .lineLimit(3)
            }
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
                .environmentObject(bridge)
                .frame(width: 460, height: 560)
        }
        .padding(14)
        .background(
            LinearGradient(
                colors: [Color.black, Color(red: 0.02, green: 0.08, blue: 0.12)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .preferredColorScheme(.dark)
        .onAppear {
            bridge.loadPermissions()
            // Automaticky začni hands-free po startu
            bridge.ensureHandsFreeAutoStart()
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("ADAM")
                    .font(.system(size: 20, weight: .semibold, design: .rounded))
                    .foregroundStyle(Color.cyan)
                Text(bridge.connected ? (bridge.handsFreeEnabled ? "Poslouchá — Hej Adame…" : "Backend připojen") : "Backend odpojen")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Circle()
                .fill(bridge.listening ? Color.cyan : Color.cyan.opacity(0.25))
                .frame(width: 14, height: 14)
                .shadow(color: bridge.listening ? .cyan.opacity(0.8) : .clear, radius: bridge.listening ? 8 : 0)
                .animation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true), value: bridge.listening)
        }
    }

    private var statusGrid: some View {
        VStack(alignment: .leading, spacing: 6) {
            labeled("Hlas", bridge.voiceState)
            labeled("Projekt", bridge.activeProject)
            labeled("Úkol", bridge.taskStatus)
            labeled("Server", "\(bridge.serverStatus) · \(bridge.serverURL)")
            labeled("Cursor", bridge.cursorStatus)
            labeled("LM Studio", bridge.llmStatus)
            labeled("Vstup", audio.inputLabel)
            labeled("Výstup", audio.outputLabel)
            if !bridge.permissionsNote.isEmpty {
                labeled("Oprávnění", bridge.permissionsNote)
            }
            if !bridge.micHint.isEmpty {
                labeled("Mikrofon", bridge.micHint)
            }
        }
        .font(.system(size: 12, design: .monospaced))
    }

    private func labeled(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top) {
            Text(title)
                .foregroundStyle(Color.cyan.opacity(0.8))
                .frame(width: 88, alignment: .leading)
            Text(value)
                .foregroundStyle(.primary)
                .lineLimit(2)
        }
    }

    private var timeline: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Průběh")
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.cyan)
            if bridge.taskSteps.isEmpty {
                Text("Žádný aktivní workflow")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(Array(bridge.taskSteps.enumerated()), id: \.offset) { _, step in
                    HStack {
                        Text(step["name"] ?? "")
                        Spacer()
                        Text(step["status"] ?? "")
                            .foregroundStyle(statusColor(step["status"] ?? ""))
                    }
                    .font(.caption2.monospaced())
                }
            }
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "ok", "running": return .cyan
        case "failed": return .red
        case "cancelled": return .orange
        default: return .secondary
        }
    }

    private var transcript: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Transkripty")
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.cyan)
            if !bridge.partialSpeech.isEmpty {
                Text("… \(bridge.partialSpeech)")
                    .font(.caption2)
                    .foregroundStyle(Color.cyan.opacity(0.7))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(bridge.transcript.suffix(30).enumerated()), id: \.offset) { _, row in
                        Text("\(row["role"] ?? ""): \(row["content"] ?? "")")
                            .font(.caption2)
                            .foregroundStyle((row["role"] == "user") ? Color.white : Color.cyan.opacity(0.9))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .frame(maxHeight: 160)
        }
    }

    private var controls: some View {
        VStack(spacing: 8) {
            Button(action: bridge.toggleHandsFree) {
                Label(
                    bridge.handsFreeEnabled ? "Poslouchám (Hej Adame) — klepni pro vypnutí" : "Zapnout naslouchání (Hej Adame)",
                    systemImage: bridge.handsFreeEnabled ? "ear.fill" : "ear"
                )
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(bridge.handsFreeEnabled ? .green : .cyan)
            .disabled(!bridge.connected)

            HStack {
                Button(action: bridge.toggleTalk) {
                    Label(
                        bridge.isRecording && !bridge.handsFreeEnabled ? "Hotovo / Stop" : "Říct jednou",
                        systemImage: "mic.fill"
                    )
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(!bridge.connected)

                if bridge.isRecording {
                    Button("Zrušit", action: bridge.stopListening)
                        .buttonStyle(.bordered)
                        .tint(.orange)
                }
            }

            HStack {
                Button("Stop úkol", action: bridge.stopTask)
                Button("Stop server", action: bridge.stopServer)
                Button("Localhost", action: bridge.openLocalhost)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)

            Button("Nastavení zvuku…") { showSettings = true }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .frame(maxWidth: .infinity)

            Button(role: .destructive, action: bridge.quitApp) {
                Label("Ukončit ADAM", systemImage: "power")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .tint(.red)
            .controlSize(.small)
        }
    }
}
