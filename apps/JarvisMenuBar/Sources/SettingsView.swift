import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var bridge: JarvisBridge
    @ObservedObject private var audio = AudioPreferences.shared
    @State private var ttsVoices: [String] = ["Zuzana", "Samantha"]
    @State private var saveMessage: String = ""
    @State private var lmBaseURL: String = "http://192.168.0.192:1234/v1"
    @State private var lmModel: String = "google/gemma-4-e4b"
    @State private var lmHealth: String = "—"

    var body: some View {
        Form {
            Section("Stav") {
                LabeledContent("Backend") {
                    Text(bridge.connected ? "Online" : "Offline")
                }
                LabeledContent("Cursor Agent") {
                    Text(bridge.cursorStatus)
                }
                LabeledContent("LM Studio") {
                    Text(bridge.llmStatus)
                }
            }

            Section("LM Studio (odpovědi AI)") {
                TextField("Base URL", text: $lmBaseURL)
                TextField("Model ID", text: $lmModel)
                Button("Uložit LM Studio a otestovat") {
                    let result = bridge.applyLLMSettings(baseURL: lmBaseURL, model: lmModel)
                    lmHealth = result
                    saveMessage = result
                }
                Text(lmHealth)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Zvuk — vstup (mikrofon)") {
                Picker("Vstup", selection: $audio.inputUID) {
                    Text("Výchozí systémový").tag(AudioDeviceManager.defaultUID)
                    ForEach(audio.inputDevices) { device in
                        Text(device.name).tag(device.uid)
                    }
                }
                Text("Aktuálně: \(audio.inputLabel)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Zvuk — výstup (reproduktor)") {
                Picker("Výstup", selection: $audio.outputUID) {
                    Text("Výchozí systémový").tag(AudioDeviceManager.defaultUID)
                    ForEach(audio.outputDevices) { device in
                        Text(device.name).tag(device.uid)
                    }
                }
                Toggle("Nastavit i jako systémový výchozí výstup", isOn: $audio.applyOutputAsSystemDefault)
                Text("Aktuálně: \(audio.outputLabel)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Hlas TTS") {
                Picker("Hlas", selection: $audio.ttsVoice) {
                    ForEach(ttsVoices, id: \.self) { voice in
                        Text(voice).tag(voice)
                    }
                }
            }

            Section("Akce") {
                Button("Obnovit seznam zařízení") {
                    audio.refreshDevices()
                    saveMessage = "Seznam zařízení obnoven"
                }
                Button("Uložit a použít") {
                    applyAudioSettings()
                }
                .buttonStyle(.borderedProminent)
                .tint(.cyan)
                if !saveMessage.isEmpty {
                    Text(saveMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Section("Oprávnění") {
                Text(bridge.permissionsNote.isEmpty ? "—" : bridge.permissionsNote)
                if !bridge.micHint.isEmpty {
                    Text(bridge.micHint)
                }
                Button("Obnovit diagnostiku") { bridge.loadPermissions() }
            }

            Section("Cursor") {
                Text("Přihlášení: agent login")
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(minWidth: 440, minHeight: 520)
        .onAppear {
            audio.refreshDevices()
            bridge.loadPermissions()
            loadVoices()
            if let s = bridge.fetchLLMSettings() {
                lmBaseURL = s.baseURL
                lmModel = s.model
                lmHealth = s.health
            }
        }
    }

    private func loadVoices() {
        if let voices = bridge.fetchTTSVoices(), !voices.isEmpty {
            ttsVoices = voices
            if !ttsVoices.contains(audio.ttsVoice) {
                audio.ttsVoice = ttsVoices.first ?? "Zuzana"
            }
        }
    }

    private func applyAudioSettings() {
        if audio.applyOutputAsSystemDefault, audio.outputUID != AudioDeviceManager.defaultUID {
            _ = AudioDeviceManager.setDefaultOutput(uid: audio.outputUID)
        }
        let ok = bridge.applyVoiceSettings(voice: audio.ttsVoice, outputUID: audio.outputUID)
        saveMessage = ok ? "Uloženo. Platí při dalším naslouchání." : "Uloženo lokálně; backend nepřijal hlas."
    }
}
