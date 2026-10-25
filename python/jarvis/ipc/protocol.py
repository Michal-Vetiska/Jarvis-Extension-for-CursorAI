"""JSON-RPC 2.0 helpers over length-prefixed Unix sockets."""

from __future__ import annotations

import json
import struct
from typing import Any


HEADER = struct.Struct("!I")


def encode_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return HEADER.pack(len(body)) + body


def read_exact(sock, nbytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = nbytes
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("Socket uzavřen během čtení zprávy")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def decode_message(sock) -> dict[str, Any]:
    header = read_exact(sock, HEADER.size)
    (length,) = HEADER.unpack(header)
    if length > 16 * 1024 * 1024:
        raise ValueError("Zpráva je příliš velká")
    body = read_exact(sock, length)
    return json.loads(body.decode("utf-8"))


def make_request(method: str, params: dict[str, Any] | None = None, req_id: int | str = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def make_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params or {}}


def make_result(req_id: int | str | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: int | str | None, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}
