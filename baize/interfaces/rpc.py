"""V41 Headless JSONL RPC Server & Stream-JSON Emitter (Pure Python Standard Library).

Enables IDE extensions (VSCode, Neovim, JetBrains), CI pipelines, and orchestrators
to embed Baize Agent over line-delimited JSON on stdin/stdout without an HTTP server.

Protocol:
  Inbound (stdin, one JSON object per line):
    {"id": "1", "method": "ping"}
    {"id": "2", "method": "run", "params": {"goal": "...", "tool_profile": "tiered"}}
    {"id": "3", "method": "steer", "params": {"message": "focus on unit tests"}}
    {"id": "4", "method": "approval_response", "params": {"request_id": "...", "approved": true, "scope": "once", "reason": ""}}
    {"id": "5", "method": "rewind", "params": {"node_id": "...", "restore_code": false}}
    {"id": "6", "method": "reload", "params": {"plugin_id": "..."}}
    {"id": "7", "method": "cancel"}
    {"id": "8", "method": "quit"}

  Outbound (stdout, one JSON object per line):
    {"event": "ready", "version": "..."}
    {"event": "token_delta", "data": {"text": "..."}}
    {"event": "approval_request", "data": {"request_id": "...", "tool": "...", "preview": "..."}}
    {"event": "tool_result", "data": {...}}
    {"event": "compacted", "data": {...}}
    {"event": "done", "id": "2", "data": {...}}
    {"event": "error", "id": "...", "error": "..."}
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from typing import Any, TextIO

from .. import __version__
from ..core.config import load_config
from .approval import ApprovalDecision, ApprovalRequest, TieredApprovalPolicy


class StreamJsonEmitter:
    """Thread-safe JSONL writer for ``baize run --output-format stream-json`` and ``baize rpc``."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout
        self._lock = threading.Lock()

    def emit(self, event: str, data: dict[str, Any] | None = None, *, req_id: str | None = None) -> None:
        frame: dict[str, Any] = {
            "event": event,
            "ts": round(time.time(), 3),
        }
        if req_id is not None:
            frame["id"] = req_id
        if data is not None:
            frame["data"] = data
        line = json.dumps(frame, ensure_ascii=False)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()


