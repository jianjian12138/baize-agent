"""V47.0.0 Horizon tests: interactive CDP browser E2E pool & mobile simulator bridge."""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from baize.execution.cdp_browser import BrowserSessionPool
from baize.execution.mobile_bridge import (
    MobileDevice,
    list_mobile_devices,
    mobile_action,
    verify_mobile_app,
)
from baize.execution.tools import default_registry


_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_TINY_PNG_B64 = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00"
    b"\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")


def _ws_recv_frame(conn: socket.socket) -> tuple[int, bytes] | None:
    def _exact(n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return b""
            buf.extend(chunk)
        return bytes(buf)

    hdr = _exact(2)
    if len(hdr) < 2:
        return None
    opcode = hdr[0] & 0x0F
    masked = bool(hdr[1] & 0x80)
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _exact(8))[0]
    mask = _exact(4) if masked else b""
    payload = _exact(length)
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _ws_send_text(conn: socket.socket, text: str) -> None:
    data = text.encode("utf-8")
    n = len(data)
    if n < 126:
        hdr = bytes([0x81, n])
    elif n < 65536:
        hdr = bytes([0x81, 126]) + struct.pack("!H", n)
    else:
        hdr = bytes([0x81, 127]) + struct.pack("!Q", n)
    conn.sendall(hdr + data)


