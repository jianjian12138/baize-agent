"""baize.orchestration — Multi-agent coordination, task contracts, hooks, and run ledgers."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "Orchestrator": (".orchestrator", "Orchestrator"),
    "OrchestrationResult": (".orchestrator", "OrchestrationResult"),
    "SubtaskReport": (".orchestrator", "SubtaskReport"),
    "run_checks": (".orchestrator", "run_checks"),
    "ProjectContract": (".contract", "ProjectContract"),
    "AtomicTask": (".contract", "AtomicTask"),
    "load_contract": (".contract", "load_contract"),
    "validate_contract": (".contract", "validate_contract"),
    "RunLedger": (".run_ledger", "RunLedger"),
    "list_runs": (".run_ledger", "list_runs"),
    "Role": (".team", "Role"),
    "TeamConfig": (".team", "TeamConfig"),
    "load_roles": (".team", "load_roles"),
    "build_team": (".team", "build_team"),
    "SubagentDef": (".subagent", "SubagentDef"),
    "load_subagent": (".subagent", "load_subagent"),
    "build_scoped_registry": (".subagent", "build_scoped_registry"),
    "Hook": (".hooks", "Hook"),
    "HookDecision": (".hooks", "HookDecision"),
    "HookRegistry": (".hooks", "HookRegistry"),
    "AutomationStore": (".automations", "AutomationStore"),
    "AutomationScheduler": (".automations", "AutomationScheduler"),
    "IntentRouter": (".intent_router", "IntentRouter"),
    "route_goal": (".intent_router", "route_goal"),
    "get_system1_engine": (".system1", "get_system1_engine"),
    "RalphLoopEngine": (".ralph", "RalphLoopEngine"),
    "CoreInvariantsAnchor": (".invariants_anchor", "CoreInvariantsAnchor"),
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
