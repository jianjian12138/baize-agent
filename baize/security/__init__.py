"""baize.security — Quality gates, lifecycle hooks, and environment diagnostics."""
from ..gate import (
    run_gate, check_manifest, check_coverage, check_composition,
    check_quality, check_loop_integrity, MANIFEST_STALE_SECONDS
)
from ..hooks import HookRegistry, Hook, HookDecision
from ..doctor import run_checks, DoctorReport
from ..manifest import validate_manifest, ValidationResult

__all__ = [
    "run_gate", "check_manifest", "check_coverage", "check_composition",
    "check_quality", "check_loop_integrity", "MANIFEST_STALE_SECONDS",
    "HookRegistry", "Hook", "HookDecision",
    "run_checks", "DoctorReport",
    "validate_manifest", "ValidationResult",
]
