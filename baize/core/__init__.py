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
    "validate_config": (".config", "validate"),
    "ConfigError": (".config", "ConfigError"),
    "SCHEMA": (".config", "SCHEMA"),
    "Session": (".sessions", "Session"),
    "AutonomyPolicy": (".autonomy", "AutonomyPolicy"),
    "READONLY_TOOLS": (".autonomy", "READONLY_TOOLS"),
    "build_policy": (".autonomy", "build_policy"),
    "resolve_mode": (".autonomy", "resolve_mode"),
    "VALID_MODES": (".autonomy", "VALID_MODES"),
    "CompositionKernel": (".component", "CompositionKernel"),
    "Kind": (".component", "Kind"),
    "Component": (".component", "Component"),
    "PluginRegistry": (".plugin", "PluginRegistry"),
    "HTTPConnPool": (".llm", "HTTPConnPool"),
    "setup_logging": (".config", "setup_logging"),
    "get_logger": (".config", "get_logger"),
    "ToolProfileManager": (".context_engine", "ToolProfileManager"),
    "SpilloverResult": (".context_engine", "SpilloverResult"),
    "CompactionReport": (".context_engine", "CompactionReport"),
    "spill_tool_output": (".context_engine", "spill_tool_output"),
    "compact_messages_structured": (".context_engine", "compact_messages_structured"),
    "estimate_context_ratio": (".context_engine", "estimate_context_ratio"),
    "PluginScope": (".plugin_lifecycle", "PluginScope"),
    "HotReloadPluginManager": (".plugin_lifecycle", "HotReloadPluginManager"),
    "get_plugin_manager": (".plugin_lifecycle", "get_plugin_manager"),
    "build_session_tree": (".sessions", "build_session_tree"),
    "format_session_tree": (".sessions", "format_session_tree"),
    "rewind_session": (".sessions", "rewind_session"),
    "CostLedger": (".cost_ledger", "CostLedger"),
    "BudgetStatus": (".cost_ledger", "BudgetStatus"),
    "BudgetExceededError": (".cost_ledger", "BudgetExceededError"),
    "get_cost_ledger": (".cost_ledger", "get_cost_ledger"),
    "encode_image_part": (".llm", "encode_image_part"),
    "ProviderCircuitBreaker": (".llm", "ProviderCircuitBreaker"),
    "get_circuit_breaker": (".llm", "get_circuit_breaker"),
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
