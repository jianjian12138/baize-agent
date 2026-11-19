"""Minimal HTTP server facade (`baize serve`) — pure stdlib.

Decomposed into ``baize/server/`` submodules (security, streaming, GET routes,
POST routes) while keeping all public & test-patched attributes on ``baize.interfaces.serve``.
"""
from __future__ import annotations

import json
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__
from ..governance import bench as bench_mod
from ..governance import bench_public as bench_public_mod
from . import dashboard
from ..governance import gate as gate_mod
from ..execution import proc as proc_mod
from ..core import sessions as sessions_mod
from ..core.agent import Agent, Session
from ..core.component import get_runtime
from ..core.config import load_config
from ..core.llm import LLMClient
from ..core.logging_setup import get_logger, setup_logging
from ..governance.observability import obs
from ..orchestration.orchestrator import Orchestrator
from ..core.plugin import registry
from .server import (
    ENV_WRITE_LOCK as _ENV_WRITE_LOCK,
    INERT_SETTINGS_NOTE,
    MAX_BODY,
    SAFE_NAME_RE as _SAFE_NAME_RE,
    code_exec_gate as _code_exec_gate_fn,
    dispatch_get,
    dispatch_post,
    emit_cors as _emit_cors_fn,
    has_real_key as _has_real_key,
    is_authorized as _is_authorized_fn,
    req_path as _req_path_fn,
    safe_child_path as _safe_child_path,
    warn_about_auth_posture as _warn_posture_fn,
)

log = get_logger("serve")
SERVER_START_TIME = time.time()

STUB_ROUTES: dict[str, str] = {
    "/api/webhook/dispatch":
        "no outbound webhook is sent - no HTTP client is constructed or invoked",
    "/api/vision/analyze":
        "no multimodal model is called - the component list and colour palette "
        "were hardcoded literals",
    "/api/git/apply_hunk":
        "no patch is applied - no file is read, patched or written",
    "/api/ci/autofix":
        "no CI run is inspected and no pull request is opened - the PR number "
        "was a literal",
    "/team/dag":
        "no DAG is executed - the per-node verdicts and timings were literals",
    "/v30/speculative/merge":
        "no timeline is merged and no regression test is run",
    "/v30/causal/heal":
        "no mutation test is run - the 4/4 counts were literals",
    "/api/tools/import":
        "no tool is registered or hot-loaded - the handler echoed the request's "
        "own name back and returned status 'imported'",
    "/api/security/rbac":
        "no permission rule is applied and no signature is produced - the "
        "watermark was a hash of the current time",
    "/api/chaos/simulate":
        "no fault is injected and no recovery is observed - faults_injected, "
        "auto_healed and the 100% recovery rate were literals",
    "/v30/speculative":
        "no branch is explored - the three candidate timelines were constructed "
        "in the handler with literal churn_lines and status 'verified', and the "
        "engine then picked a winner among them",
}


def _stub_body(path: str) -> dict:
    """Response body for a route in :data:`STUB_ROUTES`."""
    reason = STUB_ROUTES[path]
    return {
        "error": "not_implemented",
        "status": "not_implemented",
        "path": path,
        "reason": reason,
        "message": (
            f"该端点尚未实现：{reason}。此前它返回的是硬编码的假成功响应，"
            f"现改为 501，以免把桩当作结果。"
        ),
    }


def _resolve_git() -> str | None:
    """Path to a usable git, or None."""
    override = (load_config().get("BAIZE_GIT_EXE") or "").strip()
    if override:
        return override if Path(override).exists() else None
    return shutil.which("git")


def _warn_about_auth_posture(cfg: dict) -> None:
    _warn_posture_fn(cfg, log)


def _live_deps() -> dict:
    """Resolve dependencies via baize.interfaces.serve globals so test monkeypatches apply."""
    return {
        "Agent": Agent,
        "LLMClient": LLMClient,
        "Orchestrator": Orchestrator,
        "SERVER_START_TIME": SERVER_START_TIME,
        "STUB_ROUTES": STUB_ROUTES,
        "Session": Session,
        "bench_mod": bench_mod,
        "bench_public_mod": bench_public_mod,
        "dashboard": dashboard,
        "gate_mod": gate_mod,
        "has_real_key": _has_real_key,
        "obs": obs,
        "proc_mod": proc_mod,
        "resolve_git": _resolve_git,
        "sessions_mod": sessions_mod,
        "stub_body": _stub_body,
        "version": __version__,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    runtime = None

    def _send(self, code: int, obj) -> None:
        self._send_text(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _emit_cors(self) -> bool:
        return _emit_cors_fn(self)

    def _send_text(self, code: int, text: str, ctype: str) -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self._emit_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            return None
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _is_authorized(self, *, require_token: bool = False) -> bool:
        return _is_authorized_fn(self, require_token=require_token)

    def _req_path(self) -> str:
        return _req_path_fn(self.path)

    def _code_exec_gate(self):
        return _code_exec_gate_fn(self)

    def do_GET(self):
        dispatch_get(self, self._req_path(), _live_deps())

    def do_HEAD(self):
        if self._req_path() == "/metrics":
            body = obs.prometheus().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if not self._is_authorized():
            return self._send(401, {"error": "unauthorized: invalid or missing bearer token"})
        try:
            data = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid JSON"})
        if data is None:
            return self._send(413, {"error": "payload too large"})
        dispatch_post(self, self._req_path(), data, _live_deps())

    def do_OPTIONS(self):
        self.send_response(204)
        if self._emit_cors():
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_DELETE(self):
        if not self._is_authorized():
            return self._send(401, {"error": "unauthorized: invalid or missing bearer token"})
        cfg = load_config()
        sessions_dir = Path(cfg.get("BAIZE_SESSIONS_DIR", "persistence/sessions"))
        req_path = self._req_path()
        if req_path in ("/sessions", "/sessions/all", "/sessions/clear"):
            count = 0
            if sessions_dir.exists():
                for f in sessions_dir.glob("*.jsonl"):
                    try:
                        f.unlink()
                        count += 1
                    except OSError:
                        pass
            return self._send(200, {"deleted_count": count, "message": "all sessions cleared"})
        if req_path.startswith("/sessions/"):
            sid = req_path[len("/sessions/"):].strip()
            p = _safe_child_path(sessions_dir, sid, suffix=".jsonl")
            if p is None:
                return self._send(400, {"error": "invalid session id"})
            if p.exists():
                p.unlink()
                return self._send(200, {"deleted": sid})
            return self._send(404, {"error": "session not found"})
        return self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # pragma: no cover
        return


def serve(host: str | None = None, port: int | None = None) -> None:
    """Start the service. Explicit host/port win over config defaults."""
    cfg = load_config()
    host = host or cfg.get("BAIZE_SERVE_HOST", "127.0.0.1")
    port = int(port or cfg.get("BAIZE_SERVE_PORT", 8787))
    try:
        registry.discover()
    except Exception:
        pass
    Handler.runtime = get_runtime()
    httpd = ThreadingHTTPServer((host, port), Handler)
    setup_logging(cfg)
    _warn_about_auth_posture(cfg)
    log.info("baize serve listening on http://%s:%s  (Ctrl+C to stop)", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
