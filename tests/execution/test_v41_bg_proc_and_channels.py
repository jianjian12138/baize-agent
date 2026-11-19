"""V41.0.0 Polaris — Background processes, bounded MEMORY.md/USER.md, and bidirectional IM gateway."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from baize.execution.bg_proc import BackgroundProcessManager
from baize.ext.channels import ChannelGateway, get_adapter, list_channels
from baize.interfaces.server.jobs import JobStore
from baize.knowledge.memory import BoundedMemoryStore


class TestV41BgProcMemoryAndChannels(unittest.TestCase):
    def test_bg_proc_start_read_and_stop(self):
        mgr = BackgroundProcessManager()
        try:
            cmd = f'"{sys.executable}" -u -c "import time; print(\'BG_READY\', flush=True); time.sleep(30)"'
            started = mgr.start(cmd, use_pty=False)
            self.assertTrue(started["ok"])
            pid_key = started["proc_id"]

            output = ""
            for _ in range(30):
                out = mgr.read_output(pid_key)
                output += out.get("output", "")
                if "BG_READY" in output:
                    break
                time.sleep(0.05)
            self.assertIn("BG_READY", output)
            self.assertGreaterEqual(mgr.active_count(), 1)

            stopped = mgr.stop(pid_key)
            self.assertTrue(stopped["ok"])
            self.assertEqual(mgr.active_count(), 0)
        finally:
            mgr.stop_all()

    def test_bounded_memory_store_enforces_caps_and_atomic_ops(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {
                "BAIZE_PERSISTENCE_DIR": td,
                "BAIZE_MEMORY_MAX_CHARS": "120",
                "BAIZE_USER_PROFILE_MAX_CHARS": "80",
            }
            store = BoundedMemoryStore(cfg)
            r1 = store.update("memory", "add", "Always run unit tests before commit")
            self.assertTrue(r1["ok"], r1)
            r2 = store.update("user", "add", "Prefers concise Chinese summaries")
            self.assertTrue(r2["ok"], r2)
            h1 = store.revision_hash()

            # Over-budget write is gracefully bounded to max_memory_chars without unbounded growth
            for i in range(6):
                res_m = store.update("memory", "add", f"rule_{i}: " + ("x" * 45))
            self.assertTrue(res_m["ok"])
            self.assertTrue(res_m["truncated"])
            self.assertLessEqual(len(store.read("memory")), store.max_memory_chars)
            store.update("memory", "set", "- Always run unit tests before commit")

            # Replace updates content and revision hash
            rep = store.update(
                "memory",
                "replace",
                "Run compileall + unittest",
                target="Always run unit tests before commit",
            )
            self.assertTrue(rep["ok"], rep)
            h2 = store.revision_hash()
            self.assertNotEqual(h1, h2)

            snap = store.render_prefix_snapshot()
            self.assertIn("Run compileall + unittest", snap)
            self.assertIn("Prefers concise Chinese summaries", snap)

            rem = store.update("user", "remove", target="concise Chinese")
            self.assertTrue(rem["ok"], rem)
            self.assertNotIn("concise Chinese", store.read("user"))
            st = store.stats()
            self.assertEqual(st["memory"]["limit"], 200)

    def test_channels_verification_allowlist_and_real_outbound_http(self):
        received_outbound: list[dict] = []

        class _Hook(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                received_outbound.append({"path": self.path, "body": body})
                resp = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, fmt, *args):
                return

        srv = HTTPServer(("127.0.0.1", 0), _Hook)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                cfg = {
                    "BAIZE_PERSISTENCE_DIR": td,
                    "BAIZE_CHANNEL_ALLOWLIST": "u_allowed,tg_42",
                    "BAIZE_SLACK_SIGNING_SECRET": "slack_secret_test",
                    "BAIZE_TELEGRAM_SECRET_TOKEN": "tg_secret_tok",
                    "BAIZE_DINGTALK_SECRET": "dt_secret_test",
                    "BAIZE_FEISHU_WEBHOOK_URL": f"http://127.0.0.1:{port}/feishu",
                }
                chans = list_channels(cfg)
                self.assertEqual({c["channel"] for c in chans}, {"feishu", "dingtalk", "telegram", "slack"})

                store = JobStore(str(Path(td) / "jobs.sqlite3"), max_workers=1)
                gw = ChannelGateway(cfg=cfg, job_store=store)

                # 1. Feishu URL challenge handshake
                feishu_ch = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode("utf-8")
                code, body = gw.handle_webhook("feishu", {}, feishu_ch)
                self.assertEqual(code, 200)
                self.assertEqual(body["challenge"], "abc123")

                # 2. Slack valid HMAC vs invalid HMAC
                slack_payload = json.dumps({
                    "event": {"type": "message", "user": "u_allowed", "channel": "C1", "text": "check status"}
                }).encode("utf-8")
                ts = str(int(time.time()))
                sig = "v0=" + hmac.new(
                    b"slack_secret_test",
                    f"v0:{ts}:".encode("utf-8") + slack_payload,
                    hashlib.sha256,
                ).hexdigest()
                bad_code, _ = gw.handle_webhook(
                    "slack",
                    {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=deadbeef"},
                    slack_payload,
                )
                self.assertEqual(bad_code, 401)

                ok_code, ok_body = gw.handle_webhook(
                    "slack",
                    {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig},
                    slack_payload,
                    enqueue_fn=lambda msg, adapter: {"job_id": "job_test_1"},
                )
                self.assertEqual(ok_code, 202)
                self.assertEqual(ok_body["job_id"], "job_test_1")

                # 3. Telegram allowlist blocks unauthorized sender with 403
                tg_bad = json.dumps({
                    "message": {"from": {"id": "stranger_99"}, "chat": {"id": "c1"}, "text": "hi"}
                }).encode("utf-8")
                c403, _ = gw.handle_webhook(
                    "telegram",
                    {"X-Telegram-Bot-Api-Secret-Token": "tg_secret_tok"},
                    tg_bad,
                    enqueue_fn=lambda msg, adapter: {"job_id": "nope"},
                )
                self.assertEqual(c403, 403)

                # 4. DingTalk HMAC verification
                dt_ts = str(int(time.time() * 1000))
                dt_sign = base64.b64encode(
                    hmac.new(
                        b"dt_secret_test",
                        f"{dt_ts}\ndt_secret_test".encode("utf-8"),
                        hashlib.sha256,
                    ).digest()
                ).decode("utf-8")
                dt_payload = json.dumps({
                    "senderStaffId": "u_allowed",
                    "conversationId": "conv1",
                    "text": {"content": "hello dingtalk"},
                }).encode("utf-8")
                c202, dt_body = gw.handle_webhook(
                    "dingtalk",
                    {"timestamp": dt_ts, "sign": dt_sign},
                    dt_payload,
                    enqueue_fn=lambda msg, adapter: {"job_id": "job_dt_1"},
                )
                self.assertEqual(c202, 202)
                self.assertEqual(dt_body["job_id"], "job_dt_1")

                # 5. Real outbound HTTP POST to local server
                feishu = get_adapter("feishu", cfg)
                sent = feishu.send_outbound("chat_1", "Polaris V41 ready")
                self.assertTrue(sent["ok"])
                self.assertEqual(len(received_outbound), 1)
                self.assertEqual(received_outbound[0]["path"], "/feishu")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
