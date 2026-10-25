import Foundation
import Combine
import AppKit

@MainActor
final class JarvisBridge: ObservableObject {
    @Published var connected = false
    @Published var listening = false
    @Published var voiceState = "idle"
    @Published var transcript: [[String: String]] = []
    @Published var taskSteps: [[String: String]] = []
    @Published var taskStatus: String = "—"
    @Published var activeProject: String = "—"
    @Published var serverURL: String = "—"
    @Published var serverStatus: String = "—"
    @Published var cursorStatus: String = "—"
    @Published var permissionsNote: String = ""
    @Published var lastError: String = ""
    @Published var micHint: String = ""
    @Published var partialSpeech: String = ""
    @Published var handsFreeEnabled = false
    @Published var isRecording = false
    @Published var llmStatus: String = "—"

    private let client = IPCClient()
    private var timer: Timer?
    private let speech = SpeechListener.shared

    init() {
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refresh()
                self?.syncSpeechUI()
            }
        }
        refresh()
    }

    private func syncSpeechUI() {
        isRecording = speech.isListening
        listening = speech.isListening
        partialSpeech = speech.partialText
        if speech.isListening {
            voiceState = handsFreeEnabled ? "hands-free" : "listening"
            if !speech.statusMessage.isEmpty {
                lastError = speech.statusMessage
            }
            if !speech.partialText.isEmpty {
                lastError = "Slyším: \(speech.partialText)"
            }
        } else if !speech.lastError.isEmpty {
            lastError = speech.lastError
        }
    }

    func refresh() {
        do {
            let state = try client.request(method: "get_state")
            connected = true
            if !speech.isListening {
                listening = false
                voiceState = (state["voice_state"] as? String) ?? "idle"
            }
            activeProject = (state["active_project"] as? String) ?? "—"
            if let transcriptArr = state["transcript"] as? [[String: Any]] {
                transcript = transcriptArr.compactMap { row in
                    guard let role = row["role"] as? String, let content = row["content"] as? String else { return nil }
                    return ["role": role, "content": content]
                }
            }
            if let task = state["task"] as? [String: Any] {
                taskStatus = (task["status"] as? String) ?? "—"
                if let steps = task["steps"] as? [[String: Any]] {
                    taskSteps = steps.map { step in
                        [
                            "name": (step["name"] as? String) ?? "?",
                            "status": (step["status"] as? String) ?? "?"
                        ]
                    }
                }
            } else {
                taskStatus = "—"
                taskSteps = []
            }
            if let server = state["server"] as? [String: Any] {
                serverURL = (server["url"] as? String) ?? "—"
                serverStatus = (server["status"] as? String) ?? "—"
            }
            if let cursor = state["cursor"] as? [String: Any] {
                if let auth = cursor["auth"] as? [String: Any] {
                    let ok = (auth["authenticated"] as? Bool) ?? false
                    cursorStatus = ok ? "přihlášen" : "vyžaduje agent login"
                }
            }
            if let llm = state["llm"] as? [String: Any] {
                if let status = llm["status"] as? String {
                    llmStatus = status
                    if status == "offline", let err = llm["error"] as? String {
                        if !speech.isListening {
                            lastError = "LM Studio offline: \(err)"
                        }
                    }
                } else if let url = llm["base_url"] as? String {
                    llmStatus = url
                }
            }
        } catch {
            connected = false
            if !speech.isListening {
                lastError = "Backend offline — chvíli počkej"
            }
        }
    }

    private var didAutoStartHandsFree = false

    /// Po startu appky automaticky zapne „Hej Adame…“
    func ensureHandsFreeAutoStart() {
        guard !didAutoStartHandsFree else { return }
        didAutoStartHandsFree = true
        Task { @MainActor in
            // Počkej na backend + oprávnění
            for _ in 0..<20 {
                if connected { break }
                try? await Task.sleep(nanoseconds: 250_000_000)
                refresh()
            }
            guard connected else {
                lastError = "Backend ještě neběží — zapni naslouchání ručně"
                return
            }
            if !handsFreeEnabled {
                await enableHandsFree()
            }
        }
    }

    /// Hands-free zap/vyp — „Hej Adame…“
    func toggleHandsFree() {
        Task { @MainActor in
            if handsFreeEnabled || speech.isListening {
                handsFreeEnabled = false
                speech.stop(submit: false)
                lastError = "Naslouchání vypnuto"
                voiceState = "idle"
                listening = false
                isRecording = false
                return
            }
            await enableHandsFree()
        }
    }

    private func enableHandsFree() async {
        handsFreeEnabled = true
        await speech.startHandsFree { [weak self] text in
            self?.submitRecognizedText(text)
        }
        lastError = "Řekni: Hej Adame…"
        syncSpeechUI()
    }

    /// Jednorázové: start nebo stop+odeslat
    func toggleTalk() {
        Task { @MainActor in
            if speech.isListening, !handsFreeEnabled {
                speech.stop(submit: true)
                syncSpeechUI()
                return
            }
            if handsFreeEnabled {
                // V hands-free režimu toto tlačítko jen zastaví
                toggleHandsFree()
                return
            }
            await speech.startCapture { [weak self] text in
                self?.submitRecognizedText(text)
            }
            syncSpeechUI()
        }
    }

    func stopListening() {
        handsFreeEnabled = false
        speech.stop(submit: false)
        listening = false
        isRecording = false
        voiceState = "idle"
        lastError = "Zastaveno"
        partialSpeech = ""
    }

    /// Ukončí naslouchání, backend i celou appku.
    func quitApp() {
        stopListening()
        BackendLauncher.shared.stop()
        NSApplication.shared.terminate(nil)
    }

    private func submitRecognizedText(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            lastError = "Nic jsem nerozuměl"
            return
        }
        lastError = "Posílám: \(trimmed)"
        transcript.append(["role": "user", "content": trimmed])
        do {
            _ = try client.request(method: "submit_text", params: ["text": trimmed])
            lastError = ""
        } catch {
            lastError = "Backend nepřijal text: \(error.localizedDescription)"
        }
        refresh()
        // Hands-free znovu zapne SpeechListener po emitAndStop
        if handsFreeEnabled, !speech.isListening {
            Task { @MainActor in
                await speech.startHandsFree { [weak self] text in
                    self?.submitRecognizedText(text)
                }
            }
        }
    }

    func stopTask() {
        _ = try? client.request(method: "cancel_task", params: [:])
    }

    func stopServer() {
        let alias = activeProject == "—" ? "" : activeProject
        _ = try? client.request(method: "stop_server", params: ["alias": alias])
    }

    func openLocalhost() {
        let alias = activeProject == "—" ? "" : activeProject
        _ = try? client.request(method: "open_localhost", params: ["alias": alias])
    }

    func loadPermissions() {
        do {
            let diag = try client.request(method: "permission_diagnostics")
            if let ax = diag["accessibility"] as? [String: Any] {
                let ok = (ax["ok"] as? Bool) ?? false
                permissionsNote = ok ? "Accessibility: OK" : "Accessibility: vyžaduje povolení"
            }
        } catch {
            permissionsNote = "Nelze načíst diagnostiku"
        }
        Task { @MainActor in
            let ok = await speech.requestPermissions()
            micHint = ok ? "Mikrofon + řeč: OK" : (speech.lastError.isEmpty ? "Chybí oprávnění" : speech.lastError)
        }
    }

    func fetchTTSVoices() -> [String]? {
        do {
            let result = try client.request(method: "list_tts_voices")
            return result["voices"] as? [String]
        } catch {
            return nil
        }
    }

    func fetchLLMSettings() -> (baseURL: String, model: String, health: String)? {
        do {
            let result = try client.request(method: "get_llm_settings")
            let base = (result["base_url"] as? String) ?? ""
            let model = (result["model"] as? String) ?? ""
            var health = "—"
            if let h = result["health"] as? [String: Any] {
                if (h["ok"] as? Bool) == true {
                    health = "Online"
                } else {
                    health = "Offline: \((h["error"] as? String) ?? "?")"
                }
            }
            llmStatus = health
            return (base, model, health)
        } catch {
            return nil
        }
    }

    func applyLLMSettings(baseURL: String, model: String) -> String {
        do {
            let result = try client.request(
                method: "set_llm_settings",
                params: ["base_url": baseURL, "model": model]
            )
            if let health = result["health"] as? [String: Any] {
                if (health["ok"] as? Bool) == true {
                    llmStatus = "Online"
                    return "LM Studio OK — spojené"
                }
                let err = (health["error"] as? String) ?? "nedostupné"
                llmStatus = "Offline"
                return "Uloženo, ale server neodpovídá: \(err)"
            }
            return "Uloženo"
        } catch {
            return "Chyba: \(error.localizedDescription)"
        }
    }

    @discardableResult
    func applyVoiceSettings(voice: String, outputUID: String) -> Bool {
        var outputName: String = ""
        if outputUID != AudioDeviceManager.defaultUID {
            outputName = AudioPreferences.shared.outputDevices.first(where: { $0.uid == outputUID })?.name ?? ""
        }
        do {
            let result = try client.request(
                method: "set_voice_settings",
                params: [
                    "tts_voice": voice,
                    "output_uid": outputUID,
                    "output_name": outputName,
                ]
            )
            return (result["ok"] as? Bool) ?? true
        } catch {
            lastError = "Backend nepřijal nastavení: \(error.localizedDescription)"
            return false
        }
    }
}
