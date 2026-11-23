"""V46 Sovereign tests: Spec Hard-Gate in Agent, Visual UI Verify, MCP Catalog/Health, Skill Links & Live Server APIs."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from baize.core.agent import Agent, READ_ONLY_TOOLS
from baize.core.config import ROOT, _DEFAULTS
from baize.core.sessions import Session
from baize.execution.tools import ToolRegistry
from baize.execution.visual_verify import verify_ui
from baize.ext.mcp.client import (
    MCP_TEMPLATES,
    check_mcp_health,
    list_mcp_templates,
    render_mcp_template,
)
from baize.interfaces.serve import Handler
from baize.orchestration.spec_workflow import SpecWorkflowManager


class _FakeLLMClient:
    """Deterministic stub client returning a scripted sequence of assistant messages."""
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.models = []
        self.last_usage = None

    def build_messages(self, sys_prompt, tool_schemas, history):
        return history

    def chat(self, msgs, tools=None):
        if self._responses:
            return self._responses.pop(0)
        return {"role": "assistant", "content": "done"}


class _DemoWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            "<!doctype html><html><head><title>Kitchen App</title></head>"
            "<body><main><h1>Recipe Planner</h1><p>Fresh pasta in 20 minutes.</p></main></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class TestV46SpecVisualMcpAndSkills(unittest.TestCase):
    def test_spec_workflow_hard_gate_blocks_mutating_tool_until_approved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = dict(_DEFAULTS)
            cfg["BAIZE_PERSISTENCE_DIR"] = td
            cfg["BAIZE_WORKSPACE_DIR"] = td
            cfg["BAIZE_SESSIONS_DIR"] = str(Path(td) / "sessions")

            mgr = SpecWorkflowManager(cfg=cfg)
            sid = "spec-e2e-session"
            mgr.enable(sid, note="start recon")
            mgr.submit_spec(sid, summary="Build kitchen recipe app")
            # Persists across fresh manager instantiation (SQLite WAL)
            mgr2 = SpecWorkflowManager(cfg=cfg)
            self.assertTrue(mgr2.get(sid).write_locked)
            self.assertEqual(mgr2.get(sid).phase, "spec_draft")

            written: list[str] = []
            reg = ToolRegistry()
            reg.register("read_file", "read", {"type": "object", "properties": {"path": {"type": "string"}}}, lambda path="": "ok-read")
            reg.register("write_file", "write", {"type": "object", "properties": {"path": {"type": "string"}}}, lambda path="": (written.append(path) or "ok-write"))

            events: list[tuple[str, str]] = []
            client = _FakeLLMClient([
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "tc1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}},
                        {"id": "tc2", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "b.py"})}},
                    ],
                },
                {"role": "assistant", "content": "Awaiting spec approval."},
            ])
            sess = Session(session_id=sid, cfg=cfg)
            agent = Agent(
                cfg=cfg,
                client=client,
                registry=reg,
                session=sess,
                on_event=lambda ev, d: events.append((ev, d)),
            )
            res = agent.run("Explore and edit")
            self.assertEqual(written, [], "write_file MUST NOT execute while spec gate is locked")
            self.assertTrue(any(ev == "spec_locked" for ev, _ in events))
            self.assertTrue(any("SPEC_GATE_LOCKED" in str(m.get("content", "")) for m in sess.messages))

            # Now approve spec -> write_file unlocks and executes!
            mgr.approve(sid, actor="reviewer", note="LGTM")
            self.assertFalse(mgr.get(sid).write_locked)

            client2 = _FakeLLMClient([
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "tc3", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "b.py"})}},
                    ],
                },
                {"role": "assistant", "content": "File written."},
            ])
            agent2 = Agent(cfg=cfg, client=client2, registry=reg, session=sess)
            agent2.run("Now apply the approved spec")
            self.assertEqual(written, ["b.py"])
            self.assertEqual(mgr.get(sid).phase, "executing")

    def test_verify_ui_against_live_local_server_and_egress_guard(self) -> None:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _DemoWebHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            url = f"http://127.0.0.1:{port}/"
            rep = verify_ui(url, viewports=["desktop", "mobile"], check_visual=False)
            self.assertTrue(rep.passed, f"Expected pass on clean demo page, got defects={rep.defects}")
            self.assertEqual(len(rep.captures), 2)
            self.assertEqual(rep.captures[0].viewport, "desktop")
            self.assertEqual(rep.captures[1].viewport, "mobile")
            self.assertIn("verify_ui", rep.format_for_agent())

            # Egress allowlist fail-closed check
            blocked = verify_ui(url, viewports=["desktop"], check_visual=False, cfg={"BAIZE_EGRESS_ALLOWLIST": "example.com"})
            self.assertFalse(blocked.passed)
            self.assertTrue(any("egress" in d.lower() for d in blocked.defects))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_mcp_templates_catalog_and_health_check(self) -> None:
        tpls = list_mcp_templates()
        self.assertGreaterEqual(len(tpls), 8)
        self.assertIn("github", MCP_TEMPLATES)
        self.assertIn("filesystem", MCP_TEMPLATES)
        self.assertIn("figma", MCP_TEMPLATES)

        rendered = render_mcp_template("filesystem", overrides={"WORKSPACE_DIR": "/tmp/demo"})
        self.assertEqual(rendered["command"], "npx")
        self.assertIn("/tmp/demo", rendered["args"])

        health = check_mcp_health(specs=[
            {"name": "ok-py", "command": "python3", "args": [], "required_env": []},
            {"name": "bad-bin", "command": "nonexistent_mcp_binary_xyz_999", "args": [], "required_env": ["MISSING_SECRET_XYZ"]},
        ])
        self.assertEqual(health["total"], 2)
        self.assertEqual(health["healthy"], 1)
        self.assertEqual(health["unhealthy"], 1)
        bad = [s for s in health["servers"] if s["name"] == "bad-bin"][0]
        self.assertFalse(bad["ok"])
        self.assertIn("MISSING_SECRET_XYZ", bad["missing_env"])

    def test_zero_broken_relative_links_across_all_skills_and_universal_spec_skill_exists(self) -> None:
        skills_root = ROOT / "assets" / "skills"
        self.assertTrue((skills_root / "spec_driven_dev" / "SKILL.md").is_file())
        broken: list[tuple[str, str]] = []
        for md in sorted(skills_root.rglob("*.md")):
            txt = md.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"(\.\./[^\s`\"')>]+)", txt):
                rel = m.group(1).rstrip(".,;:")
                if not (md.parent / rel).resolve().exists():
                    broken.append((str(md.relative_to(skills_root)), rel))
        self.assertEqual(broken, [], f"Found broken relative links in skills: {broken}")

    def test_live_http_routes_v45_v46_and_studio_console(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_env = {k: os.environ.get(k) for k in ("BAIZE_ALLOW_NO_AUTH", "BAIZE_PERSISTENCE_DIR")}
            os.environ["BAIZE_ALLOW_NO_AUTH"] = "1"
            os.environ["BAIZE_PERSISTENCE_DIR"] = td
            srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                base = f"http://127.0.0.1:{port}"
                # GET /api/platform/status
                with urlopen(f"{base}/api/platform/status?session_id=http-s1", timeout=5) as r:
                    d = json.loads(r.read().decode("utf-8"))
                    self.assertIn("project_profile", d)
                    self.assertIn("lsp_pool", d)
                    self.assertIn("sandbox", d)
                    self.assertIn("spec_workflow", d)
                    self.assertGreaterEqual(d["mcp_templates_count"], 8)

                # POST /api/spec enable -> approve
                for action, expected_locked in (("enable", True), ("approve", False)):
                    req = Request(
                        f"{base}/api/spec",
                        data=json.dumps({"session_id": "http-s1", "action": action}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urlopen(req, timeout=5) as r:
                        sd = json.loads(r.read().decode("utf-8"))
                        self.assertEqual(sd["write_locked"], expected_locked)

                # GET /api/mcp/templates
                with urlopen(f"{base}/api/mcp/templates", timeout=5) as r:
                    md = json.loads(r.read().decode("utf-8"))
                    self.assertGreaterEqual(md["total"], 8)

                # POST /api/mcp/health
                req = Request(
                    f"{base}/api/mcp/health",
                    data=json.dumps({"specs": [{"name": "py", "command": "python3"}]}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=5) as r:
                    hd = json.loads(r.read().decode("utf-8"))
                    self.assertEqual(hd["healthy"], 1)

                # Studio index.html has helios-v46 pane
                studio_html = (ROOT / "baize" / "interfaces" / "studio" / "index.html").read_text(encoding="utf-8")
                self.assertIn('id="helios-v46"', studio_html)
                self.assertIn("runHeliosVisualVerify", studio_html)
            finally:
                srv.shutdown()
                srv.server_close()
                for k, v in old_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
