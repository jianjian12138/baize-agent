"""baize.execution — Tool registry, sandboxes, subprocess control, and Windows/Docker execution."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "ToolRegistry": (".tools", "ToolRegistry"),
    "default_registry": (".tools", "default_registry"),
    "register_mcp_client": (".tools", "register_mcp_client"),
    "SandboxResult": (".sandbox", "SandboxResult"),
    "run_sandboxed": (".sandbox", "run"),
    "exec_restricted": (".sandbox", "exec_restricted"),
    "custom_tool": (".tools", "tool"),
    "discover_external_rules": (".tools", "discover_external_rules"),
    "load_external_rules": (".tools", "load_external_rules"),
    "run_proc": (".proc", "run"),
    "is_docker_available": (".docker_sandbox", "is_docker_available"),
    "Checkpoint": (".checkpoint", "Checkpoint"),
    "GitCheckpointManager": (".checkpoint", "GitCheckpointManager"),
    "SandboxPolicy": (".sandbox", "SandboxPolicy"),
    "sandbox_posture": (".sandbox", "sandbox_posture"),
    "resolve_sandbox_mode": (".sandbox", "resolve_sandbox_mode"),
    "scrub_environment": (".sandbox", "scrub_environment"),
    "BackgroundProcess": (".bg_proc", "BackgroundProcess"),
    "BackgroundProcessManager": (".bg_proc", "BackgroundProcessManager"),
    "get_bg_manager": (".bg_proc", "get_bg_manager"),
    "GitWorktreePool": (".worktree", "GitWorktreePool"),
    "WorktreeEntry": (".worktree", "WorktreeEntry"),
    "CDPBrowserClient": (".cdp_browser", "CDPBrowserClient"),
    "CDPUnavailableError": (".cdp_browser", "CDPUnavailableError"),
    "SimpleWebSocketClient": (".cdp_browser", "SimpleWebSocketClient"),
    "verify_url_with_cdp": (".browser_verify", "verify_url_with_cdp"),
    "SessionDockerPool": (".docker_sandbox", "SessionDockerPool"),
    "get_docker_pool": (".docker_sandbox", "get_docker_pool"),
    "landlock_driver": (".sandbox", "landlock_driver"),
    "VIEWPORT_PRESETS": (".visual_verify", "VIEWPORT_PRESETS"),
    "ViewportCapture": (".visual_verify", "ViewportCapture"),
    "VisualVerifyReport": (".visual_verify", "VisualVerifyReport"),
    "verify_ui": (".visual_verify", "verify_ui"),
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
