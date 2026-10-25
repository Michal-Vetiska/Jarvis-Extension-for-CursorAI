import AVFoundation
import AppKit
import Foundation
import Speech

/// Hands-free + toggle mluvení přes Apple Speech (čeština) uvnitř JARVIS.app.
@MainActor
final class SpeechListener: NSObject, ObservableObject {
    static let shared = SpeechListener()

    @Published private(set) var isListening = false
    @Published private(set) var partialText: String = ""
    @Published var statusMessage: String = ""
    @Published var lastError: String = ""

    private let audioEngine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var silenceWatch: Task<Void, Never>?
    private var lastSpeechAt = Date()
    private var mode: Mode = .capture
    private var wakeArmed = true
    private var latestText = ""
    private var onUtterance: ((String) -> Void)?

    /// Wake fráze — vokativ „Adame“ + „Adam“ / „Hej Adame“
    private let wakePatterns = [
        "hej adame", "ahoj adame", "hej adam", "ahoj adam",
        "hey adam", "adame", "adam",
    ]

    private enum Mode {
        case handsFree
        case capture
    }

    private override init() {
        super.init()
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: "cs-CZ"))
            ?? SFSpeechRecognizer(locale: Locale(identifier: "cs"))
            ?? SFSpeechRecognizer()
    }

    func requestPermissions() async -> Bool {
        let speechOK: Bool = await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status == .authorized)
            }
        }
        let micOK: Bool = await withCheckedContinuation { cont in
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                cont.resume(returning: granted)
            }
        }
        if !speechOK {
            lastError = "Povol Rozpoznávání řeči → ADAM v Nastavení systému"
            return false
        }
        if !micOK {
            lastError = "Povol Mikrofon → ADAM"
            return false
        }
        lastError = ""
        return true
    }

    func startHandsFree(onUtterance: @escaping (String) -> Void) async {
        self.onUtterance = onUtterance
        mode = .handsFree
        wakeArmed = true
        latestText = ""
        await begin()
        statusMessage = "Naslouchám — řekni „Hej Adame…“"
    }

    func startCapture(onUtterance: @escaping (String) -> Void) async {
        self.onUtterance = onUtterance
        mode = .capture
        wakeArmed = false
        latestText = ""
        await begin()
        statusMessage = "Mluv — pak klepni Stop"
    }

    func stop(submit: Bool = false) {
        silenceWatch?.cancel()
        silenceWatch = nil
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        if audioEngine.isRunning {
            audioEngine.inputNode.removeTap(onBus: 0)
            audioEngine.stop()
        }
        isListening = false
        let text = cleanedCommand(from: latestText)
        partialText = ""
        statusMessage = ""
        if submit, !text.isEmpty {
            onUtterance?(text)
        }
    }

    private func begin() async {
        stop(submit: false)
        guard await requestPermissions() else { return }
        guard let recognizer, recognizer.isAvailable else {
            lastError = "Rozpoznávání řeči není dostupné"
            return
        }

        let inputUID = AudioPreferences.shared.inputUID
        if inputUID != AudioDeviceManager.defaultUID {
            _ = AudioDeviceManager.setDefaultInput(uid: inputUID)
        }

        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        self.request = req

        let input = audioEngine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            req.append(buffer)
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            lastError = "Nepodařilo se spustit mikrofon: \(error.localizedDescription)"
            return
        }

        isListening = true
        lastSpeechAt = Date()

        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            Task { @MainActor in
                guard let self, self.isListening else { return }
                if let result {
                    let text = result.bestTranscription.formattedString
                    self.latestText = text
                    self.partialText = text
                    self.lastSpeechAt = Date()
                    self.handle(text: text, isFinal: result.isFinal)
                }
                if error != nil, self.isListening == false {
                    // ignore after stop
                }
            }
        }

        silenceWatch = Task { [weak self] in
            while let self, !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 250_000_000)
                guard self.isListening else { break }
                let silentFor = Date().timeIntervalSince(self.lastSpeechAt)
                let cmd = self.cleanedCommand(from: self.latestText)
                // Kratší ticho = rychlejší odeslání příkazu
                if self.mode == .capture, silentFor >= 0.85, !cmd.isEmpty {
                    self.emitAndStop(cmd)
                    break
                }
                if self.mode == .handsFree, !self.wakeArmed, silentFor >= 0.9, !cmd.isEmpty {
                    self.emitAndStop(cmd)
                    break
                }
            }
        }
    }

    private func handle(text: String, isFinal: Bool) {
        if mode == .handsFree, wakeArmed {
            let lower = text.lowercased()
                .replacingOccurrences(of: ",", with: " ")
                .replacingOccurrences(of: ".", with: " ")
            if wakePatterns.contains(where: { lower.contains($0) }) {
                wakeArmed = false
                statusMessage = "Ano? Poslouchám…"
                lastSpeechAt = Date()
                // Krátké akustické potvrzení wake
                NSSound(named: "Tink")?.play()
            }
            return
        }
        if isFinal {
            let cmd = cleanedCommand(from: text)
            if !cmd.isEmpty {
                emitAndStop(cmd)
            }
        }
    }

    private func emitAndStop(_ text: String) {
        let cb = onUtterance
        stop(submit: false)
        statusMessage = ""
        cb?(text)
    }

    private func cleanedCommand(from text: String) -> String {
        var result = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let lower = result.lowercased()
        for wake in wakePatterns.sorted(by: { $0.count > $1.count }) {
            if let range = lower.range(of: wake) {
                let idx = result.index(result.startIndex, offsetBy: lower.distance(from: lower.startIndex, to: range.upperBound))
                result = String(result[idx...])
                    .trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
                break
            }
        }
        return result.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
