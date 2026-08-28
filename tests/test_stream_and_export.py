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
        from baize.sessions import Session, _read_records
        # Create a dummy session
        s = Session(session_id="test_export_999")
        s.append({"role": "user", "content": "Hello Baize"})
        s.append({"role": "assistant", "content": "Hello! I am ready."})

        # Test read records logic
        recs = _read_records("test_export_999")
        msgs = [r.get("message", r) for r in recs if r.get("kind") == "message"]
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["content"], "Hello Baize")
        
        # Cleanup
        try:
            from pathlib import Path
            p = Path("persistence/sessions/test_export_999.jsonl")
            if p.exists():
                p.unlink()
        except OSError:
            pass

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
