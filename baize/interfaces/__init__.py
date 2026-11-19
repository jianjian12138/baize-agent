"""baize.interfaces — CLI, REPL, HTTP/SSE server, dashboard, desktop UI, and setup wizard."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "cli_main": (".cli", "main"),
    "run_server": (".serve", "serve"),
    "render_dashboard": (".ui", "render"),
    "BaizeREPL": (".repl", "BaizeREPL"),
    "run_repl": (".repl", "run_repl"),
    "ApprovalRequest": (".approval", "ApprovalRequest"),
    "ApprovalDecision": (".approval", "ApprovalDecision"),
    "TieredApprovalPolicy": (".approval", "TieredApprovalPolicy"),
    "render_unified_diff": (".approval", "render_unified_diff"),
    "build_tool_preview": (".approval", "build_tool_preview"),
    "format_status_bar": (".approval", "format_status_bar"),
    "StreamJsonEmitter": (".rpc", "StreamJsonEmitter"),
    "RpcServer": (".rpc", "RpcServer"),
}

__all__ = list(_EXPORTS)

def __getattr__(name: str):
    if name in _EXPORTS:
        mod_path, attr = _EXPORTS[name]
        mod = importlib.import_module(mod_path, __name__)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
