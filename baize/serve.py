"""V20 built-in REST service (stdlib http.server, zero dependencies).

Exposes the runtime over HTTP so baize can be embedded into existing systems:

  GET  /           -> V20 web dashboard (self-contained HTML)
  GET  /health     -> {"status":"ok","version":...}
  POST /run        -> {"goal": "..."}        single autonomous agent
  POST /team       -> {"goal": "..."}        Director->Executor->Verifier team
  GET  /sessions   -> list session transcripts
  GET  /metrics    -> Prometheus text (observability)

Defensive: request-size cap, JSON validation, CORS header, fail-closed when the
model endpoint is unconfigured (HTTP 422).
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from . import dashboard
from .agent import Agent, Session
from .config import load_config
from .llm import LLMClient
from .observability import obs
from .orchestrator import Orchestrator
from .plugin import registry

MAX_BODY = 1 << 20  # 1 MiB


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, obj) -> None:
        """Send a JSON body."""
        self._send_text(code, json.dumps(obj, ensure_ascii=False),
                        "application/json; charset=utf-8")

    def _send_text(self, code: int, text: str, ctype: str) -> None:
        """Send a raw (non-JSON) body - required for HTML and Prometheus."""
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            return None
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def do_GET(self):
        if self.path in ("/", "/dashboard", "/index.html"):
            return self._send_text(200, dashboard.render(),
                                   "text/html; charset=utf-8")
        if self.path == "/health":
            return self._send(200, {"status": "ok", "version": __version__})
        if self.path == "/metrics":
            # Prometheus exposition format - plain text, NOT JSON-encoded
            return self._send_text(200, obs.prometheus(),
                                   "text/plain; version=0.0.4; charset=utf-8")
        if self.path.startswith("/sessions"):
            return self._send(200, {"sessions": Session.list_sessions()})
        return self._send(404, {"error": "not found"})

    def do_HEAD(self):
        """Health checkers and scrapers often probe with HEAD."""
        if self.path in ("/", "/dashboard", "/index.html"):
            return self._send_text(200, "", "text/html; charset=utf-8")
        if self.path == "/metrics":
            return self._send_text(200, "",
                                   "text/plain; version=0.0.4; charset=utf-8")
        if self.path == "/health" or self.path.startswith("/sessions"):
            return self._send_text(200, "", "application/json; charset=utf-8")
        return self._send_text(404, "", "application/json; charset=utf-8")

    def do_POST(self):
        try:
            data = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid JSON"})
        if data is None:
            return self._send(413, {"error": "payload too large"})
        if self.path == "/run":
            return self._handle_run(data)
        if self.path == "/team":
            return self._handle_team(data)
        return self._send(404, {"error": "not found"})

    def _handle_run(self, data: dict) -> None:
        goal = (data.get("goal") or "").strip()
        if not goal:
            return self._send(400, {"error": "missing goal"})
        client = LLMClient()
        if not client.configured:
            return self._send(422, {"error": "model endpoint not configured"})
        agent = Agent(role="executor", client=client)
        obs.inc("serve_run")
        res = agent.run(goal)
        self._send(200, {
            "final_text": res.final_text,
            "stopped_reason": res.stopped_reason,
            "steps": res.steps,
            "session_id": res.session_id,
        })

    def _handle_team(self, data: dict) -> None:
        goal = (data.get("goal") or "").strip()
        if not goal:
            return self._send(400, {"error": "missing goal"})
        client = LLMClient()
        if not client.configured:
            return self._send(422, {"error": "model endpoint not configured"})
        orch = Orchestrator(client=client)
        obs.inc("serve_team")
        res = orch.run(goal)
        self._send(200, {
            "success": res.success,
            "reports": [
                {"task_id": r.task_id, "verdict": r.verdict,
                 "issues": r.issues, "task": r.task}
                for r in res.reports
            ],
        })


def serve(host: str | None = None, port: int | None = None) -> None:
    """Start the service. Explicit host/port win over config defaults."""
    cfg = load_config()
    host = host or cfg.get("BAIZE_SERVE_HOST", "127.0.0.1")
    port = int(port or cfg.get("BAIZE_SERVE_PORT", 8787))
    try:
        registry.discover()
    except Exception:  # defensive: serving must not depend on plugins
        pass
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"baize serve listening on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
