"""Minimal HTTP server facade (`baize serve`) — pure stdlib.

Decomposed into ``baize/server/`` submodules (security, streaming, GET routes,
POST routes) while keeping all public & test-patched attributes on ``baize.interfaces.serve``.
"""
from __future__ import annotations

from .server.jobs import JobStore, SlidingWindowRateLimiter

import json
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__
from ..governance import bench as bench_mod
from ..governance import bench as bench_public_mod
from . import ui as dashboard
from ..governance import gate as gate_mod
from ..execution import proc as proc_mod
from ..core import sessions as sessions_mod
from ..core.agent import Agent, Session
from ..core.component import get_runtime
from ..core.config import load_config
from ..core.llm import LLMClient
from ..core.config import get_logger, setup_logging
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

# All former 501 stubs have been resolved in V40.1:
#   - 6 routes implemented for real (/team/dag, /api/git/apply_hunk,
#     /api/webhook/dispatch, /api/security/rbac, /api/tools/import, /api/ci/autofix)
#   - 5 legacy V30 demo routes retired below with HTTP 410 Gone
STUB_ROUTES: dict[str, str] = {}

RETIRED_ROUTES: dict[str, str] = {
    "/v30/speculative":
        "retired in V40.1 - use POST /v30/swarm/speculate for real git-worktree exploration",
    "/v30/speculative/merge":
        "retired in V40.1 - legacy demo timeline merge endpoint removed",
    "/v30/causal/heal":
        "retired in V40.1 - use POST /api/causal/mutation_test or baize.governance.mutation directly",
    "/api/vision/analyze":
        "retired in V40.1 - legacy UI palette demo endpoint removed",
    "/api/chaos/simulate":
        "retired in V40.1 - chaos testing lives in tests/core/test_llm_chaos.py, not as a production HTTP route",
}


