"""Modular HTTP server package for Baize Agent.

Decomposes transport/security, SSE streaming, GET routes, and POST routes into
focused single-responsibility modules behind the ``baize.serve`` facade.
"""
from __future__ import annotations

from .security import (
    ENV_WRITE_LOCK,
    INERT_SETTINGS_NOTE,
    MAX_BODY,
    SAFE_NAME_RE,
    code_exec_gate,
    emit_cors,
    has_real_key,
    is_authorized,
    req_path,
    safe_child_path,
    warn_about_auth_posture,
)
from .routes_get import dispatch_get, handle_git_status_or_diff, handle_export_session
from .routes_post import dispatch_post
from .streaming import handle_run_stream

__all__ = [
    "ENV_WRITE_LOCK",
    "INERT_SETTINGS_NOTE",
    "MAX_BODY",
    "SAFE_NAME_RE",
    "code_exec_gate",
    "dispatch_get",
    "dispatch_post",
    "emit_cors",
    "handle_export_session",
    "handle_git_status_or_diff",
    "handle_run_stream",
    "has_real_key",
    "is_authorized",
    "req_path",
    "safe_child_path",
    "warn_about_auth_posture",
]
