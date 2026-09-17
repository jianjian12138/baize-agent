"""Unit tests for Baize SSE streaming endpoint and session export (V34.0.0)."""
from __future__ import annotations

import unittest
from baize.desktop_ui import render_desktop_studio
from baize import __version__
from baize.serve import Handler


class TestStreamAndExport(unittest.TestCase):
    def test_desktop_studio_includes_rich_code_and_export(self):
        html = render_desktop_studio("34.0.0")
        self.assertIn("copyCodeBlock", html)
        self.assertIn("renderRichMarkdown", html)
        self.assertIn("exportCurrentSession", html)
        self.assertIn("thinking-drawer", html)

    def test_export_session_formatting(self):
        """Session export must round-trip exactly the messages that were appended.

        Rewritten to isolate its state. The previous version appended to a FIXED
        session id in the real persistence directory and asserted the total was
        exactly 2, cleaning up only at the end:

            try:
                p.unlink()
            except OSError:
                pass

        On Windows `unlink()` on a still-open file raises PermissionError, which
        that `except OSError` swallowed silently - so the file survived, the next
        run appended 2 more, the count assertion failed, and the failure aborted
        the function *before* the cleanup. That made the test self-latching: once
        it leaked, it could never pass again. Measured: 8 accumulated records from
        4 runs, failing from the first leak onward.

        Pointing BAIZE_SESSIONS_DIR at a temporary directory removes the shared
        state entirely, so there is nothing to clean up and no way to leak.

        This is a unittest.TestCase, so pytest fixtures (tmp_path, monkeypatch)
        cannot be injected - the environment is set and restored by hand.
        """
        import os
        import tempfile

        from baize.sessions import Session, _read_records

        with tempfile.TemporaryDirectory() as td:
            previous = os.environ.get("BAIZE_SESSIONS_DIR")
            os.environ["BAIZE_SESSIONS_DIR"] = td
            try:
                s = Session(session_id="test_export_999")
                s.append({"role": "user", "content": "Hello Baize"})
                s.append({"role": "assistant", "content": "Hello! I am ready."})

                recs = _read_records("test_export_999")
                msgs = [r.get("message", r) for r in recs
                        if r.get("kind") == "message"]
                self.assertEqual(len(msgs), 2)
                self.assertEqual(msgs[0]["content"], "Hello Baize")

                # Append-only, not overwrite: a fresh Session on the same id must
                # see what the first one wrote. That is the property this test is
                # really about; the old version asserted an absolute count instead
                # and so could not distinguish the two.
                reopened = Session(session_id="test_export_999")
                self.assertEqual(len(reopened.messages), 2)

                # Re-running the same assertions must be a no-op on a fresh dir:
                # prove the test does not depend on leftovers from a prior run.
                self.assertEqual(
                    len([r for r in _read_records("test_export_999")
                         if r.get("kind") == "message"]), 2)
            finally:
                if previous is None:
                    os.environ.pop("BAIZE_SESSIONS_DIR", None)
                else:
                    os.environ["BAIZE_SESSIONS_DIR"] = previous

    def test_desktop_studio_includes_search_and_heal(self):
        html = render_desktop_studio("34.0.0")
        self.assertIn("filterSessions", html)
        self.assertIn("mergeSpeculativeWinner", html)
        self.assertIn("applyCausalHeal", html)

    def test_desktop_studio_includes_metrics_and_webhook(self):
        html = render_desktop_studio("34.0.0")
        self.assertIn("loadMetricsSummary", html)
        self.assertIn("testWebhookDispatch", html)
        self.assertIn("metric-uptime", html)

    def test_desktop_studio_includes_dag_palette_and_lineage_tree(self):
        html = render_desktop_studio("34.1.0")
        self.assertIn("addDagNode", html)
        self.assertIn("loadLineageTree", html)
        self.assertIn("setDiffViewMode", html)
        self.assertIn("diff-mode-split", html)

    def test_desktop_studio_includes_sprint2_features(self):
        html = render_desktop_studio("34.2.0")
        self.assertIn("persistCausalTest", html)
        self.assertIn("loadToolHub", html)
        self.assertIn("importMetaTool", html)
        self.assertIn("testRagSearch", html)

    def test_desktop_studio_includes_sprint3_features(self):
        html = render_desktop_studio("35.0.0")
        self.assertIn("runChaosSimulation", html)
        self.assertIn("applyRbacRules", html)
        self.assertIn("Baize-Gate-Verified", html)
        self.assertIn("Matt Pocock套件", html)
        from pathlib import Path
        self.assertTrue(Path("Dockerfile").exists())

    def test_mattpocock_skills_catalog_integration(self):
        from baize.skills_catalog import get_full_skills_catalog, get_skill_content
        catalog = get_full_skills_catalog()
        matt_skills = [s for s in catalog if s.get("domain") == "mattpocock"]
        self.assertGreaterEqual(len(matt_skills), 8)
        names = {s["name"] for s in matt_skills}
        self.assertIn("grill-with-docs", names)
        self.assertIn("to-spec", names)
        self.assertIn("to-tickets", names)

        content = get_skill_content("grill-with-docs")
        self.assertIn("Matt Pocock", content)
        self.assertIn("The Spine Workflow", content)
