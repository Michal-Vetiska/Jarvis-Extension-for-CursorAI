import socket
import threading

from jarvis.ipc.protocol import decode_message, encode_message, make_request
from jarvis.ipc.server import IpcServer
from pathlib import Path
import tempfile


def test_encode_decode_roundtrip():
    server, client = socket.socketpair()
    try:
        payload = make_request("ping", {"a": 1}, req_id=7)
        client.sendall(encode_message(payload))
        got = decode_message(server)
        assert got["method"] == "ping"
        assert got["params"]["a"] == 1
    finally:
        server.close()
        client.close()


def test_ipc_server_ping():
    with tempfile.TemporaryDirectory() as tmp:
        sock_path = Path(tmp) / "t.sock"
        server = IpcServer(sock_path, {"ping": lambda p: {"pong": True}})
        server.start()
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(str(sock_path))
            client.sendall(encode_message(make_request("ping")))
            resp = decode_message(client)
            assert resp["result"]["pong"] is True
            client.close()
        finally:
            server.stop()
