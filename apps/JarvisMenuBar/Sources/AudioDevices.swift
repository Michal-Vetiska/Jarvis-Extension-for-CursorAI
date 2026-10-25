import Foundation
import CoreAudio
import AVFoundation

struct AudioDeviceInfo: Identifiable, Hashable {
    let id: AudioDeviceID
    let uid: String
    let name: String
    let isInput: Bool
    let isOutput: Bool
}

enum AudioDeviceManager {
    static let defaultUID = "__system_default__"

    static func listDevices() -> [AudioDeviceInfo] {
        var prop = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var dataSize: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &prop, 0, nil, &dataSize) == noErr else {
            return []
        }
        let count = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var ids = [AudioDeviceID](repeating: 0, count: count)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &prop, 0, nil, &dataSize, &ids) == noErr else {
            return []
        }

        return ids.compactMap { deviceID -> AudioDeviceInfo? in
            let name = stringProperty(deviceID, selector: kAudioObjectPropertyName) ?? "Device \(deviceID)"
            let uid = stringProperty(deviceID, selector: kAudioDevicePropertyDeviceUID) ?? "\(deviceID)"
            let hasInput = channelCount(deviceID, scope: kAudioDevicePropertyScopeInput) > 0
            let hasOutput = channelCount(deviceID, scope: kAudioDevicePropertyScopeOutput) > 0
            guard hasInput || hasOutput else { return nil }
            return AudioDeviceInfo(id: deviceID, uid: uid, name: name, isInput: hasInput, isOutput: hasOutput)
        }
    }

    static func inputDevices() -> [AudioDeviceInfo] {
        listDevices().filter(\.isInput)
    }

    static func outputDevices() -> [AudioDeviceInfo] {
        listDevices().filter(\.isOutput)
    }

    static func defaultInputUID() -> String? {
        guard let id = defaultDeviceID(selector: kAudioHardwarePropertyDefaultInputDevice) else { return nil }
        return stringProperty(id, selector: kAudioDevicePropertyDeviceUID)
    }

    static func defaultOutputUID() -> String? {
        guard let id = defaultDeviceID(selector: kAudioHardwarePropertyDefaultOutputDevice) else { return nil }
        return stringProperty(id, selector: kAudioDevicePropertyDeviceUID)
    }

    static func setDefaultInput(uid: String) -> Bool {
        if uid == defaultUID { return true }
        guard let id = deviceID(forUID: uid) else { return false }
        return setDefaultDevice(id, selector: kAudioHardwarePropertyDefaultInputDevice)
    }

    static func setDefaultOutput(uid: String) -> Bool {
        if uid == defaultUID { return true }
        guard let id = deviceID(forUID: uid) else { return false }
        return setDefaultDevice(id, selector: kAudioHardwarePropertyDefaultOutputDevice)
    }

    /// Dočasně přepne vstup, provede práci, pak obnoví původní default.
    static func withInputDevice<T>(uid: String, _ body: () async throws -> T) async rethrows -> T {
        if uid == defaultUID {
            return try await body()
        }
        let previous = defaultInputUID()
        _ = setDefaultInput(uid: uid)
        defer {
            if let previous {
                _ = setDefaultInput(uid: previous)
            }
        }
        return try await body()
    }

    static func withOutputDevice<T>(uid: String, _ body: () throws -> T) rethrows -> T {
        if uid == defaultUID {
            return try body()
        }
        let previous = defaultOutputUID()
        _ = setDefaultOutput(uid: uid)
        defer {
            if let previous {
                _ = setDefaultOutput(uid: previous)
            }
        }
        return try body()
    }

    // MARK: - CoreAudio helpers

    private static func defaultDeviceID(selector: AudioObjectPropertySelector) -> AudioDeviceID? {
        var prop = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var deviceID = AudioDeviceID(0)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &prop, 0, nil, &size, &deviceID)
        return status == noErr ? deviceID : nil
    }

    private static func setDefaultDevice(_ deviceID: AudioDeviceID, selector: AudioObjectPropertySelector) -> Bool {
        var prop = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var value = deviceID
        let size = UInt32(MemoryLayout<AudioDeviceID>.size)
        return AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &prop, 0, nil, size, &value) == noErr
    }

    private static func deviceID(forUID uid: String) -> AudioDeviceID? {
        listDevices().first(where: { $0.uid == uid })?.id
    }

    private static func channelCount(_ deviceID: AudioDeviceID, scope: AudioObjectPropertyScope) -> Int {
        var prop = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreamConfiguration,
            mScope: scope,
            mElement: kAudioObjectPropertyElementMain
        )
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(deviceID, &prop, 0, nil, &size) == noErr, size > 0 else { return 0 }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        guard AudioObjectGetPropertyData(deviceID, &prop, 0, nil, &size, raw) == noErr else { return 0 }
        let list = raw.assumingMemoryBound(to: AudioBufferList.self)
        let buffers = UnsafeMutableAudioBufferListPointer(list)
        return buffers.reduce(0) { $0 + Int($1.mNumberChannels) }
    }

    private static func stringProperty(_ deviceID: AudioDeviceID, selector: AudioObjectPropertySelector) -> String? {
        var prop = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(deviceID, &prop, 0, nil, &size) == noErr else { return nil }
        var cfName: Unmanaged<CFString>?
        let status = withUnsafeMutablePointer(to: &cfName) { ptr in
            AudioObjectGetPropertyData(deviceID, &prop, 0, nil, &size, ptr)
        }
        guard status == noErr, let cfName else { return nil }
        return cfName.takeUnretainedValue() as String
    }
}