def _retired_body(path: str) -> dict:
    """Response body for a retired route in :data:`RETIRED_ROUTES` (HTTP 410 Gone)."""
    reason = RETIRED_ROUTES[path]
    return {
        "error": "gone",
        "status": "retired",
        "path": path,
        "reason": reason,
        "message": f"该历史端点已正式下线（HTTP 410 Gone）：{reason}。",
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



_JOB_STORE: JobStore | None = None
_JOB_STORE_DB: str = ""
_RATE_LIMITER: SlidingWindowRateLimiter | None = None
_RATE_LIMITER_RPM: int = -1


def get_job_store(cfg: dict | None = None) -> JobStore:
    global _JOB_STORE, _JOB_STORE_DB
    cfg = cfg or load_config()
    db_path = str(Path(cfg.get("BAIZE_PERSISTENCE_DIR", "persistence")) / "jobs.sqlite3")
    workers = max(1, int(cfg.get("BAIZE_JOB_WORKERS", "2") or "2"))
    if _JOB_STORE is None or _JOB_STORE_DB != db_path:
        _JOB_STORE = JobStore(db_path, max_workers=workers)
        _JOB_STORE_DB = db_path
    return _JOB_STORE


def check_http_rate_limit(handler) -> tuple[bool, float]:
    global _RATE_LIMITER, _RATE_LIMITER_RPM
    rpm = int(load_config().get("BAIZE_HTTP_RPM", "0") or "0")
    if rpm <= 0:
        return True, 0.0
    if _RATE_LIMITER is None or _RATE_LIMITER_RPM != rpm:
        _RATE_LIMITER = SlidingWindowRateLimiter(max_requests=rpm, window_seconds=60.0)
        _RATE_LIMITER_RPM = rpm
    client_ip = (handler.client_address[0] if getattr(handler, "client_address", None) else "local")
    auth_hdr = (handler.headers.get("Authorization") or "")[:32]
    return _RATE_LIMITER.allow(f"{client_ip}:{auth_hdr}")


_SHUTTING_DOWN = False


def is_shutting_down() -> bool:
    return _SHUTTING_DOWN


def set_shutting_down(flag: bool) -> None:
    global _SHUTTING_DOWN
    _SHUTTING_DOWN = bool(flag)


def _live_deps() -> dict:
    """Resolve dependencies via baize.interfaces.serve globals so test monkeypatches apply."""
    return {
        "Agent": Agent,
        "LLMClient": LLMClient,
        "Orchestrator": Orchestrator,
        "SERVER_START_TIME": SERVER_START_TIME,
        "STUB_ROUTES": STUB_ROUTES,
        "RETIRED_ROUTES": RETIRED_ROUTES,
        "retired_body": _retired_body,
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
        "get_job_store": get_job_store,
        "version": __version__,
        "is_shutting_down": is_shutting_down,
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
        tp = getattr(self, "_traceparent", "")
        if tp:
            self.send_header("traceparent", tp)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            return None
        raw = self.rfile.read(length) if length else b"{}"
        self._raw_body = raw
        return json.loads(raw or b"{}")

    def _is_authorized(self, *, require_token: bool = False) -> bool:
        return _is_authorized_fn(self, require_token=require_token)

    def _req_path(self) -> str:
        return _req_path_fn(self.path)

    def _code_exec_gate(self):
        return _code_exec_gate_fn(self)

    def _init_trace_ctx(self, method: str):
        from ..governance.telemetry import format_traceparent, get_tracer
        tracer = get_tracer(load_config())
        cm = tracer.start_span(
            f"http.{method}",
            kind="SERVER",
            traceparent=self.headers.get("traceparent", ""),
            attributes={"http.method": method, "http.target": self._req_path()},
        )
        return cm, format_traceparent

    def do_GET(self):
        cm, fmt_tp = self._init_trace_ctx("GET")
        with cm as span:
            self._traceparent = fmt_tp(span.trace_id, span.span_id)
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
        cm, fmt_tp = self._init_trace_ctx("POST")
        with cm as span:
            self._traceparent = fmt_tp(span.trace_id, span.span_id)
            req_path = self._req_path()
            is_channel_webhook = (
                req_path.startswith("/api/channels/") and req_path.endswith("/webhook")
            )
            if not is_channel_webhook and not self._is_authorized():
                return self._send(401, {"error": "unauthorized: invalid or missing bearer token"})
            allowed, retry_after = check_http_rate_limit(self)
            if not allowed:
                return self._send(429, {
                    "error": "rate_limit_exceeded",
                    "retry_after_seconds": retry_after,
                })
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
    """Start the service with persisted config hydration, crash recovery, and graceful shutdown."""
    import signal
    import threading
    set_shutting_down(False)
    try:
        from ..governance.dlp import RuntimeConfigStore
        RuntimeConfigStore().apply_to_env(overwrite=False)
    except Exception:
        pass
    cfg = load_config()
    try:
        from ..execution.worktree import GitWorktreePool
        GitWorktreePool(workspace=cfg.get("BAIZE_WORKSPACE_DIR", ".")).recover_orphans()
    except Exception:
        pass
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

    def _graceful_stop(signum, _frame):
        set_shutting_down(True)
        log.info("received signal %s; draining connections...", signum)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
        if sig is not None:
            try:
                signal.signal(sig, _graceful_stop)
            except (ValueError, OSError):
                pass

    log.info("baize serve listening on http://%s:%s  (Ctrl+C to stop)", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        set_shutting_down(True)
    finally:
        set_shutting_down(True)
        try:
            from ..execution.bg_proc import get_bg_manager
            for p in get_bg_manager().list_procs():
                if p.get("running"):
                    get_bg_manager().stop(p["proc_id"])
        except Exception:
            pass
        try:
            from ..codebase.diagnostics import get_lsp_pool
            get_lsp_pool().shutdown_all()
        except Exception:
            pass
        try:
            from ..execution.docker_sandbox import get_docker_pool
            get_docker_pool().stop_all()
        except Exception:
            pass
        try:
            from ..execution.cdp_browser import get_browser_pool
            get_browser_pool().close_all()
        except Exception:
            pass
        try:
            from ..execution.compose_stack import get_compose_manager
            get_compose_manager().down_all()
        except Exception:
            pass
        try:
            from ..governance.telemetry import get_tracer
            get_tracer(cfg).flush_otlp(timeout=2.0)
        except Exception:
            pass
        httpd.server_close()
