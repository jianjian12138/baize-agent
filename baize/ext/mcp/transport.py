"""MCP transport — pure-stdlib stdio JSON-RPC 2.0 with Content-Length framing.

This module is part of ``baize.ext.mcp`` and is ONLY imported lazily by the
core runtime (via ``baize.tools.register_mcp_client``), never at module top
level. That keeps the zero-dependency red line (A) intact: the core ``baize/``
package never imports ``baize.ext``.

Protocol reference: Model Context Protocol 2024-11-05 (stdio transport).
The wire format is newline-free: each message is ``Content-Length: N\r\n\r\n``
followed by exactly N bytes of UTF-8 JSON. We deliberately use Content-Length
(not newline-delimited) because the MCP spec mandates it — a server that expects
newline framing will silently hang, which is exactly the failure mode the
expert review (D8 §P2) warned about.
"""
from __future__ import annotations

import json
import subprocess
from typing import Callable

log: Callable[[str], None] | None = None  # optional logger; patched by caller


class JsonRpcError(RuntimeError):
    """Raised when an MCP peer returns a JSON-RPC error object."""


class Transport:
    """Abstract stdio JSON-RPC 2.0 transport (request/response + notify)."""

    def send(self, obj: dict) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def recv(self) -> dict | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class StdioTransport(Transport):
    """Real transport: spawn an external MCP server as a subprocess and frame
    messages over its stdin/stdout pipes (pure stdlib ``subprocess``)."""

    def __init__(self, command: str, args: list[str] | None = None,
                 env: dict | None = None, timeout: float = 30.0):
        self.timeout = timeout
        full = [command, *(args or [])]
        self.proc = subprocess.Popen(
            full, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, bufsize=0,
        )
        self._out = self.proc.stdout
        self._buf = b""

    # -- low-level framing ------------------------------------------------
    def _write_frame(self, payload: bytes) -> None:
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8")
        assert self.proc.stdin is not None
        # Write header + payload in one shot, then flush. On Windows named
        # pipes a single large buffered write can partially post; loop until
        # the full frame is handed to the OS so the peer sees it atomically.
        data = header + payload
        view = memoryview(data)
        while view:
            sent = self.proc.stdin.write(bytes(view))
            view = view[sent:]
        self.proc.stdin.flush()

    def _read_frame(self) -> dict:
        if self._out is None:
            raise JsonRpcError("transport closed")
        # Read one byte at a time and accumulate. On Windows named pipes a
        # single read(N) with N > available bytes blocks until N bytes arrive
        # (or EOF), which deadlocks streaming JSON-RPC framing. A byte-by-byte
        # accumulator returns as soon as each byte is available, on every OS.
        while b"\r\n\r\n" not in self._buf:
            b = self._out.read(1)
            if not b:
                raise JsonRpcError("MCP server closed the stream "
                                   "(handshake/response never arrived)")
            self._buf += b
        header_blob, _, rest = self._buf.partition(b"\r\n\r\n")
        length = 0
        for line in header_blob.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        self._buf = rest
        while len(self._buf) < length:
            b = self._out.read(1)
            if not b:
                raise JsonRpcError("MCP frame truncated")
            self._buf += b
        body = self._buf[:length]
        self._buf = self._buf[length:]
        return json.loads(body.decode("utf-8"))

    # -- Transport API ----------------------------------------------------
    def send(self, obj: dict) -> None:
        self._write_frame(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def recv(self) -> dict | None:
        return self._read_frame()

    def close(self) -> None:
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


class MemoryTransport(Transport):
    """In-process transport for deterministic tests. The ``handler`` is a pure
    function ``(message: dict) -> dict | None`` that plays the server role.
    ``send`` stores the outbound message; ``recv`` invokes the handler with it.
    A notification (no ``id``) yields ``None`` so the caller can skip it.

    This is the W2 "server 暂 mock" path: no real subprocess, fully scriptable.
    """

    def __init__(self, handler: Callable[[dict], dict | None]) -> None:
        self._handler = handler
        self._last: dict | None = None
        self.closed = False

    def send(self, obj: dict) -> None:
        self._last = obj

    def recv(self) -> dict | None:
        if self._last is None:
            return None
        sent = self._last
        self._last = None
        return self._handler(sent)

    def close(self) -> None:
        self.closed = True
