"""V41.0.0 Polaris — Context engine, tiered tool profile, agent wiring, and hot-reload plugins."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from baize.core.agent import Agent, Session
from baize.core.context_engine import (
    ToolProfileManager,
    compact_messages_structured,
    estimate_context_ratio,
    spill_tool_output,
)
from baize.core.plugin_lifecycle import HotReloadPluginManager
from baize.execution.tools import ToolRegistry, default_registry
from baize.interfaces.approval import ApprovalDecision


class _StubClient:
    """Deterministic multi-turn fake LLM client for Agent V41 loop tests."""

    def __init__(self, turns: list[dict]):
        self._turns = list(turns)
        self.calls: list[dict] = []
        self.configured = True

    def build_messages(self, system: str, tools: list[dict], history: list[dict]):
        return [{"role": "system", "content": system}] + list(history)

    def chat(self, messages, tools=None, stream=False, on_token=None):
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})
        if not self._turns:
            return {"role": "assistant", "content": "DONE"}
        turn = self._turns.pop(0)
        if on_token and turn.get("content"):
            on_token(turn["content"])
        return turn


class TestV41ContextAndPlugins(unittest.TestCase):
    def test_tool_profile_manager_tiered_saves_tokens_and_activates(self):
        schemas = default_registry().schemas()
        full_mgr = ToolProfileManager(schemas, profile="full")
        tiered_mgr = ToolProfileManager(schemas, profile="tiered")
        min_mgr = ToolProfileManager(schemas, profile="minimal")

        self.assertEqual(len(min_mgr.active_names), 4)
        self.assertEqual(len(tiered_mgr.active_names), 7)  # 6 core + tool_search
        self.assertGreater(len(full_mgr.active_names), 18)

        # Tiered profile saves >50% schema tokens compared to full
        savings = 1.0 - (tiered_mgr.schema_token_estimate() / full_mgr.schema_token_estimate())
        self.assertGreater(savings, 0.50)

        # Append-only activation via search_and_activate preserves existing prefix order
        before_order = list(tiered_mgr.active_names)
        res = tiered_mgr.search_and_activate("background")
        after_order = list(tiered_mgr.active_names)
        self.assertEqual(after_order[: len(before_order)], before_order)
        self.assertTrue(any("bash_bg" in n for n in res["newly_activated"]))

    def test_spillover_large_output_writes_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            small = spill_tool_output(
                "short output",
                tool_name="bash",
                session_id="s1",
                step=1,
                max_bytes=1024,
                artifacts_root=td,
            )
            self.assertFalse(small.spilled)
            self.assertEqual(small.text, "short output")

            big_text = "\n".join(f"line {i:04d} payload_abcdef1234567890" for i in range(600))
            res = spill_tool_output(
                big_text,
                tool_name="bash",
                session_id="s1",
                step=2,
                max_bytes=2048,
                artifacts_root=td,
            )
            self.assertTrue(res.spilled)
            self.assertTrue(Path(res.artifact_path).is_file())
            self.assertIn(res.artifact_path, res.text)
            self.assertIn("line 0000", res.text)
            self.assertIn("line 0599", res.text)

    def test_structured_compaction_preserves_prefix_and_recent_turns(self):
        msgs = [{"role": "system", "content": "SYSTEM_PREFIX_FIXED"}]
        for i in range(18):
            msgs.append({"role": "user", "content": f"user task {i} " + ("x" * 600)})
            msgs.append({"role": "assistant", "content": f"assistant reply {i} " + ("y" * 600)})

        _tok, ratio_before = estimate_context_ratio(msgs, budget_tokens=4000)
        self.assertGreater(ratio_before, 0.75)

        report = compact_messages_structured(
            msgs,
            budget_tokens=4000,
            threshold_ratio=0.75,
            keep_recent=4,
        )
        self.assertTrue(report.compacted)
        self.assertEqual(msgs[0]["content"], "SYSTEM_PREFIX_FIXED")
        self.assertTrue(any("COMPACTED" in str(m.get("content", "")).upper() for m in msgs))
        self.assertLess(report.tokens_after, report.tokens_before)

    def test_agent_approval_denial_feeds_back_and_steer_injects(self):
        with tempfile.TemporaryDirectory() as td:
            reg = ToolRegistry()
            executed = []
            reg.register(
                "write_file",
                "Write file",
                {"path": {"type": "string"}, "content": {"type": "string"}},
                lambda path, content: executed.append((path, content)) or "WRITTEN",
            )
            client = _StubClient([
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path": "a.txt", "content": "bad"}',
                            },
                        }
                    ],
                },
                {"role": "assistant", "content": "Understood, I will not write that file."},
            ])

            def deny_cb(req):
                return ApprovalDecision(approved=False, reason="use safe path instead")

            sess = Session(cfg={"BAIZE_SESSIONS_DIR": td})
            agent = Agent(
                role="executor",
                client=client,
                registry=reg,
                session=sess,
                approval_callback=deny_cb,
                tool_profile="full",
            )
            agent.steer("Remember to keep changes minimal")
            res = agent.run("Write a file")
            self.assertEqual(res.stopped_reason, "final")
            self.assertEqual(executed, [])
            second_turn_msgs = client.calls[1]["messages"]
            tool_texts = [str(m.get("content", "")) for m in second_turn_msgs if m.get("role") == "tool"]
            self.assertTrue(any("use safe path instead" in t for t in tool_texts))

    def test_hot_reload_plugin_lifecycle_and_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            reg = ToolRegistry()
            mgr = HotReloadPluginManager(registry=reg)
            pfile = Path(td) / "demo_plugin.py"

            # 1. Initial load
            pfile.write_text(
                "CLEANED = []\n"
                "def register(scope):\n"
                "    scope.add_tool('hello_v1', 'v1', {'name': {'type': 'string'}}, lambda name: f'v1:{name}')\n"
                "    scope.on_cleanup(lambda: CLEANED.append('v1'))\n"
                "def smoke_test(scope):\n"
                "    return 'hello_v1' in [t[0] for t in scope._staged_tools]\n",
                encoding="utf-8",
            )
            r1 = mgr.load_plugin(pfile)
            self.assertTrue(r1["ok"], r1)
            self.assertIn("hello_v1", reg.names())
            self.assertEqual(reg.execute("hello_v1", {"name": "baize"}), "v1:baize")

            # 2. Hot reload to v2
            pfile.write_text(
                "def register(scope):\n"
                "    scope.add_tool('hello_v2', 'v2', {'name': {'type': 'string'}}, lambda name: f'v2:{name}')\n"
                "def smoke_test(scope):\n"
                "    return 'hello_v2' in [t[0] for t in scope._staged_tools]\n",
                encoding="utf-8",
            )
            r2 = mgr.reload_plugin(r1["plugin_id"])
            self.assertTrue(r2["ok"], r2)
            self.assertNotIn("hello_v1", reg.names())
            self.assertIn("hello_v2", reg.names())
            self.assertEqual(reg.execute("hello_v2", {"name": "baize"}), "v2:baize")

            # 3. Broken syntax reload -> automatic rollback keeps hello_v2 alive!
            pfile.write_text("def register(scope):\n    return (((broken\n", encoding="utf-8")
            r3 = mgr.reload_plugin(r1["plugin_id"])
            self.assertFalse(r3["ok"])
            self.assertIn("hello_v2", reg.names())
            self.assertEqual(reg.execute("hello_v2", {"name": "still_alive"}), "v2:still_alive")

            # 4. Failing smoke_test -> automatic rollback keeps hello_v2 alive!
            pfile.write_text(
                "def register(scope):\n"
                "    scope.add_tool('bad_v3', 'v3', {}, lambda: 'bad')\n"
                "def smoke_test(scope):\n"
                "    return False\n",
                encoding="utf-8",
            )
            r4 = mgr.reload_plugin(r1["plugin_id"])
            self.assertFalse(r4["ok"])
            self.assertNotIn("bad_v3", reg.names())
            self.assertIn("hello_v2", reg.names())

            # 5. Clean unload removes tool
            u = mgr.unload_plugin(r1["plugin_id"])
            self.assertTrue(u["ok"])
            self.assertNotIn("hello_v2", reg.names())


if __name__ == "__main__":
    unittest.main()
