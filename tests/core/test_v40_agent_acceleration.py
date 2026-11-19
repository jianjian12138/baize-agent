"""Tests for V40 core acceleration: streaming, parallel read-only tools,
post-edit auto-diagnostics, and Git transactional checkpoint/rollback.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from baize.core.agent import Agent, READ_ONLY_TOOLS
from baize.core.config import load_config
from baize.core.llm import LLMClient
from baize.execution.checkpoint import GitCheckpointManager
from baize.execution.tools import ToolRegistry


class _ScriptedClient:
    configured = True

    def __init__(self, turns: list[dict]):
        self._turns = list(turns)
        self.calls = 0

    def build_messages(self, sys_prompt, tool_schemas, session_messages):
        return list(session_messages)

    def chat(self, messages, tools=None, temperature=None, stream=False):
        idx = min(self.calls, len(self._turns) - 1)
        self.calls += 1
        return self._turns[idx]

    def chat_with_stream(self, messages, tools=None, temperature=None, on_token=None):
        msg = self.chat(messages, tools=tools, temperature=temperature)
        if on_token and msg.get("content"):
            for ch in [msg["content"][:5], msg["content"][5:]]:
                if ch:
                    on_token(ch)
        return msg


class TestV40AgentAcceleration(unittest.TestCase):
    def test_streaming_on_token_callback_receives_live_deltas(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {**load_config(), "BAIZE_WORKSPACE_DIR": td, "BAIZE_SESSIONS_DIR": td, "BAIZE_AUTO_HARVEST_SKILLS": "0"}
            client = _ScriptedClient([{"role": "assistant", "content": "Hello streamed world"}])
            tokens: list[str] = []
            agent = Agent(cfg=cfg, client=client, registry=ToolRegistry(), on_token=tokens.append)
            res = agent.run("say hi")
            self.assertEqual(res.stopped_reason, "final")
            self.assertEqual("".join(tokens), "Hello streamed world")
            self.assertGreaterEqual(len(tokens), 2)

    def test_llm_chat_with_stream_accumulates_text_and_tool_calls(self):
        chunks = [
            {"choices": [{"delta": {"content": "Checking "}}]},
            {"choices": [{"delta": {"content": "files"}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {"name": "read_", "arguments": '{"path":'}}
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"name": "file", "arguments": ' "a.py"}'}}
            ]}}]},
        ]
        client = LLMClient({"BAIZE_MODEL_BASE_URL": "https://example.invalid", "BAIZE_MODEL_API_KEY": "sk-test", "BAIZE_MODEL_NAME": "gpt-4o"})
        client.stream_transport = lambda url, hdrs, body: iter(chunks)
        got: list[str] = []
        msg = client.chat_with_stream([{"role": "user", "content": "hi"}], on_token=got.append)
        self.assertEqual("".join(got), "Checking files")
        self.assertEqual(msg["content"], "Checking files")
        self.assertEqual(len(msg["tool_calls"]), 1)
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(msg["tool_calls"][0]["function"]["arguments"]), {"path": "a.py"})

    def test_parallel_read_only_tool_batch_runs_concurrently_and_preserves_order(self):
        barrier = threading.Barrier(3, timeout=3.0)

        def fake_read(path: str) -> str:
            barrier.wait()
            return f"content:{path}"

        reg = ToolRegistry()
        reg.register("read_file", "read", {"type": "object", "properties": {"path": {"type": "string"}}}, fake_read)
        self.assertIn("read_file", READ_ONLY_TOOLS)

        client = _ScriptedClient([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "read_file", "arguments": '{"path": "one.py"}'}},
                    {"id": "c2", "function": {"name": "read_file", "arguments": '{"path": "two.py"}'}},
                    {"id": "c3", "function": {"name": "read_file", "arguments": '{"path": "three.py"}'}},
                ],
            },
            {"role": "assistant", "content": "all read"},
        ])
        with tempfile.TemporaryDirectory() as td:
            cfg = {**load_config(), "BAIZE_WORKSPACE_DIR": td, "BAIZE_SESSIONS_DIR": td, "BAIZE_AUTO_HARVEST_SKILLS": "0"}
            events: list[tuple[str, str]] = []
            agent = Agent(cfg=cfg, client=client, registry=reg, on_event=lambda k, d: events.append((k, d)))
            res = agent.run("read three files")
            self.assertEqual(res.stopped_reason, "final")
            tool_msgs = [m for m in res.transcript if m.get("role") == "tool"]
            self.assertEqual([m["tool_call_id"] for m in tool_msgs], ["c1", "c2", "c3"])
            self.assertEqual([m["content"] for m in tool_msgs], ["content:one.py", "content:two.py", "content:three.py"])
            self.assertTrue(any(k == "tool_batch_start" for k, _ in events))

    def test_post_edit_auto_diagnostics_reports_python_syntax_error(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            reg = ToolRegistry()

            def _write(path: str, content: str) -> str:
                p = ws / path
                p.write_text(content, encoding="utf-8")
                return f"wrote {path}"

            reg.register("write_file", "write", {"type": "object", "properties": {}}, _write)
            client = _ScriptedClient([
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "w1", "function": {"name": "write_file",
                                                  "arguments": json.dumps({"path": "bad.py", "content": "def broken(:\n    pass\n"})}}
                    ],
                },
                {"role": "assistant", "content": "seen diagnostic"},
            ])
            cfg = {
                **load_config(),
                "BAIZE_WORKSPACE_DIR": str(ws),
                "BAIZE_SESSIONS_DIR": str(ws / "sessions"),
                "BAIZE_AUTO_DIAGNOSTICS": "1",
                "BAIZE_AUTO_HARVEST_SKILLS": "0",
            }
            agent = Agent(cfg=cfg, client=client, registry=reg)
            res = agent.run("write bad python")
            tool_msgs = [m for m in res.transcript if m.get("role") == "tool"]
            self.assertEqual(len(tool_msgs), 1)
            self.assertIn("[diagnostics:python-ast]", tool_msgs[0]["content"])
            self.assertIn("SyntaxError", tool_msgs[0]["content"])

    def test_git_checkpoint_manager_snapshot_and_atomic_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
            subprocess.run(["git", "config", "user.email", "test@baize.local"], cwd=ws, check=True)
            subprocess.run(["git", "config", "user.name", "Baize Test"], cwd=ws, check=True)
            (ws / "a.txt").write_text("original\n", encoding="utf-8")
            subprocess.run(["git", "add", "a.txt"], cwd=ws, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=ws, check=True)

            mgr = GitCheckpointManager(ws)
            cp = mgr.create(label="before-edit")
            self.assertEqual(cp.status, "active")

            (ws / "a.txt").write_text("broken change\n", encoding="utf-8")
            (ws / "stray.txt").write_text("should disappear\n", encoding="utf-8")
            self.assertIn("a.txt", mgr.diff_stat(cp.checkpoint_id))

            rb = mgr.rollback(cp.checkpoint_id)
            self.assertTrue(rb["ok"])
            self.assertEqual((ws / "a.txt").read_text(encoding="utf-8"), "original\n")
            self.assertFalse((ws / "stray.txt").exists())
            stash_out = subprocess.run(["git", "stash", "list"], cwd=ws, capture_output=True, text=True).stdout.strip()
            self.assertEqual(stash_out, "")

    def test_agent_auto_rollback_on_max_steps_restores_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
            subprocess.run(["git", "config", "user.email", "test@baize.local"], cwd=ws, check=True)
            subprocess.run(["git", "config", "user.name", "Baize Test"], cwd=ws, check=True)
            (ws / "keep.py").write_text("X = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "keep.py"], cwd=ws, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=ws, check=True)

            reg = ToolRegistry()
            reg.register(
                "write_file", "write", {"type": "object", "properties": {}},
                lambda path, content: (ws / path).write_text(content, encoding="utf-8") and "ok" or "ok",
            )
            client = _ScriptedClient([
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "w1", "function": {"name": "write_file",
                                                  "arguments": json.dumps({"path": "keep.py", "content": "X = 999\n"})}}
                    ],
                },
            ])
            cfg = {
                **load_config(),
                "BAIZE_WORKSPACE_DIR": str(ws),
                "BAIZE_SESSIONS_DIR": str(ws / ".baize_checkpoints" / "sessions"),
                "BAIZE_AGENT_MAX_STEPS": "1",
                "BAIZE_AUTO_ROLLBACK": "1",
                "BAIZE_AUTO_HARVEST_SKILLS": "0",
            }
            agent = Agent(cfg=cfg, client=client, registry=reg)
            res = agent.run("mutate and fail")
            self.assertEqual(res.stopped_reason, "max_steps")
            self.assertTrue(res.rolled_back)
            self.assertTrue(res.checkpoint_id.startswith("cp-"))
            self.assertEqual((ws / "keep.py").read_text(encoding="utf-8"), "X = 1\n")


if __name__ == "__main__":
    unittest.main()
