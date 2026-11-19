"""End-to-end tests for V42 GitWorktreePool and pure-stdlib CDP browser verification."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from baize.execution.browser_verify import verify_url_with_cdp
from baize.execution.cdp_browser import CDPBrowserClient, CDPUnavailableError
from baize.execution.worktree import GitWorktreePool


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def _init_temp_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@baize.local")
    _git(root, "config", "user.name", "Baize Test")
    (root / "README.md").write_text("line1\nline2\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "initial")


class _MockCDPWebSocketServer:
    """Minimal RFC 6455 WebSocket server simulating Chrome DevTools Protocol."""

    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(5)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/devtools/page/mock"

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def _send_text(self, conn: socket.socket, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        n = len(raw)
        if n < 126:
            hdr = bytes([0x81, n])
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x81, 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x81, 127, n)
        conn.sendall(hdr + raw)

    def _recv_exact(self, conn: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise EOFError("closed")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_frame(self, conn: socket.socket) -> tuple[int, bytes]:
        b1, b2 = self._recv_exact(conn, 2)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(conn, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(conn, 8))[0]
        mask = self._recv_exact(conn, 4) if masked else b""
        data = bytearray(self._recv_exact(conn, length))
        if masked:
            for i in range(length):
                data[i] ^= mask[i % 4]
        return opcode, bytes(data)

    def _serve(self) -> None:
        self._sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(3.0)
                req = b""
                while b"\r\n\r\n" not in req:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    req += chunk
                key = ""
                for line in req.decode("utf-8", errors="replace").split("\r\n"):
                    if line.lower().startswith("sec-websocket-key:"):
                        key = line.split(":", 1)[1].strip()
                accept = base64.b64encode(
                    hashlib.sha1((key + self.GUID).encode("ascii")).digest()
                ).decode("ascii")
                resp = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode("ascii")
                conn.sendall(resp)
                while not self._stop.is_set():
                    opcode, data = self._recv_frame(conn)
                    if opcode == 0x8:
                        break
                    if opcode != 0x1:
                        continue
                    msg = json.loads(data.decode("utf-8"))
                    mid = msg.get("id")
                    method = msg.get("method", "")
                    if method == "Page.navigate":
                        self._send_text(conn, {
                            "method": "Runtime.consoleAPICalled",
                            "params": {
                                "type": "error",
                                "args": [{"value": "Uncaught mock console error"}],
                            },
                        })
                        self._send_text(conn, {
                            "method": "Runtime.exceptionThrown",
                            "params": {
                                "exceptionDetails": {"text": "ReferenceError: boom"},
                            },
                        })
                        self._send_text(conn, {"id": mid, "result": {"frameId": "f1"}})
                        self._send_text(conn, {"method": "Page.loadEventFired", "params": {"timestamp": 1.0}})
                    elif method == "Runtime.evaluate":
                        expr = (msg.get("params") or {}).get("expression", "")
                        val = "Mock Helios Page" if "title" in expr else "Hello Helios DOM"
                        self._send_text(conn, {
                            "id": mid,
                            "result": {
                                "result": {
                                    "type": "string",
                                    "value": val,
                                }
                            },
                        })
                    elif method == "Page.captureScreenshot":
                        png_bytes = b"\x89PNG\r\n\x1a\nMOCKPNG"
                        self._send_text(conn, {
                            "id": mid,
                            "result": {"data": base64.b64encode(png_bytes).decode("ascii")},
                        })
                    else:
                        self._send_text(conn, {"id": mid, "result": {}})
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass


class TestV42WorktreeAndCDP(unittest.TestCase):
    def test_parallel_worktrees_disjoint_merge_and_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            _init_temp_repo(repo)
            pool = GitWorktreePool(repo)
            self.assertTrue(pool.is_git_repo())

            e1 = pool.create("t1", label="alpha")
            e2 = pool.create("t2", label="beta")
            self.assertTrue(Path(e1.worktree_path).exists())
            self.assertTrue(Path(e2.worktree_path).exists())

            (Path(e1.worktree_path) / "alpha.txt").write_text("from t1\n", encoding="utf-8")
            (Path(e2.worktree_path) / "beta.txt").write_text("from t2\n", encoding="utf-8")

            c1 = pool.commit_worktree_changes(e1.worktree_id, "add alpha")
            c2 = pool.commit_worktree_changes(e2.worktree_id, "add beta")
            self.assertTrue(c1["ok"] and c1["committed"])
            self.assertTrue(c2["ok"] and c2["committed"])

            m1 = pool.merge_verified(e1.worktree_id, auto_cleanup=True)
            m2 = pool.merge_verified(e2.worktree_id, auto_cleanup=True)
            self.assertTrue(m1["ok"], m1)
            self.assertTrue(m2["ok"], m2)
            self.assertEqual((repo / "alpha.txt").read_text(encoding="utf-8"), "from t1\n")
            self.assertEqual((repo / "beta.txt").read_text(encoding="utf-8"), "from t2\n")
            self.assertFalse(Path(e1.worktree_path).exists())
            self.assertFalse(Path(e2.worktree_path).exists())

    def test_worktree_merge_conflict_aborts_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            _init_temp_repo(repo)
            pool = GitWorktreePool(repo)

            e1 = pool.create("c1", label="left")
            e2 = pool.create("c2", label="right")
            (Path(e1.worktree_path) / "README.md").write_text("LEFT CHANGE\nline2\n", encoding="utf-8")
            (Path(e2.worktree_path) / "README.md").write_text("RIGHT CHANGE\nline2\n", encoding="utf-8")
            pool.commit_worktree_changes(e1.worktree_id, "left edit")
            pool.commit_worktree_changes(e2.worktree_id, "right edit")

            m1 = pool.merge_verified(e1.worktree_id, auto_cleanup=True)
            self.assertTrue(m1["ok"], m1)
            m2 = pool.merge_verified(e2.worktree_id, auto_cleanup=False)
            self.assertFalse(m2["ok"])
            self.assertEqual(m2["status"], "conflict")
            # Main working tree must be cleanly aborted (no conflict markers left behind)
            status_out = _git(repo, "status", "--porcelain").stdout.strip()
            self.assertEqual(status_out, "")
            self.assertEqual((repo / "README.md").read_text(encoding="utf-8"), "LEFT CHANGE\nline2\n")
            res = pool.cleanup(e2.worktree_id)
            self.assertTrue(res["ok"])

    def test_rfc6455_websocket_and_cdp_mock_server(self):
        srv = _MockCDPWebSocketServer()
        try:
            with tempfile.TemporaryDirectory() as td:
                shot = Path(td) / "screen.png"
                res = verify_url_with_cdp(
                    "http://127.0.0.1:8787/",
                    ws_url=srv.ws_url,
                    screenshot_path=str(shot),
                    timeout=5.0,
                )
                self.assertEqual(res["mode"], "cdp")
                self.assertEqual(res["title"], "Mock Helios Page")
                self.assertTrue(any("mock console error" in e for e in res["console_errors"]))
                self.assertTrue(any("ReferenceError: boom" in e for e in res["exceptions"]))
                self.assertTrue(shot.exists())
                self.assertTrue(shot.read_bytes().startswith(b"\x89PNG"))
        finally:
            srv.close()

    def test_cdp_honest_unavailable_fallback(self):
        prev = os.environ.get("BAIZE_CDP_BINARY")
        os.environ["BAIZE_CDP_BINARY"] = "/nonexistent/chrome-bin-v42"
        try:
            res = verify_url_with_cdp(
                "http://127.0.0.1:8787/",
                browser_binary="/nonexistent/chrome-bin-v42",
                timeout=2.0,
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["mode"], "unavailable")
            self.assertIn("error", res)
        finally:
            if prev is None:
                os.environ.pop("BAIZE_CDP_BINARY", None)
            else:
                os.environ["BAIZE_CDP_BINARY"] = prev


if __name__ == "__main__":
    unittest.main()
