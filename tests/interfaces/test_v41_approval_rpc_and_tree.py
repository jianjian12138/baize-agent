"""V41.0.0 Polaris — Tiered Diff approval, JSONL RPC, dual-axis tree rewind, and external evals."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from baize.core.agent import Session
from baize.core.sessions import (
    build_session_tree,
    format_session_tree,
    record_checkpoint_node,
    rewind_session,
)
from baize.execution.checkpoint import GitCheckpointManager
from baize.governance.eval_harness import load_external_eval_tasks, run_profile_comparison
from baize.interfaces.approval import (
    ApprovalRequest,
    TieredApprovalPolicy,
    build_tool_preview,
    format_status_bar,
    make_terminal_approval_callback,
    render_unified_diff,
)
from baize.interfaces.rpc import RpcServer, StreamJsonEmitter


class TestV41ApprovalRpcTreeAndEval(unittest.TestCase):
    def test_tiered_approval_diff_preview_and_session_allow(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "demo.py"
            f.write_text("x = 1\n", encoding="utf-8")

            policy = TieredApprovalPolicy(mode="tiered")
            self.assertFalse(policy.requires_approval("read_file", {"path": "demo.py"}))
            self.assertTrue(policy.requires_approval("write_file", {"path": "demo.py"}))
            self.assertTrue(policy.requires_approval("bash", {"command": "echo hi"}))

            diff = render_unified_diff("demo.py", "x = 1\n", "x = 2\n", color=False)
            self.assertIn("-x = 1", diff)
            self.assertIn("+x = 2", diff)

            preview = build_tool_preview("write_file", {"path": "demo.py", "content": "x = 2\n"}, workspace=td, color=False)
            self.assertIn("+x = 2", preview)

            answers = iter(["a", "n too risky"])
            out_buf = io.StringIO()
            cb = make_terminal_approval_callback(
                policy,
                workspace=td,
                input_fn=lambda _prompt: next(answers),
                output_stream=out_buf,
            )
            # First write_file -> 'a' allows for entire session
            d1 = cb(ApprovalRequest(
                tool_name="write_file",
                arguments={"path": "demo.py", "content": "x = 2\n"},
                preview=preview,
            ))
            self.assertTrue(d1.approved)
            self.assertEqual(d1.scope, "session")

            # Second write_file skips prompt automatically!
            d2 = cb(ApprovalRequest(
                tool_name="write_file",
                arguments={"path": "demo.py", "content": "x = 3\n"},
                preview=preview,
            ))
            self.assertTrue(d2.approved)

            # bash still prompts -> 'n' + reason denies
            d3 = cb(ApprovalRequest(
                tool_name="bash",
                arguments={"command": "rm -rf /tmp/foo"},
                preview="bash: rm -rf /tmp/foo",
            ))
            self.assertFalse(d3.approved)
            self.assertIn("too risky", d3.reason)

            bar = format_status_bar(
                model="deepseek-chat",
                profile="tiered",
                active_tools=7,
                context_ratio=0.42,
                bg_procs=1,
                color=False,
            )
            self.assertIn("deepseek-chat", bar)
            self.assertIn("tiered", bar)
            self.assertIn("42%", bar)

    def test_rpc_server_ping_and_stream_json_emitter(self):
        buf = io.StringIO()
        em = StreamJsonEmitter(stream=buf)
        em.emit("token", {"text": "hi"})
        line = json.loads(buf.getvalue().strip())
        self.assertEqual(line["event"], "token")
        self.assertEqual(line["data"]["text"], "hi")

        in_stream = io.StringIO(
            json.dumps({"id": "1", "method": "ping"}) + "\n"
            + json.dumps({"id": "2", "method": "quit"}) + "\n"
        )
        out_stream = io.StringIO()
        srv = RpcServer(stdin=in_stream, stdout=out_stream)
        rc = srv.serve_forever()
        self.assertEqual(rc, 0)
        events = [json.loads(l) for l in out_stream.getvalue().splitlines() if l.strip()]
        self.assertTrue(any(e.get("event") == "pong" for e in events))
        self.assertTrue(any(e.get("event") == "bye" for e in events))

    def test_dual_axis_tree_and_rewind_with_git_code_restore(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "repo"
            sess_dir = Path(td) / "sessions"
            ws.mkdir()
            sess_dir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
            subprocess.run(["git", "config", "user.email", "test@baize.local"], cwd=ws, check=True)
            subprocess.run(["git", "config", "user.name", "Baize Test"], cwd=ws, check=True)
            app_py = ws / "app.py"
            app_py.write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=ws, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=ws, check=True)

            cfg = {"BAIZE_SESSIONS_DIR": str(sess_dir), "BAIZE_WORKSPACE_DIR": str(ws)}
            sess = Session(session_id="tree_s1", cfg=cfg)
            sess.append({"role": "user", "content": "turn 1"})
            sess.append({"role": "assistant", "content": "ok 1"})

            cp_mgr = GitCheckpointManager(str(ws))
            cp = cp_mgr.create("before_turn_2")
            node = record_checkpoint_node(
                sess.id,
                turn_index=len(sess.messages),
                checkpoint_id=cp.checkpoint_id if cp else "",
                summary="after turn 1",
                cfg=cfg,
            )

            sess.append({"role": "user", "content": "turn 2"})
            sess.append({"role": "assistant", "content": "changed file"})
            app_py.write_text("VALUE = 999\n", encoding="utf-8")

            tree = build_session_tree(cfg=cfg)
            self.assertTrue(any(n["session_id"] == "tree_s1" for n in tree["nodes"]))
            rendered = format_session_tree(cfg=cfg)
            self.assertIn("tree_s1", rendered)

            res = rewind_session(
                sess.id,
                node["node_id"],
                restore_code=True,
                workspace=str(ws),
                cfg=cfg,
            )
            self.assertTrue(res["ok"], res)
            self.assertTrue(res["code_restored"])
            self.assertEqual(app_py.read_text(encoding="utf-8"), "VALUE = 1\n")
            reloaded = Session(session_id=res["new_session_id"], cfg=cfg)
            self.assertEqual(len(reloaded.messages), 2)
            orig = Session(session_id="tree_s1", cfg=cfg)
            self.assertEqual(len(orig.messages), 4)

    def test_external_jsonl_eval_dataset_and_profile_comparison(self):
        with tempfile.TemporaryDirectory() as td:
            ds = Path(td) / "ext_tasks.jsonl"
            task_row = {
                "task_id": "ext_math_01",
                "title": "Fix add()",
                "goal": "Fix add() in calc.py",
                "initial_files": {
                    "calc.py": "def add(a, b):\n    return a - b\n",
                    "test_calc.py": (
                        "import unittest\nfrom calc import add\n"
                        "class T(unittest.TestCase):\n"
                        "    def test_add(self): self.assertEqual(add(2, 3), 5)\n"
                        "if __name__ == '__main__': unittest.main()\n"
                    ),
                },
                "test_command": [sys.executable, "-m", "unittest", "test_calc.py"],
                "oracle_files": {
                    "calc.py": "def add(a, b):\n    return a + b\n",
                },
            }
            ds.write_text(json.dumps(task_row) + "\n", encoding="utf-8")
            tasks = load_external_eval_tasks(ds)
            self.assertEqual(len(tasks), 1)

            report = run_profile_comparison(
                profiles=("minimal", "tiered", "full"),
                mode="oracle",
                tasks=tasks,
            )
            self.assertEqual(report["profiles"]["tiered"]["passed_tasks"], 1)
            self.assertGreater(report["tiered_savings_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()
