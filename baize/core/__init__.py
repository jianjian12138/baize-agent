"""baize.core — Fundamental agent runtime, loop, configuration, and LLM interfaces."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "Agent": (".agent", "Agent"),
    "AgentResult": (".agent", "AgentResult"),
    "build_system_prompt": (".agent", "build_system_prompt"),
    "recall_context": (".agent", "recall_context"),
    "LLMClient": (".llm", "LLMClient"),
    "LLMError": (".llm", "LLMError"),
    "load_config": (".config", "load_config"),
    "ROOT": (".config", "ROOT"),
    "validate_config": (".config_schema", "validate"),
    "ConfigError": (".config_schema", "ConfigError"),
    "SCHEMA": (".config_schema", "SCHEMA"),
    "Session": (".sessions", "Session"),
    "AutonomyPolicy": (".autonomy", "AutonomyPolicy"),
    "READONLY_TOOLS": (".autonomy", "READONLY_TOOLS"),
    "build_policy": (".autonomy", "build_policy"),
    "resolve_mode": (".modes", "resolve_mode"),
    "VALID_MODES": (".modes", "VALID_MODES"),
    "CompositionKernel": (".component", "CompositionKernel"),
    "Kind": (".component", "Kind"),
    "Component": (".component", "Component"),
    "PluginRegistry": (".plugin", "PluginRegistry"),
    "HTTPConnPool": (".http_pool", "HTTPConnPool"),
    "setup_logging": (".logging_setup", "setup_logging"),
    "get_logger": (".logging_setup", "get_logger"),
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
