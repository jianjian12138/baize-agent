"""V49.0.0 Zenith tests: interactive PTY/stdin send_input, streaming tool output, CDP ARIA @eN refs, LLM retry & thinking replay, and MCP Streamable HTTP/SSE + resources/prompts."""
from __future__ import annotations

import base64
import hashlib
import http.server
import io
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from baize.core.llm import (
    LLMClient,
    LLMError,
    ModelSpec,
    _anthropic_parse,
    _anthropic_request,
    _compute_retry_delay,
    _is_retryable_error,
    _parse_retry_after,
)
from baize.core.runtime_ctx import execution_context
from baize.execution import tools as tools_mod
from baize.execution.bg_proc import BackgroundProcessManager
from baize.execution.cdp_browser import InteractiveBrowserSession
from baize.ext.mcp.client import MCPClient, MCPServerSpec
from baize.ext.mcp.transport import StreamableHttpTransport


def _ws_read_client_frame(conn: socket.socket) -> str:
    hdr = conn.recv(2)
    if len(hdr) < 2:
        return ""
    masked = bool(hdr[1] & 0x80)
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", conn.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", conn.recv(8))[0]
    mask = conn.recv(4) if masked else b""
    buf = bytearray()
    while len(buf) < length:
        chunk = conn.recv(length - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    if masked:
        buf = bytearray(b ^ mask[i % 4] for i, b in enumerate(buf))
    return buf.decode("utf-8", errors="replace")


def _ws_send_server_text(conn: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    n = len(payload)
    if n < 126:
        hdr = bytes([0x81, n])
    elif n < 65536:
        hdr = bytes([0x81, 126]) + struct.pack("!H", n)
    else:
        hdr = bytes([0x81, 127]) + struct.pack("!Q", n)
    conn.sendall(hdr + payload)


class TestV49PtyAriaRetryAndMcpHttp(unittest.TestCase):
    def test_bg_proc_send_input_pipe_and_tool_registration(self) -> None:
        self.assertIn("bash_bg_send_input", tools_mod.default_registry().names())
        mgr = BackgroundProcessManager()
        with tempfile.TemporaryDirectory() as d:
            cmd = f"{sys.executable} -u -c \"import sys; line = sys.stdin.readline().strip(); print('ECHO:' + line, flush=True)\""
            info = mgr.start(cmd, cwd=d, use_pty=False)
            pid = info["proc_id"]
            try:
                res = mgr.send_input(pid, "hello-zenith", wait_ms=250)
                self.assertTrue(res["ok"])
                out_all = res.get("output", "")
                if "ECHO:hello-zenith" not in out_all:
                    time.sleep(0.2)
                    out_all += mgr.read_output(pid).get("output", "")
                self.assertIn("ECHO:hello-zenith", out_all)
            finally:
                mgr.stop(pid)

    def test_streaming_tool_output_emits_live_chunks(self) -> None:
        chunks: list[tuple[str, str, str]] = []
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d).resolve()
            env_patch = {"BAIZE_SANDBOX_ENABLED": "0", "BAIZE_SANDBOX_MODE": "off", "BAIZE_STREAM_TOOL_OUTPUT": "1"}
            with mock.patch.dict(os.environ, env_patch):
                with execution_context(workspace=ws, session_id="sess-stream", on_tool_output=lambda t, s, c: chunks.append((t, s, c))):
                    out = tools_mod._tool_bash(
                        f"{sys.executable} -u -c \"print('line-one', flush=True); print('line-two', flush=True)\""
                    )
            self.assertIn("line-one", out)
            self.assertIn("line-two", out)
            combined = "".join(c for _, _, c in chunks)
            self.assertIn("line-one", combined)
            self.assertIn("line-two", combined)
            self.assertTrue(all(t == "bash" for t, _, _ in chunks))

    def test_cdp_aria_snapshot_and_at_ref_click_fill_over_local_websocket(self) -> None:
        calls: list[tuple[str, dict]] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(1)

        def ws_server() -> None:
            conn, _ = srv.accept()
            with conn:
                req_raw = conn.recv(4096).decode("utf-8", errors="replace")
                key = ""
                for line in req_raw.splitlines():
                    if line.lower().startswith("sec-websocket-key:"):
                        key = line.split(":", 1)[1].strip()
                accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                conn.sendall((
                    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode())
                while True:
                    msg_txt = _ws_read_client_frame(conn)
                    if not msg_txt:
                        break
                    msg = json.loads(msg_txt)
                    mid, method, params = msg["id"], msg["method"], msg.get("params") or {}
                    calls.append((method, params))
                    if method == "Accessibility.getFullAXTree":
                        res = {
                            "nodes": [
                                {"nodeId": "1", "role": {"value": "textbox"}, "name": {"value": "Email"}, "backendDOMNodeId": 101, "ignored": False},
                                {"nodeId": "2", "role": {"value": "button"}, "name": {"value": "Sign In"}, "backendDOMNodeId": 102, "ignored": False},
                            ]
                        }
                    elif method == "DOM.resolveNode":
                        res = {"object": {"objectId": f"obj-{params.get('backendNodeId')}"}}
                    elif method == "Runtime.callFunctionOn":
                        if params.get("objectId") == "obj-101":
                            res = {"result": {"value": {"found": True, "ref": "e1", "tag": "INPUT", "length": 17}}}
                        else:
                            res = {"result": {"value": {"found": True, "ref": "e2", "tag": "BUTTON", "text": "Sign In"}}}
                    else:
                        res = {}
                    _ws_send_server_text(conn, json.dumps({"id": mid, "result": res}))

        th = threading.Thread(target=ws_server, daemon=True)
        th.start()
        try:
            sess = InteractiveBrowserSession("aria-test", ws_url=f"ws://127.0.0.1:{port}/devtools/page/1", timeout=5.0)
            try:
                snap = sess.execute("aria_snapshot")
                self.assertTrue(snap["ok"])
                self.assertEqual(snap["node_count"], 2)
                self.assertIn('[e1] textbox "Email"', snap["tree"])
                self.assertIn('[e2] button "Sign In"', snap["tree"])

                fill_res = sess.execute("fill", selector="@e1", value="alice@example.com")
                self.assertTrue(fill_res["ok"])
                self.assertEqual(fill_res["result"].get("length"), 17)

                click_res = sess.execute("click", selector="@e2")
                self.assertTrue(click_res["ok"])
                self.assertEqual(click_res["element"].get("tag"), "BUTTON")

                resolved_ids = [p.get("backendNodeId") for m, p in calls if m == "DOM.resolveNode"]
                self.assertEqual(resolved_ids, [101, 102])
            finally:
                sess.close()
        finally:
            srv.close()

    def test_llm_retry_after_fail_fast_4xx_and_anthropic_thinking_replay(self) -> None:
        hdrs = Message()
        hdrs["Retry-After"] = "2.5"
        err_429 = urllib.error.HTTPError("https://api.example.com", 429, "Too Many Requests", hdrs, io.BytesIO(b""))
        err_400 = urllib.error.HTTPError("https://api.example.com", 400, "Bad Request", Message(), io.BytesIO(b""))
        self.assertEqual(_parse_retry_after(err_429), 2.5)
        self.assertTrue(_is_retryable_error(err_429))
        self.assertFalse(_is_retryable_error(err_400))
        self.assertEqual(_compute_retry_delay(0, 1.0, err_429), 2.5)

        attempts = {"count": 0}
        def fail_400(url, headers, payload):
            attempts["count"] += 1
            raise urllib.error.HTTPError(url, 400, "Bad Request", Message(), io.BytesIO(b"bad"))

        cfg = {
            "BAIZE_MODEL_NAME": "test-model",
            "BAIZE_MODEL_BASE_URL": "https://api.example.com/v1",
            "BAIZE_MODEL_API_KEY": "sk-test",
            "BAIZE_LLM_RETRY_MAX": "3",
            "BAIZE_LLM_RETRY_BASE_S": "0.05",
        }
        cli = LLMClient(cfg=cfg, transport=fail_400)
        with self.assertRaises(LLMError):
            cli.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(attempts["count"], 1)

        attempts2 = {"count": 0}
        def retry_429_then_ok(url, headers, payload):
            attempts2["count"] += 1
            if attempts2["count"] == 1:
                h = Message()
                h["Retry-After"] = "0.01"
                raise urllib.error.HTTPError(url, 429, "Rate Limited", h, io.BytesIO(b"rate"))
            return {"choices": [{"message": {"role": "assistant", "content": "recovered"}}]}

        cli2 = LLMClient(cfg=cfg, transport=retry_429_then_ok)
        out = cli2.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(out["content"], "recovered")
        self.assertEqual(attempts2["count"], 2)

        raw_anth = {
            "content": [
                {"type": "thinking", "thinking": "Step 1: inspect code", "signature": "sig-abc"},
                {"type": "redacted_thinking", "data": "opaque-xyz"},
                {"type": "text", "text": "Running check"},
                {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a.py"}},
            ]
        }
        parsed = _anthropic_parse(raw_anth)
        self.assertEqual(parsed["content"], "Running check")
        self.assertEqual(parsed["reasoning_content"], "Step 1: inspect code")
        self.assertEqual(len(parsed["thinking_blocks"]), 2)

        spec = ModelSpec(name="claude-3-7-sonnet", base_url="https://api.anthropic.com", provider="anthropic")
        req_body = _anthropic_request(spec, [{"role": "user", "content": "go"}, parsed], None, None)
        asst_blocks = req_body["messages"][1]["content"]
        self.assertEqual(asst_blocks[0]["type"], "thinking")
        self.assertEqual(asst_blocks[0]["signature"], "sig-abc")
        self.assertEqual(asst_blocks[1]["type"], "redacted_thinking")
        self.assertEqual(asst_blocks[2]["type"], "text")
        self.assertEqual(asst_blocks[3]["type"], "tool_use")

    def test_mcp_streamable_http_sse_resources_and_prompts(self) -> None:
        seen_sessions: list[str] = []

        class MCPHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                sid = self.headers.get("Mcp-Session-Id", "")
                if sid:
                    seen_sessions.append(sid)
                method, mid = body.get("method", ""), body.get("id")
                if method == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    raw = json.dumps({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {}}}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Mcp-Session-Id", "mcp-sess-v49")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if method == "tools/list":
                    resp = {"jsonrpc": "2.0", "id": mid, "result": {"tools": [{"name": "ping", "description": "Ping", "inputSchema": {"type": "object", "properties": {}}}]}}
                    sse = f"event: message\ndata: {json.dumps(resp)}\n\n".encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(sse)))
                    self.end_headers()
                    self.wfile.write(sse)
                    return
                if method == "tools/call":
                    resp = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "pong-via-sse"}]}}
                    sse = f"data: {json.dumps(resp)}\n\n".encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(sse)))
                    self.end_headers()
                    self.wfile.write(sse)
                    return
                if method == "resources/list":
                    resp = {"jsonrpc": "2.0", "id": mid, "result": {"resources": [{"uri": "file:///spec.md", "name": "spec", "mimeType": "text/markdown"}]}}
                elif method == "resources/read":
                    resp = {"jsonrpc": "2.0", "id": mid, "result": {"contents": [{"uri": "file:///spec.md", "text": "# Spec Content"}]}}
                elif method == "prompts/list":
                    resp = {"jsonrpc": "2.0", "id": mid, "result": {"prompts": [{"name": "review", "description": "Code review", "arguments": [{"name": "lang"}]}]}}
                elif method == "prompts/get":
                    resp = {"jsonrpc": "2.0", "id": mid, "result": {"messages": [{"role": "user", "content": {"type": "text", "text": "Review python code"}}]}}
                else:
                    resp = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "not found"}}
                raw = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MCPHandler)
        port = httpd.server_address[1]
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        try:
            spec = MCPServerSpec(name="remote_srv", url=f"http://127.0.0.1:{port}/mcp", transport_type="http")
            client = MCPClient(spec)
            self.assertIsInstance(client.transport, StreamableHttpTransport)
            client.connect()
            self.assertEqual([t.name for t in client.list_tools()], ["ping"])
            self.assertEqual(client.call_tool("ping", {}), "pong-via-sse")
            self.assertEqual(client.list_resources()[0].uri, "file:///spec.md")
            self.assertEqual(client.read_resource("file:///spec.md"), "# Spec Content")
            self.assertEqual(client.list_prompts()[0].name, "review")
            self.assertEqual(client.get_prompt("review", {"lang": "python"})["messages"][0]["content"]["text"], "Review python code")
            self.assertTrue(len(seen_sessions) >= 4 and all(s == "mcp-sess-v49" for s in seen_sessions))
            client.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
