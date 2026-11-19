"""baize.interfaces — CLI, REPL, HTTP/SSE server, dashboard, desktop UI, and setup wizard."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "cli_main": (".cli", "main"),
    "run_server": (".serve", "serve"),
    "render_dashboard": (".dashboard", "render"),
    "BaizeREPL": (".repl", "BaizeREPL"),
    "run_repl": (".repl", "run_repl"),
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
