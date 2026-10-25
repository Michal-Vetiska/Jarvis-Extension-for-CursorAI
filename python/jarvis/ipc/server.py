"""Unix-domain JSON-RPC server for Swift UI ↔ Python backend."""

from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path
from typing import Any, Callable

from jarvis.ipc.protocol import decode_message, encode_message, make_error, make_result

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Any]


class IpcServer:
    def __init__(self, socket_path: Path, handlers: dict[str, Handler]) -> None:
        self.socket_path = socket_path
        self.handlers = handlers
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.socket_path))
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        self._stop.clear()
        self._thread = threading.Thread(target=self._accept_loop, name="jarvis-ipc", daemon=True)
        self._thread.start()
        logger.info("IPC server listening on %s", self.socket_path)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except OSError:
                    pass
            self._clients.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                pass

    def broadcast(self, method: str, params: dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        data = encode_message(payload)
        with self._lock:
            dead: list[socket.socket] = []
            for client in self._clients:
                try:
                    client.sendall(data)
                except OSError:
                    dead.append(client)
            for client in dead:
                self._clients.remove(client)

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                client, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                self._clients.append(client)
            threading.Thread(
                target=self._client_loop, args=(client,), name="jarvis-ipc-client", daemon=True
            ).start()

    def _client_loop(self, client: socket.socket) -> None:
        try:
            while not self._stop.is_set():
                try:
                    message = decode_message(client)
                except ConnectionError:
                    break
                response = self._dispatch(message)
                if response is not None:
                    client.sendall(encode_message(response))
        finally:
            with self._lock:
                if client in self._clients:
                    self._clients.remove(client)
            try:
                client.close()
            except OSError:
                pass

    def _dispatch(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if "method" not in message:
            return make_error(message.get("id"), -32600, "Neplatný požadavek")
        method = message["method"]
        params = message.get("params") or {}
        req_id = message.get("id")
        handler = self.handlers.get(method)
        if not handler:
            if req_id is None:
                return None
            return make_error(req_id, -32601, f"Neznámá metoda: {method}")
        try:
            result = handler(params if isinstance(params, dict) else {})
        except Exception as exc:  # noqa: BLE001
            logger.exception("IPC handler %s failed", method)
            if req_id is None:
                return None
            return make_error(req_id, -32000, str(exc))
        if req_id is None:
            return None
        return make_result(req_id, result)