class _MockCDPServer:
    """Minimal real RFC-6455 WebSocket mock CDP server for stateful E2E testing."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(4)
        self.sock.settimeout(0.5)
        self.stop_evt = threading.Event()
        self.methods_seen: list[str] = []
        self.state = {"url": "about:blank", "filled": "", "clicked": False}
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/devtools/page/mock1"

    def _serve(self) -> None:
        while not self.stop_evt.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            req = conn.recv(4096).decode("utf-8", errors="replace")
            key = ""
            for line in req.splitlines():
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
                    break
            accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
            resp = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            )
            conn.sendall(resp.encode("ascii"))
            while not self.stop_evt.is_set():
                frame = _ws_recv_frame(conn)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode != 0x1:
                    continue
                msg = json.loads(payload.decode("utf-8"))
                cid = msg.get("id")
                method = msg.get("method", "")
                params = msg.get("params") or {}
                self.methods_seen.append(method)
                result: dict = {}
                if method == "Page.navigate":
                    self.state["url"] = params.get("url", "")
                    result = {"frameId": "f1"}
                elif method == "Page.captureScreenshot":
                    result = {"data": _TINY_PNG_B64}
                elif method == "Runtime.evaluate":
                    expr = str(params.get("expression", ""))
                    if "document.title" in expr and "innerText" in expr:
                        val = {
                            "url": self.state["url"],
                            "title": "Kitchen Demo",
                            "text": f"filled={self.state['filled']} clicked={self.state['clicked']}",
                            "interactive_count": 3,
                        }
                    elif "value" in expr and "dispatchEvent" in expr:
                        self.state["filled"] = "ok"
                        val = {"found": True, "tag": "INPUT", "length": 16}
                    elif ".click()" in expr:
                        self.state["clicked"] = True
                        val = {"found": True, "tag": "BUTTON", "text": "Save"}
                    elif "querySelector" in expr:
                        val = True
                    elif "1 + 1 === 2" in expr:
                        val = True
                    else:
                        val = {"ok": True}
                    result = {"result": {"type": "object", "value": val}}
                _ws_send_text(conn, json.dumps({"id": cid, "result": result}))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def close(self) -> None:
        self.stop_evt.set()
        try:
            self.sock.close()
        except Exception:
            pass


class TestV47InteractiveBrowserE2E(unittest.TestCase):
    def test_stateful_session_all_8_actions(self):
        srv = _MockCDPServer()
        pool = BrowserSessionPool(idle_timeout=120.0)
        try:
            r_nav = pool.run_action("navigate", session_id="e2e", url="http://127.0.0.1:3000/login", ws_url=srv.ws_url)
            self.assertTrue(r_nav["ok"])
            self.assertEqual(r_nav["url"], "http://127.0.0.1:3000/login")

            r_fill = pool.run_action("fill", session_id="e2e", selector="#email", value="chef@example.com", ws_url=srv.ws_url)
            self.assertTrue(r_fill["ok"])

            r_click = pool.run_action("click", session_id="e2e", selector="#submit", ws_url=srv.ws_url)
            self.assertTrue(r_click["ok"])

            r_wait = pool.run_action("wait", session_id="e2e", selector="#done", timeout=2.0, ws_url=srv.ws_url)
            self.assertTrue(r_wait["ok"])

            r_assert = pool.run_action("eval_assert", session_id="e2e", expression="1 + 1 === 2", ws_url=srv.ws_url)
            self.assertTrue(r_assert["ok"])
            self.assertTrue(r_assert["value"])

            r_snap = pool.run_action("snapshot", session_id="e2e", ws_url=srv.ws_url)
            self.assertTrue(r_snap["ok"])
            self.assertEqual(r_snap["page"]["title"], "Kitchen Demo")
            self.assertIn("filled=ok", r_snap["page"]["text"])

            r_shot = pool.run_action("screenshot", session_id="e2e", ws_url=srv.ws_url)
            self.assertTrue(r_shot["ok"])
            self.assertTrue(Path(r_shot["screenshot_path"]).exists())

            st = pool.status()
            self.assertEqual(st["active_count"], 1)

            r_close = pool.run_action("close", session_id="e2e")
            self.assertTrue(r_close["ok"])
            self.assertEqual(pool.status()["active_count"], 0)
        finally:
            pool.close_all()
            srv.close()

    def test_egress_allowlist_blocks_disallowed_navigate(self):
        pool = BrowserSessionPool()
        try:
            cfg = {"BAIZE_EGRESS_ALLOWLIST": "127.0.0.1,localhost"}
            res = pool.run_action("navigate", session_id="egress", url="https://evil.example.org/phish", cfg=cfg)
            self.assertFalse(res["ok"])
            self.assertIn("egress", res.get("error", "").lower())
        finally:
            pool.close_all()

    def test_tools_registered_and_mutating(self):
        reg = default_registry()
        names = set(reg.names())
        self.assertIn("browser_action", names)
        self.assertIn("mobile_verify", names)
        self.assertIn("compose_stack", names)
        from baize.core.agent import READONLY_TOOLS
        self.assertNotIn("browser_action", READONLY_TOOLS)
        self.assertNotIn("mobile_verify", READONLY_TOOLS)
        self.assertNotIn("compose_stack", READONLY_TOOLS)


class TestV47MobileBridge(unittest.TestCase):
    def test_discover_android_and_ios_devices_mocked(self):
        adb_out = (
            "List of devices attached\n"
            "emulator-5554          device product:sdk_gphone64 model:Pixel_7 device:emu64\n"
            "R5CR12345              offline model:Galaxy_S23\n"
        )
        simctl_out = json.dumps({
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-17-5": [
                    {"udid": "IOS-UDID-1", "name": "iPhone 15 Pro", "state": "Booted"}
                ]
            }
        })

        def fake_which(bin_name: str):
            if bin_name == "adb":
                return "/usr/bin/adb"
            if bin_name == "xcrun":
                return "/usr/bin/xcrun"
            return None

        def fake_run(argv, **kwargs):
            cp = mock.Mock()
            cp.returncode = 0
            cp.stdout = adb_out if "adb" in argv[0] else simctl_out
            cp.stderr = ""
            return cp

        with mock.patch("baize.execution.mobile_bridge.shutil.which", side_effect=fake_which), \
             mock.patch("baize.execution.mobile_bridge._run_cmd", side_effect=fake_run):
            info = list_mobile_devices()
        devs = info["devices"]
        self.assertEqual(info["online_count"], 2)
        plats = {d["platform"]: d for d in devs if d["state"] in ("device", "booted")}
        self.assertIn("android", plats)
        self.assertIn("ios", plats)
        self.assertTrue(plats["android"]["is_emulator"])
        self.assertEqual(plats["android"]["device_id"], "emulator-5554")
        self.assertEqual(plats["ios"]["device_id"], "IOS-UDID-1")

    def test_mobile_action_android_tap_and_screenshot(self):
        fake_dev = MobileDevice(platform="android", device_id="emulator-5554", name="Pixel_7", state="device", is_emulator=True)

        def fake_run(argv, **kwargs):
            cp = mock.Mock()
            cp.returncode = 0
            cp.stdout = "OK\n"
            cp.stderr = ""
            return cp

        def fake_sub_run(argv, **kwargs):
            cp = mock.Mock()
            cp.returncode = 0
            cp.stdout = base64.b64decode(_TINY_PNG_B64)
            cp.stderr = b""
            return cp

        with mock.patch("baize.execution.mobile_bridge._select_device", return_value=fake_dev), \
             mock.patch("baize.execution.mobile_bridge.shutil.which", return_value="/usr/bin/adb"), \
             mock.patch("baize.execution.mobile_bridge._run_cmd", side_effect=fake_run), \
             mock.patch("baize.execution.mobile_bridge.subprocess.run", side_effect=fake_sub_run):
            r_tap = mobile_action("tap", device_id="emulator-5554", x=120, y=340)
            self.assertTrue(r_tap["ok"])
            r_shot = mobile_action("screenshot", device_id="emulator-5554")
            self.assertTrue(r_shot["ok"])
            self.assertTrue(Path(r_shot["screenshot_path"]).exists())

    def test_verify_mobile_honest_degradation_unit_test_and_web_preview(self):
        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><head><title>Recipe App</title></head><body><h1>Recipes</h1></body></html>")

            def log_message(self, fmt, *args):
                return

        httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
                (Path(td) / "test_app.py").write_text(
                    "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertEqual(2+2, 4)\n",
                    encoding="utf-8",
                )
                with mock.patch("baize.execution.mobile_bridge._select_device", return_value=None):
                    rep = verify_mobile_app(
                        workspace=td,
                        fallback_web_url=f"http://127.0.0.1:{port}/",
                        check_visual=False,
                    )
            self.assertTrue(rep.degraded)
            self.assertEqual(rep.mode, "degraded-unit-and-web")
            self.assertTrue(rep.unit_test_ok)
            self.assertIsNotNone(rep.web_preview_report)
            self.assertTrue(any("degraded" in n.lower() or "no android" in n.lower() for n in rep.notes))
            self.assertIn("DEGRADED", rep.format_for_agent())
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
