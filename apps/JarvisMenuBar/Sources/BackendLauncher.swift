import Foundation
import AppKit

/// Spouští a ukončuje Python backend zabalený v JARVIS.app.
final class BackendLauncher {
    static let shared = BackendLauncher()

    private var process: Process?
    private let pidFile: URL = {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/JARVIS", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("backend.pid")
    }()

    private init() {}

    func startIfNeeded() {
        // Vždy restartuj backend při startu appky, ať platí nový Python kód.
        stop()
        removeStaleSocket()
        // Krátká pauza, ať se uvolní port/socket
        Thread.sleep(forTimeInterval: 0.35)

        guard let launcher = bundledLauncherURL() else {
            NSLog("JARVIS: launch-backend.sh nenalezen v Resources")
            return
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/bash")
        proc.arguments = [launcher.path]
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "\(NSHomeDirectory())/.local/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
        proc.environment = env
        proc.terminationHandler = { [weak self] _ in
            self?.process = nil
            try? FileManager.default.removeItem(at: self?.pidFile ?? URL(fileURLWithPath: "/dev/null"))
        }

        do {
            try proc.run()
            process = proc
            try "\(proc.processIdentifier)".write(to: pidFile, atomically: true, encoding: .utf8)
            NSLog("JARVIS: backend PID %d", proc.processIdentifier)
        } catch {
            NSLog("JARVIS: backend start failed: %@", error.localizedDescription)
        }
    }

    func stop() {
        if let proc = process, proc.isRunning {
            proc.terminate()
            proc.waitUntilExit()
        }
        stopExistingFromPidFile()
        process = nil
    }

    private func bundledLauncherURL() -> URL? {
        if let url = Bundle.main.url(forResource: "launch-backend", withExtension: "sh") {
            return url
        }
        // Dev fallback: běh přes `swift run` z repo
        let dev = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // Sources
            .deletingLastPathComponent() // JarvisMenuBar
            .deletingLastPathComponent() // apps
            .appendingPathComponent("scripts/launch-backend-dev.sh")
        if FileManager.default.isExecutableFile(atPath: dev.path) {
            return dev
        }
        return nil
    }

    private func socketURL() -> URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/JARVIS/jarvis.sock")
    }

    private func removeStaleSocket() {
        let sock = socketURL()
        if FileManager.default.fileExists(atPath: sock.path) {
            try? FileManager.default.removeItem(at: sock)
        }
    }

    private func stopExistingFromPidFile() {
        guard let raw = try? String(contentsOf: pidFile, encoding: .utf8),
              let pid = Int32(raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              pid > 0 else { return }
        // Ukonči celou process group (bash + python)
        kill(pid, SIGTERM)
        // Fallback: zabij známý python modul
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        task.arguments = ["-f", "python -m jarvis.main"]
        try? task.run()
        task.waitUntilExit()
        try? FileManager.default.removeItem(at: pidFile)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        Task { @MainActor in
            let ok = await SpeechListener.shared.requestPermissions()
            NSLog("JARVIS speech/mic permission: %@", ok ? "granted" : "denied")
        }
        BackendLauncher.shared.startIfNeeded()
    }

    func applicationWillTerminate(_ notification: Notification) {
        BackendLauncher.shared.stop()
    }
}
