"""baize.governance — NO FAKE DONE verification gates, manifests, observability, benchmarks, and doctor."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "run_gate": (".gate", "run_gate"),
    "validate_manifest": (".gate", "validate_manifest"),
    "obs": (".observability", "obs"),
    "DoctorReport": (".doctor", "DoctorReport"),
    "run_doctor": (".doctor", "run_checks"),
    "run_all": (".bench", "run_all"),
    "run_ast_mutation_arena": (".mutation", "run_ast_mutation_arena"),
    "Chaos": (".mutation", "Chaos"),
    "ChaosError": (".mutation", "ChaosError"),
    "EvalTask": (".eval_harness", "EvalTask"),
    "EvalRunSummary": (".eval_harness", "EvalRunSummary"),
    "run_eval_suite": (".eval_harness", "run_eval_suite"),
    "compare_runs": (".eval_harness", "compare_runs"),
    "load_external_eval_tasks": (".eval_harness", "load_external_eval_tasks"),
    "run_profile_comparison": (".eval_harness", "run_profile_comparison"),
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
