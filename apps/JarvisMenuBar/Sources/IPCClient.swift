import Foundation

enum IPCError: Error {
    case notConnected
    case invalidResponse
    case remote(String)
}

final class IPCClient {
    private var socketFD: Int32 = -1
    private let queue = DispatchQueue(label: "jarvis.ipc")
    private let path: String

    init(socketPath: String? = nil) {
        if let socketPath {
            self.path = socketPath
        } else {
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            self.path = "\(home)/Library/Application Support/JARVIS/jarvis.sock"
        }
    }

    var isConnected: Bool { socketFD >= 0 }

    func connect() throws {
        if socketFD >= 0 { return }
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw IPCError.notConnected }
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let maxLen = MemoryLayout.size(ofValue: addr.sun_path) - 1
        let pathBytes = Array(path.utf8.prefix(maxLen)) + [0]
        _ = withUnsafeMutablePointer(to: &addr.sun_path.0) { ptr in
            pathBytes.withUnsafeBytes { raw in
                memcpy(ptr, raw.baseAddress!, pathBytes.count)
            }
        }
        let size = socklen_t(MemoryLayout<sockaddr_un>.size)
        let result = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(fd, $0, size)
            }
        }
        guard result == 0 else {
            close(fd)
            throw IPCError.notConnected
        }
        socketFD = fd
    }

    func disconnect() {
        if socketFD >= 0 {
            close(socketFD)
            socketFD = -1
        }
    }

    @discardableResult
    func request(method: String, params: [String: Any] = [:], id: Int = 1) throws -> [String: Any] {
        try connect()
        let payload: [String: Any] = [
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params
        ]
        let data = try JSONSerialization.data(withJSONObject: payload)
        var length = UInt32(data.count).bigEndian
        let header = Data(bytes: &length, count: 4)
        try writeAll(header)
        try writeAll(data)
        let responseData = try readMessage()
        guard let obj = try JSONSerialization.jsonObject(with: responseData) as? [String: Any] else {
            throw IPCError.invalidResponse
        }
        if let error = obj["error"] as? [String: Any] {
            throw IPCError.remote((error["message"] as? String) ?? "IPC error")
        }
        if let result = obj["result"] as? [String: Any] {
            return result
        }
        if obj["result"] != nil {
            return ["value": obj["result"] as Any]
        }
        throw IPCError.invalidResponse
    }

    private func writeAll(_ data: Data) throws {
        try data.withUnsafeBytes { raw in
            var written = 0
            let total = raw.count
            while written < total {
                let n = Darwin.write(socketFD, raw.baseAddress!.advanced(by: written), total - written)
                if n <= 0 { throw IPCError.notConnected }
                written += n
            }
        }
    }

    private func readExact(_ count: Int) throws -> Data {
        var buffer = Data(count: count)
        var offset = 0
        while offset < count {
            let n = buffer.withUnsafeMutableBytes { raw -> Int in
                Darwin.read(socketFD, raw.baseAddress!.advanced(by: offset), count - offset)
            }
            if n <= 0 { throw IPCError.notConnected }
            offset += n
        }
        return buffer
    }

    private func readMessage() throws -> Data {
        let header = try readExact(4)
        let length = header.withUnsafeBytes { $0.load(as: UInt32.self).bigEndian }
        return try readExact(Int(length))
    }
}