/// Uložené preference zvuku (UserDefaults).
@MainActor
final class AudioPreferences: ObservableObject {
    static let shared = AudioPreferences()

    @Published var inputUID: String {
        didSet { UserDefaults.standard.set(inputUID, forKey: Keys.input) }
    }
    @Published var outputUID: String {
        didSet { UserDefaults.standard.set(outputUID, forKey: Keys.output) }
    }
    @Published var ttsVoice: String {
        didSet { UserDefaults.standard.set(ttsVoice, forKey: Keys.voice) }
    }
    @Published var applyOutputAsSystemDefault: Bool {
        didSet { UserDefaults.standard.set(applyOutputAsSystemDefault, forKey: Keys.applyOut) }
    }

    @Published var inputDevices: [AudioDeviceInfo] = []
    @Published var outputDevices: [AudioDeviceInfo] = []

    private enum Keys {
        static let input = "jarvis.audio.inputUID"
        static let output = "jarvis.audio.outputUID"
        static let voice = "jarvis.audio.ttsVoice"
        static let applyOut = "jarvis.audio.applyOutputDefault"
    }

    private init() {
        inputUID = UserDefaults.standard.string(forKey: Keys.input) ?? AudioDeviceManager.defaultUID
        outputUID = UserDefaults.standard.string(forKey: Keys.output) ?? AudioDeviceManager.defaultUID
        ttsVoice = UserDefaults.standard.string(forKey: Keys.voice) ?? "Zuzana"
        applyOutputAsSystemDefault = UserDefaults.standard.object(forKey: Keys.applyOut) as? Bool ?? false
        refreshDevices()
    }

    func refreshDevices() {
        inputDevices = AudioDeviceManager.inputDevices()
        outputDevices = AudioDeviceManager.outputDevices()
    }

    var inputLabel: String {
        if inputUID == AudioDeviceManager.defaultUID { return "Výchozí systémový vstup" }
        return inputDevices.first(where: { $0.uid == inputUID })?.name ?? inputUID
    }

    var outputLabel: String {
        if outputUID == AudioDeviceManager.defaultUID { return "Výchozí systémový výstup" }
        return outputDevices.first(where: { $0.uid == outputUID })?.name ?? outputUID
    }
}
