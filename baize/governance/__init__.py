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
    "EvalHistoryStore": (".eval_harness", "EvalHistoryStore"),
    "CODING_BENCH_TASKS": (".eval_harness", "CODING_BENCH_TASKS"),
    "run_coding_benchmark": (".eval_harness", "run_coding_benchmark"),
    "SecretFinding": (".dlp", "SecretFinding"),
    "InjectionFinding": (".dlp", "InjectionFinding"),
    "redact_secrets": (".dlp", "redact_secrets"),
    "redact_text": (".dlp", "redact_text"),
    "redact_payload": (".dlp", "redact_payload"),
    "scan_prompt_injection": (".dlp", "scan_prompt_injection"),
    "guard_untrusted_output": (".dlp", "guard_untrusted_output"),
    "check_egress_url": (".dlp", "check_egress_url"),
    "AuditLedger": (".dlp", "AuditLedger"),
    "get_audit_ledger": (".dlp", "get_audit_ledger"),
    "RuntimeConfigStore": (".dlp", "RuntimeConfigStore"),
    "OTelSpan": (".telemetry", "OTelSpan"),
    "Tracer": (".telemetry", "Tracer"),
    "get_tracer": (".telemetry", "get_tracer"),
    "format_traceparent": (".telemetry", "format_traceparent"),
    "parse_traceparent": (".telemetry", "parse_traceparent"),
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
