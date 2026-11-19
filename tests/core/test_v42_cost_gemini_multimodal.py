"""End-to-end tests for V42 CostLedger, Budget Circuit Breaker, Gemini Adapter, and Multimodal."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from baize.core.agent import Agent
from baize.core.config import load_config
from baize.core.cost_ledger import CostLedger, estimate_usd
from baize.core.llm import LLMClient, encode_image_part
from baize.ext.providers.gemini import GeminiProviderAdapter


class _MockGeminiHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        has_inline = False
        for c in body.get("contents", []):
            for p in c.get("parts", []):
                if "inlineData" in p:
                    has_inline = True
        resp = {
            "candidates": [{
                "content": {
                    "role": "model",
                    "parts": [{"text": f"gemini-ok inline={has_inline}"}],
                },
                "finishReason": "STOP",
            }],
            "usageMetadata": {
                "promptTokenCount": 200,
                "cachedContentTokenCount": 100,
                "candidatesTokenCount": 50,
            },
        }
        raw = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        return


class _BudgetStubClient:
    """Stub LLM client that records realistic token usage on each turn."""

    configured = True
    build_messages = staticmethod(LLMClient.build_messages)

    def __init__(self) -> None:
        self.calls = 0
        self.last_usage: dict = {}

    def chat(self, messages, tools=None, temperature=0.2):
        self.calls += 1
        # Simulate expensive call (~$0.03 per turn on gpt-4o)
        self.last_usage = {
            "provider": "openai",
            "model": "gpt-4o",
            "prompt_tokens": 6000,
            "completion_tokens": 1500,
            "cached_tokens": 1000,
        }
        return {
            "content": f"step {self.calls}",
            "tool_calls": [{
                "id": f"call_{self.calls}",
                "type": "function",
                "function": {
                    "name": "grep_search",
                    "arguments": json.dumps({"pattern": f"token_{self.calls}", "path": "."}),
                },
            }],
        }


class TestV42CostGeminiMultimodal(unittest.TestCase):
    def test_cost_ledger_rates_cache_ratio_and_reset(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = CostLedger(Path(td) / "cost.sqlite3")
            r1 = ledger.record(
                session_id="s-1",
                provider="deepseek",
                model="deepseek-chat",
                prompt_tokens=10000,
                completion_tokens=2000,
                cached_tokens=6000,
            )
            self.assertGreater(r1["estimated_usd"], 0.0)
            s = ledger.summary()
            self.assertEqual(s["total_calls"], 1)
            self.assertAlmostEqual(s["cache_hit_ratio"], 0.6, places=2)
            self.assertGreater(estimate_usd("gemini-2.5-flash", prompt_tokens=10000, cached_tokens=5000, completion_tokens=1000), 0.0)
            deleted = ledger.reset_session("s-1")
            self.assertEqual(deleted, 1)
            self.assertEqual(ledger.summary()["total_calls"], 0)

    def test_agent_budget_soft_warning_and_hard_circuit_breaker(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {
                **load_config(),
                "BAIZE_PERSISTENCE_DIR": td,
                "BAIZE_SESSIONS_DIR": str(Path(td) / "sessions"),
                "BAIZE_WORKSPACE_DIR": td,
                "BAIZE_MAX_STEPS": "10",
                "BAIZE_MAX_SESSION_USD": "0.05",
                "BAIZE_MAX_SESSION_TOKENS": "0",
                "BAIZE_BUDGET_WARN_RATIO": "0.5",
                "BAIZE_TOOL_PROFILE": "core",
            }
            stub = _BudgetStubClient()
            events: list[tuple[str, dict]] = []
            agent = Agent(
                role="executor",
                client=stub,
                cfg=cfg,
                on_event=lambda k, p: events.append((k, p)),
            )
            res = agent.run("inspect workspace")
            self.assertEqual(res.stopped_reason, "budget_exceeded")
            # Turn 1 spends ~$0.02875 (>50% -> warning on turn 2), turn 2 spends ~$0.0575 (>100% -> halt before turn 3)
            self.assertLessEqual(stub.calls, 2)
            kinds = [k for k, _ in events]
            self.assertIn("budget_warning", kinds)

    def test_gemini_provider_adapter_request_parse_and_http(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockGeminiHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                img = Path(td) / "demo.png"
                img.write_bytes(b"\x89PNG\r\n\x1a\nTESTIMAGE")
                part = encode_image_part(img, provider="gemini")
                adapter = GeminiProviderAdapter(
                    api_key="test-gemini-key",
                    model="gemini-2.5-flash",
                    base_url=f"http://127.0.0.1:{port}",
                )
                msgs = [
                    {"role": "system", "content": "Be concise"},
                    {"role": "user", "content": [{"type": "text", "text": "describe"}, part]},
                ]
                body = adapter.build_request_body(msgs, tools=[{
                    "type": "function",
                    "function": {"name": "read_file", "description": "Read", "parameters": {"type": "object"}},
                }])
                self.assertIn("systemInstruction", body)
                self.assertIn("tools", body)
                out = adapter.chat(msgs)
                self.assertIn("gemini-ok inline=True", out["content"])
                self.assertEqual(out["_usage"]["cached_tokens"], 100)

                # Verify LLMClient dispatches provider=gemini end-to-end
                client = LLMClient(cfg={
                    "BAIZE_MODEL_PROVIDER": "gemini",
                    "BAIZE_MODEL_BASE_URL": f"http://127.0.0.1:{port}",
                    "BAIZE_MODEL_API_KEY": "test-gemini-key",
                    "BAIZE_MODEL_NAME": "gemini-2.5-flash",
                })
                res = client.chat([{"role": "user", "content": "hi"}])
                self.assertIn("gemini-ok", res["content"])
                self.assertEqual(client.last_usage.get("provider"), "gemini")
                self.assertEqual(client.last_usage.get("cached_tokens"), 100)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_encode_image_part_providers_and_size_limit(self):
        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "tiny.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\n12345")
            p_oai = encode_image_part(img, provider="openai")
            self.assertEqual(p_oai["type"], "image_url")
            self.assertTrue(p_oai["image_url"]["url"].startswith("data:image/png;base64,"))
            p_ant = encode_image_part(img, provider="anthropic")
            self.assertEqual(p_ant["type"], "image")
            self.assertEqual(p_ant["source"]["media_type"], "image/png")
            p_gem = encode_image_part(img, provider="gemini")
            self.assertEqual(p_gem["mime_type"], "image/png")
            with self.assertRaises(ValueError):
                encode_image_part(img, provider="openai", max_bytes=4)


if __name__ == "__main__":
    unittest.main()