class RpcServer:
    """Bidirectional stdin/stdout JSONL RPC server wrapping a single Baize Agent session."""

    def __init__(
        self,
        *,
        cfg: dict[str, Any] | None = None,
        agent_factory=None,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        approval_mode: str | None = None,
    ) -> None:
        self.cfg = cfg or load_config()
        self.stdin = stdin or sys.stdin
        self.emitter = StreamJsonEmitter(stdout or sys.stdout)
        self._agent_factory = agent_factory
        mode = approval_mode or str(self.cfg.get("BAIZE_APPROVAL_MODE", "tiered"))
        self.approval_policy = TieredApprovalPolicy(mode=mode)

        self._lock = threading.Lock()
        self._active_agent: Any = None
        self._run_thread: threading.Thread | None = None
        self._pending_approvals: dict[str, tuple[threading.Event, list[ApprovalDecision]]] = {}

    def _make_approval_callback(self):
        def _cb(req: ApprovalRequest) -> ApprovalDecision:
            if not self.approval_policy.requires_approval(req.tool_name, req.arguments):
                return ApprovalDecision(approved=True, scope="session")
            req_id = req.request_id or f"apr-{uuid.uuid4().hex[:8]}"
            ev = threading.Event()
            holder: list[ApprovalDecision] = []
            with self._lock:
                self._pending_approvals[req_id] = (ev, holder)
            self.emitter.emit(
                "approval_request",
                {
                    "request_id": req_id,
                    "tool": req.tool_name,
                    "arguments": req.arguments,
                    "preview": req.preview,
                    "risk": req.risk,
                },
            )
            waited = ev.wait(timeout=300.0)
            with self._lock:
                self._pending_approvals.pop(req_id, None)
            if not waited or not holder:
                return ApprovalDecision(approved=False, scope="denied", reason="RPC approval timed out")
            dec = holder[0]
            if dec.approved and dec.scope == "session":
                self.approval_policy.record_session_allow(req.tool_name, req.arguments)
            return dec

        return _cb

    def _build_agent(self, params: dict[str, Any]):
        profile = params.get("tool_profile") or self.cfg.get("BAIZE_TOOL_PROFILE", "tiered")
        on_token = lambda delta: self.emitter.emit("token_delta", {"text": delta})
        on_event = lambda kind, payload: self.emitter.emit(kind, payload if isinstance(payload, dict) else {"value": payload})
        approval_cb = self._make_approval_callback()
        if self._agent_factory is not None:
            return self._agent_factory(
                cfg=self.cfg,
                on_token=on_token,
                on_event=on_event,
                approval_callback=approval_cb,
                tool_profile=profile,
            )
        from ..core.agent import Agent

        return Agent(
            cfg=self.cfg,
            on_token=on_token,
            on_event=on_event,
            approval_callback=approval_cb,
            tool_profile=profile,
        )

    def handle_frame(self, frame: dict[str, Any]) -> bool:
        """Process one decoded JSONL request. Returns False to stop the server."""
        req_id = str(frame.get("id") or "")
        method = str(frame.get("method") or "").strip().lower()
        params = frame.get("params") if isinstance(frame.get("params"), dict) else {}

        if method == "ping":
            self.emitter.emit("pong", {"version": __version__}, req_id=req_id)
            return True

        if method == "quit":
            self._cancel_active()
            self.emitter.emit("bye", {"ok": True}, req_id=req_id)
            return False

        if method == "approval_response":
            apr_id = str(params.get("request_id") or "")
            approved = bool(params.get("approved", False))
            scope = str(params.get("scope") or ("once" if approved else "denied"))
            reason = str(params.get("reason") or "")
            with self._lock:
                entry = self._pending_approvals.get(apr_id)
            if entry is None:
                self.emitter.emit("error", {"error": f"unknown approval request_id: {apr_id}"}, req_id=req_id)
                return True
            ev, holder = entry
            holder.append(ApprovalDecision(approved=approved, scope=scope, reason=reason))
            ev.set()
            self.emitter.emit("ack", {"request_id": apr_id, "approved": approved}, req_id=req_id)
            return True

        if method == "steer":
            msg = str(params.get("message") or "").strip()
            with self._lock:
                ag = self._active_agent
            if ag is None or not hasattr(ag, "steer"):
                self.emitter.emit("error", {"error": "no active run to steer"}, req_id=req_id)
                return True
            ag.steer(msg)
            self.emitter.emit("steered", {"message": msg}, req_id=req_id)
            return True

        if method == "cancel":
            self._cancel_active()
            self.emitter.emit("cancelled", {"ok": True}, req_id=req_id)
            return True

        if method == "rewind":
            from ..core.sessions import rewind_session

            sid = str(params.get("session_id") or "")
            node_id = str(params.get("node_id") or "")
            restore_code = bool(params.get("restore_code", False))
            res = rewind_session(
                sid,
                node_id,
                restore_code=restore_code,
                workspace=self.cfg.get("BAIZE_WORKSPACE_DIR", "."),
                cfg=self.cfg,
            )
            self.emitter.emit("rewound", res, req_id=req_id)
            return True

        if method == "reload":
            from ..core.plugin_lifecycle import get_plugin_manager

            plugin_id = str(params.get("plugin_id") or "")
            mgr = get_plugin_manager()
            with self._lock:
                ag = self._active_agent
            reg = ag.registry if ag is not None else None
            hooks = ag.hooks if ag is not None else None
            res = mgr.reload_plugin(plugin_id, registry=reg, hooks=hooks) if plugin_id else {"ok": False, "error": "plugin_id required"}
            self.emitter.emit("reloaded", res, req_id=req_id)
            return True

        if method == "run":
            goal = str(params.get("goal") or "").strip()
            if not goal:
                self.emitter.emit("error", {"error": "goal is required"}, req_id=req_id)
                return True
            if self._run_thread is not None and self._run_thread.is_alive():
                self.emitter.emit("error", {"error": "a run is already in progress; use steer or cancel"}, req_id=req_id)
                return True

            def _worker() -> None:
                try:
                    ag = self._build_agent(params)
                    with self._lock:
                        self._active_agent = ag
                    res = ag.run(goal)
                    self.emitter.emit(
                        "done",
                        {
                            "final_text": res.final_text,
                            "stopped_reason": res.stopped_reason,
                            "steps": res.steps,
                            "session_id": res.session_id,
                            "checkpoint_id": getattr(res, "checkpoint_id", ""),
                            "rolled_back": getattr(res, "rolled_back", False),
                        },
                        req_id=req_id,
                    )
                except Exception as exc:
                    self.emitter.emit("error", {"error": str(exc)}, req_id=req_id)
                finally:
                    with self._lock:
                        self._active_agent = None

            self._run_thread = threading.Thread(target=_worker, name="baize-rpc-run", daemon=True)
            self._run_thread.start()
            return True

        self.emitter.emit("error", {"error": f"unknown method: {method}"}, req_id=req_id)
        return True

    def _cancel_active(self) -> None:
        with self._lock:
            ag = self._active_agent
            pending = list(self._pending_approvals.values())
        if ag is not None and hasattr(ag, "request_interrupt"):
            ag.request_interrupt()
        for ev, holder in pending:
            holder.append(ApprovalDecision(approved=False, scope="denied", reason="Cancelled"))
            ev.set()

    def serve_forever(self) -> int:
        self.emitter.emit("ready", {"version": __version__, "protocol": "baize-jsonl-rpc/1.0"})
        for raw in self.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as exc:
                self.emitter.emit("error", {"error": f"invalid JSON: {exc}"})
                continue
            if not isinstance(frame, dict):
                self.emitter.emit("error", {"error": "request must be a JSON object"})
                continue
            if not self.handle_frame(frame):
                break
        if self._run_thread is not None and self._run_thread.is_alive():
            self._run_thread.join(timeout=5.0)
        return 0
