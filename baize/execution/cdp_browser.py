"""V42.0.0 Helios — Pure-Stdlib RFC 6455 WebSocket & Chrome DevTools Protocol (CDP) Client.

Enables real headless browser verification (navigation, DOM extraction, Console
error capture, uncaught exception capture, and PNG screenshot capture) using ONLY
Python standard library sockets—zero Playwright/Selenium dependencies.

Honest Degradation Contract:
  When no local Chrome/Chromium/Edge binary is detected and no explicit ``ws_url``
  is supplied, raises :class:`CDPUnavailableError` cleanly instead of faking a pass.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CDPUnavailableError(RuntimeError):
    """Raised honestly when no browser binary or CDP endpoint is available."""


def find_browser_binary(override: str = "") -> str | None:
    """Locate a local Chrome, Chromium, or Edge binary, or return None."""
    if override and Path(override).is_file():
        return str(Path(override))
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for cand in candidates:
        if os.path.isabs(cand):
            if Path(cand).is_file():
                return cand
        else:
            found = shutil.which(cand)
            if found:
                return found
    return None


class SimpleWebSocketClient:
    """Minimal, RFC 6455 compliant client-side WebSocket using pure Python stdlib."""

    def __init__(self, url: str, timeout: float = 15.0) -> None:
        self.url = url
        self.timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._buf = bytearray()

    def connect(self) -> None:
        parsed = urllib.parse.urlparse(self.url)
        scheme = (parsed.scheme or "ws").lower()
        if scheme not in ("ws", "wss"):
            raise ValueError(f"Unsupported WebSocket scheme: {scheme}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        raw_sock = socket.create_connection((host, port), timeout=self.timeout)
        if scheme == "wss":
            ctx = ssl.create_default_context()
            raw_sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        raw_sock.settimeout(self.timeout)
        self._sock = raw_sock

        sec_key = base64.b64encode(os.urandom(16)).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1((sec_key + _WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self._sock.sendall(handshake)

        # Read HTTP 101 response headers
        while b"\r\n\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake closed before completion")
            self._buf.extend(chunk)
        sep = self._buf.index(b"\r\n\r\n")
        header_text = bytes(self._buf[:sep]).decode("latin-1", errors="replace")
        del self._buf[: sep + 4]
        if " 101 " not in header_text.splitlines()[0]:
            raise ConnectionError(f"WebSocket handshake rejected: {header_text.splitlines()[0]}")
        hdrs: dict[str, str] = {}
        for line in header_text.splitlines()[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                hdrs[k.strip().lower()] = v.strip()
        if hdrs.get("sec-websocket-accept") != expected_accept:
            raise ConnectionError("Invalid Sec-WebSocket-Accept header")

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        while len(self._buf) < n:
            chunk = self._sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("WebSocket connection closed")
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        assert self._sock is not None
        header = bytearray([0x80 | (opcode & 0x0F)])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask_key = os.urandom(4)
        header.extend(mask_key)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def recv_text(self, timeout: float | None = None) -> str:
        assert self._sock is not None
        if timeout is not None:
            self._sock.settimeout(timeout)
        fragments: list[bytes] = []
        while True:
            b1, b2 = self._recv_exact(2)
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask_key = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length) if length else b""
            if masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:  # Ping -> Pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # Pong
                continue
            if opcode == 0x8:  # Close
                raise ConnectionError("WebSocket closed by peer")
            fragments.append(payload)
            if fin:
                return b"".join(fragments).decode("utf-8", errors="replace")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._send_frame(0x8, b"")
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


@dataclass
class CDPVerifyResult:
    ok: bool
    url: str
    mode: str = "cdp"
    title: str = ""
    console_errors: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    dom_snippet: str = ""
    screenshot_path: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CDPBrowserClient:
    """High-level CDP verifier supporting explicit WebSocket endpoints or local Chrome."""

    def __init__(self, *, ws_url: str = "", browser_binary: str = "", timeout: float = 15.0) -> None:
        self.ws_url = ws_url.strip()
        self.browser_binary = browser_binary.strip()
        self.timeout = float(timeout)
        self._proc: subprocess.Popen | None = None
        self._user_data_dir: str = ""
        self._ws: SimpleWebSocketClient | None = None
        self._msg_id = 0
        self.console_errors: list[str] = []
        self.exceptions: list[str] = []

    def _launch_local_browser(self) -> str:
        binary = find_browser_binary(self.browser_binary)
        if not binary:
            raise CDPUnavailableError(
                "No local Chrome/Chromium/Edge binary found; set BAIZE_CDP_BINARY or install Chromium."
            )
        # Pick an ephemeral free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self._user_data_dir = tempfile.mkdtemp(prefix="baize-cdp-")
        self._proc = subprocess.Popen(
            [
                binary,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={self._user_data_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + min(self.timeout, 10.0)
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.0) as r:
                    targets = json.loads(r.read().decode("utf-8"))
                    for t in targets:
                        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                            return str(t["webSocketDebuggerUrl"])
            except Exception:
                time.sleep(0.15)
        self.close()
        raise CDPUnavailableError("Timed out waiting for headless browser DevTools endpoint")

    def connect(self) -> None:
        target_ws = self.ws_url or self._launch_local_browser()
        self._ws = SimpleWebSocketClient(target_ws, timeout=self.timeout)
        self._ws.connect()

    def send_command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("CDP client is not connected")
        self._msg_id += 1
        cid = self._msg_id
        self._ws.send_text(json.dumps({"id": cid, "method": method, "params": params or {}}))
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            raw = self._ws.recv_text(timeout=max(0.5, deadline - time.time()))
            frame = json.loads(raw)
            if "method" in frame:
                self._handle_event(frame)
                continue
            if frame.get("id") == cid:
                if "error" in frame:
                    raise RuntimeError(f"CDP error for {method}: {frame['error']}")
                return frame.get("result") or {}
        raise TimeoutError(f"CDP command timed out: {method}")

    def _handle_event(self, frame: dict[str, Any]) -> None:
        ev = frame.get("method", "")
        params = frame.get("params") or {}
        if ev == "Runtime.consoleAPICalled":
            if params.get("type") in ("error", "assert"):
                args = params.get("args") or []
                msg = " ".join(str(a.get("value") or a.get("description") or "") for a in args).strip()
                self.console_errors.append(msg or "console.error")
        elif ev == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails") or {}
            exc = details.get("exception") or {}
            self.exceptions.append(str(exc.get("description") or details.get("text") or "uncaught exception"))

    def verify_page(self, url: str, *, screenshot_path: str | Path | None = None) -> CDPVerifyResult:
        try:
            self.connect()
            self.send_command("Runtime.enable")
            self.send_command("Page.enable")
            self.send_command("Page.navigate", {"url": url})
            title_res = self.send_command("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
            dom_res = self.send_command(
                "Runtime.evaluate",
                {"expression": "document.body ? document.body.innerText.slice(0, 600) : ''", "returnByValue": True},
            )
            title = str(((title_res.get("result") or {}).get("value")) or "")
            dom_snippet = str(((dom_res.get("result") or {}).get("value")) or "")
            saved_shot = ""
            if screenshot_path:
                shot = self.send_command("Page.captureScreenshot", {"format": "png"})
                b64 = shot.get("data") or ""
                if b64:
                    sp = Path(screenshot_path)
                    sp.parent.mkdir(parents=True, exist_ok=True)
                    sp.write_bytes(base64.b64decode(b64))
                    saved_shot = str(sp)
            ok = (len(self.console_errors) == 0 and len(self.exceptions) == 0)
            return CDPVerifyResult(
                ok=ok,
                url=url,
                mode="cdp",
                title=title,
                console_errors=list(self.console_errors),
                exceptions=list(self.exceptions),
                dom_snippet=dom_snippet,
                screenshot_path=saved_shot,
            )
        finally:
            self.close()

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._user_data_dir:
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = ""
