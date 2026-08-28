"""MCP server — expose baize's ToolRegistry tools to external MCP clients.

Part of ``baize.ext.mcp``; imported lazily. ``MCPServer.handle`` implements the
server side of the stdio JSON-RPC 2.0 protocol and is pure-function friendly, so
it can be driven in-process by a :class:`MemoryTransport` in tests. ``serve_stdio``
is the production loop that reads framed messages from stdin and writes framed
responses to stdout (the ``baize mcp server`` command).

The server is an ACL (anti-corruption layer): external clients only ever see
MCP-shaped tool schemas; the core runtime's tool execution semantics stay
encapsulated behind ``ToolRegistry.execute``.
"""
from __future__ import annotations

import json
import sys
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    def __init__(self, registry, name: str = "baize",
                 version: str = "25.0.0") -> None:
        self.registry = registry
        self.name = name
        self.version = version

    # -- protocol handler (testable, transport-agnostic) ------------------
    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        msg_id = message.get("id")
        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.name,
                                   "version": self.version},
                },
            }
        if method == "notifications/initialized":
            return None  # notification: no response
        if method == "tools/list":
            tools = []
            for schema in self.registry.schemas():
                fn = schema.get("function", schema)
                tools.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "inputSchema": fn.get("parameters",
                                          {"type": "object", "properties": {}}),
                })
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"tools": tools}}
        if method == "tools/call":
            params = message.get("params", {})
            name = params.get("name", "")
            arguments = params.get("arguments", {}) or {}
            try:
                observation = self.registry.execute(name, arguments)
            except Exception as exc:  # defensive: never crash the server loop
                observation = f"ERROR: {exc}"
            is_error = isinstance(observation, str) and observation.startswith("ERROR")
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": str(observation)}],
                    "isError": is_error,
                },
            }
        # Unknown method -> JSON-RPC error (fail-closed, not silent).
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601,
                          "message": f"method not found: {method}"}}

    # -- production stdio loop --------------------------------------------
    def serve_stdio(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        buf = bytearray()
        while True:
            try:
                message, buf = self._read_frame(stdin, buf)
            except EOFError:
                return
            if message is None:
                continue
            response = self.handle(message)
            if response is None:
                continue
            self._write_frame(stdout, response)

    # -- minimal framing (mirrors transport.py, server side) --------------
    @staticmethod
    def _read_frame(stream, buf: bytearray) -> tuple[dict | None, bytearray]:
        # Read one byte at a time. On Windows named pipes a single read(N)
        # blocks until N bytes arrive (or EOF), deadlocking streaming framing;
        # a byte accumulator returns as soon as each byte is available.
        while b"\r\n\r\n" not in buf:
            b = stream.read(1)
            if not b:
                raise EOFError
            buf.extend(b)
        header_blob, _, rest = bytes(buf).partition(b"\r\n\r\n")
        length = 0
        for line in header_blob.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        # The header and body may arrive in separate pipe reads.  Keep
        # accumulating until the advertised byte length is available instead
        # of treating the header remainder as a complete body.
        while len(rest) < length:
            b = stream.read(1)
            if not b:
                raise EOFError
            rest += b
        body = rest[:length]
        leftover = bytearray(rest[length:])
        obj = json.loads(body.decode("utf-8"))
        return obj, leftover

    @staticmethod
    def _write_frame(stdout, obj: dict) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        stdout.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8"))
        stdout.write(payload)
        stdout.flush()
