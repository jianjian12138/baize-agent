"""V49.0.1 dogfooding regression tests covering all 5 field-discovered fixes."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from baize.codebase.impact import analyze_blast_radius, analyze_test_impact
from baize.core.agent import Agent, Session
from baize.core.config import load_config
from baize.core.llm import LLMClient
from baize.execution.tools import default_registry
from baize.governance.dlp import get_audit_ledger
from baize.governance.doctor import run_checks


class _FakeLLM:
    build_messages = staticmethod(LLMClient.build_messages)

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.configured = True
        self.calls = 0

    def chat(self, messages, tools=None, temperature=None, stream=False):
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[idx]


class TestV49DogfoodFixes(unittest.TestCase):
    def test_01_impact_uses_external_workspace_root(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "sut").mkdir()
            (ws / "tests").mkdir()
            (ws / "sut" / "db.py").write_text("def create_order():\n    return 1\n", encoding="utf-8")
            (ws / "tests" / "test_db.py").write_text(
                "from sut.db import create_order\ndef test_order():\n    assert create_order() == 1\n",
                encoding="utf-8",
            )
            res = analyze_test_impact("sut/db.py", root_dir=ws)
            self.assertEqual(res.total_test_files, 1)
            self.assertEqual(res.impacted_files, ["tests/test_db.py"])

    def test_02_blast_expands_file_path_symbols(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "sut").mkdir()
            (ws / "sut" / "db.py").write_text(
                "def create_order():\n    return 1\ndef cancel_order():\n    return 2\n",
                encoding="utf-8",
            )
            (ws / "sut" / "server.py").write_text(
                "from . import db\ndef handle_post():\n    return db.create_order()\n",
                encoding="utf-8",
            )
            rep = analyze_blast_radius("sut/db.py", workspace_dir=ws)
            self.assertEqual(rep.target_file, "sut/db.py")
            self.assertIn("sut/server.py", rep.impacted_files)
            self.assertGreaterEqual(len(rep.direct_callers), 1)

    def test_03_permission_denied_persisted_in_audit_chain(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / ".baize").mkdir()
            (ws / ".env").write_text("SECRET=123\n", encoding="utf-8")
            (ws / ".baize" / "permissions.json").write_text(
                json.dumps({"deny": ["Read(.env*)"]}),
                encoding="utf-8",
            )
            persist = ws / ".baize" / "persistence"
            persist.mkdir(parents=True)
            cfg = dict(load_config())
            cfg["BAIZE_WORKSPACE_DIR"] = str(ws)
            cfg["BAIZE_PERSISTENCE_DIR"] = str(persist)
            cfg["BAIZE_SESSIONS_DIR"] = str(ws / ".sessions")
            cfg["BAIZE_ALLOW_EGRESS"] = "1"

            llm = _FakeLLM([
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": json.dumps({"path": ".env"})},
                    }],
                },
                {"role": "assistant", "content": "done"},
            ])

            ag = Agent(
                role="executor",
                cfg=cfg,
                client=llm,
                registry=default_registry(),
                session=Session(session_id="audit-deny-test", cfg=cfg),
            )
            ag.run("read .env")

            ledger = get_audit_ledger(cfg)
            ver = ledger.verify_chain()
            self.assertTrue(ver["ok"])
            denied = ledger.list_entries(limit=20, event_type="permission_denied")
            self.assertGreaterEqual(len(denied), 1)
            self.assertEqual(denied[0]["target"], "read_file")
            self.assertEqual(denied[0]["outcome"], "denied")

    def test_04_llm_retry_alias_and_default_alignment(self):
        old_new = os.environ.pop("BAIZE_LLM_RETRY_MAX", None)
        old_leg = os.environ.pop("BAIZE_LLM_MAX_RETRIES", None)
        try:
            cfg = dict(load_config())
            self.assertEqual(cfg["BAIZE_LLM_RETRY_MAX"], "3")
            self.assertEqual(cfg["BAIZE_LLM_MAX_RETRIES"], "3")
            cfg_leg = dict(cfg)
            cfg_leg["BAIZE_LLM_MAX_RETRIES"] = "5"
            c1 = LLMClient(cfg=cfg_leg)
            self.assertEqual(c1.max_retries, 5)
            cfg_both = dict(cfg)
            cfg_both["BAIZE_LLM_MAX_RETRIES"] = "5"
            cfg_both["BAIZE_LLM_RETRY_MAX"] = "1"
            c2 = LLMClient(cfg=cfg_both)
            self.assertEqual(c2.max_retries, 1)
        finally:
            if old_new is not None:
                os.environ["BAIZE_LLM_RETRY_MAX"] = old_new
            if old_leg is not None:
                os.environ["BAIZE_LLM_MAX_RETRIES"] = old_leg

    def test_05_doctor_workspace_env_and_fix_flag(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / ".env").write_text("KEY=VAL\n", encoding="utf-8")
            persist = ws / ".baize" / "persistence"
            projects = ws / "projects"
            assets = ws / "assets"
            cfg = dict(load_config())
            cfg["BAIZE_WORKSPACE_DIR"] = str(ws)
            cfg["BAIZE_PERSISTENCE_DIR"] = str(persist)
            cfg["BAIZE_PROJECTS_DIR"] = str(projects)
            cfg["BAIZE_ASSETS_DIR"] = str(assets)

            rep_before = run_checks(cfg, fix=False)
            self.assertFalse(rep_before.passed)
            env_chk = [r for r in rep_before.results if r.name == ".env present"][0]
            self.assertTrue(env_chk.ok)
            self.assertIn(str(ws / ".env"), env_chk.detail)

            rep_fixed = run_checks(cfg, fix=True)
            self.assertTrue(rep_fixed.passed)
            self.assertTrue(persist.is_dir())


if __name__ == "__main__":
    unittest.main()
