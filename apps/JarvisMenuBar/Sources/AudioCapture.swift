import AVFoundation
import Foundation

/// Nahrávání mikrofonu ve Swiftu (TCC oprávnění patří JARVIS.app, ne Pythonu).
final class AudioCapture: NSObject {
    static let shared = AudioCapture()

    private var recorder: AVAudioRecorder?
    private var finishTimer: Timer?
    private var continuation: CheckedContinuation<URL?, Never>?

    private override init() {
        super.init()
    }

    func requestPermission() async -> Bool {
        await withCheckedContinuation { cont in
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                cont.resume(returning: granted)
            }
        }
    }

    /// Nahraje řeč do WAV (16 kHz mono) a vrátí cestu k souboru.
    @MainActor
    func recordUtterance(maxSeconds: TimeInterval = 8.0, silenceSeconds: TimeInterval = 1.4) async -> URL? {
        let granted = await requestPermission()
        guard granted else { return nil }

        let inputUID = AudioPreferences.shared.inputUID
        return await AudioDeviceManager.withInputDevice(uid: inputUID) {
            await self.recordOnce(maxSeconds: maxSeconds, silenceSeconds: silenceSeconds)
        }
    }

    private func recordOnce(maxSeconds: TimeInterval, silenceSeconds: TimeInterval) async -> URL? {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("jarvis-ptt-\(UUID().uuidString).wav")

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: 16000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]

        do {
            let recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder.isMeteringEnabled = true
            recorder.prepareToRecord()
            guard recorder.record() else { return nil }
            self.recorder = recorder
        } catch {
            NSLog("JARVIS audio record error: %@", error.localizedDescription)
            return nil
        }

        return await withCheckedContinuation { cont in
            self.continuation = cont
            let started = Date()
            var lastVoice = Date()

            self.finishTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] timer in
                guard let self, let recorder = self.recorder else {
                    timer.invalidate()
                    return
                }
                recorder.updateMeters()
                let level = recorder.averagePower(forChannel: 0)
                if level > -40 {
                    lastVoice = Date()
                }
                let elapsed = Date().timeIntervalSince(started)
                let silentFor = Date().timeIntervalSince(lastVoice)
                if elapsed >= maxSeconds || (elapsed > 0.6 && silentFor >= silenceSeconds) {
                    timer.invalidate()
                    self.finishTimer = nil
                    recorder.stop()
                    self.recorder = nil
                    let cont = self.continuation
                    self.continuation = nil
                    cont?.resume(returning: url)
                }
            }
            RunLoop.main.add(self.finishTimer!, forMode: .common)
        }
    }
}
