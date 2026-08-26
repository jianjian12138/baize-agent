"""V25 评审 E-01/M-05 真实 MCP 参考 server (纯 stdlib).

A standalone MCP server that speaks stdio JSON-RPC 2.0 (2024-11-05) with
Content-Length framing. It implements initialize / notifications/initialized /
tools/list / tools/call and exposes one demo tool `echo_upper` that uppercases
its input. This is the *real* peer the baize StdioTransport connects to in the
acceptance integration test — no MemoryTransport, no mock.

Run: python examples/mcp_reference_server.py
"""
from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "2024-11-05"


def handle(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcp-reference-server", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "tools": [
                    {
                        "name": "echo_upper",
                        "description": "Uppercase the given text.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            },
        }
    if method == "tools/call":
        params = message.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        if name == "echo_upper":
            text = str(arguments.get("text", ""))
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": text.upper()}],
                    "isError": False,
                },
            }
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"method not found: {name}"},
        }
    return {
        "jsonrpc": "2.0", "id": msg_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def _read_frame(stream, buf: bytearray):
    while b"\r\n\r\n" not in buf:
        # ``BufferedReader.read(N)`` on Windows pipes can wait for N bytes,
        # deadlocking a peer that has already sent a valid, smaller frame.
        # Accumulate one byte at a time so framing progresses as data arrives.
        chunk = stream.read(1)
        if not chunk:
            raise EOFError
        buf.extend(chunk)
    header_blob, _, rest = bytes(buf).partition(b"\r\n\r\n")
    length = 0
    for line in header_blob.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    while len(rest) < length:
        chunk = stream.read(1)
        if not chunk:
            raise EOFError
        rest += chunk
    body = rest[:length]
    leftover = bytearray(rest[length:])
    return json.loads(body.decode("utf-8")), leftover


def _write_frame(stdout, obj: dict) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stdout.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8"))
    stdout.write(payload)
    stdout.flush()


def main() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    buf = bytearray()
    while True:
        try:
            message, buf = _read_frame(stdin, buf)
        except EOFError:
            return
        response = handle(message)
        if response is None:
            continue
        _write_frame(stdout, response)


if __name__ == "__main__":
    main()
