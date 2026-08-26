"""V26-A1: ProjectContract — atomic task contract schema and validation.

Implements the lightweight ProjectContract concept described in the V26 upgrade
plan (§3.2) and specified in openspec/specs/baize-agent/v26-contract.md.

Key design decisions:
- Pure stdlib only (json, dataclasses, pathlib) — Red Line A.
- Does NOT replace the manifest; contract files are manifest evidence.
- Does NOT create a parallel project state system — Red Line C/D.
- fail-closed: unknown check types produce errors, not silent passes.
- Forward-compatible: unknown JSON fields are silently ignored.

State transitions (§3.2):
    pending → in_progress → verified → done
    in_progress → failed

'verified' only appears in the run ledger (persistence/runs/<run-id>.jsonl).
When writing back to manifest, use 'done'. This avoids modifying the
P1–P12 fact model.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "AtomicTask",
    "ProjectContract",
    "ValidationResult",
    "load_contract",
    "save_contract",
    "validate_contract",
]

# Valid status values for AtomicTask
VALID_TASK_STATUS = {"pending", "in_progress", "verified", "done", "failed"}

# Valid check types — fail-closed: anything else is an ERROR
VALID_CHECK_TYPES = {"file_exists", "file_contains", "cmd_ok"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AtomicTask:
    """A single atomic unit of work within a ProjectContract.

    Every field maps directly to the OpenSpec §3.1 schema.
    Unknown fields passed via **kwargs are silently dropped (forward compat).
    """
    id: str
    goal: str
    prerequisites: list[str] = field(default_factory=list)
    allowed_roles: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    workspace_scope: str = ""
    expected_artifacts: list[dict] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    verifier_criterion: str = ""
    failure_reasons: list[str] = field(default_factory=list)
    max_retries: int = 1
    skill_candidate_condition: str = ""
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "prerequisites": list(self.prerequisites),
            "allowed_roles": list(self.allowed_roles),
            "allowed_tools": list(self.allowed_tools),
            "workspace_scope": self.workspace_scope,
            "expected_artifacts": list(self.expected_artifacts),
            "evidence_paths": list(self.evidence_paths),
            "checks": list(self.checks),
            "verifier_criterion": self.verifier_criterion,
            "failure_reasons": list(self.failure_reasons),
            "max_retries": self.max_retries,
            "skill_candidate_condition": self.skill_candidate_condition,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AtomicTask":
        """Deserialize from a dict. Unknown keys are silently ignored."""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


@dataclass
class ProjectContract:
    """Container for a run's atomic tasks.

    Relates to manifest as evidence (task_decomposition.json).
    Does NOT replace or duplicate manifest phase state.
    """
    run_id: str
    project: str
    goal: str
    created_at: str
    tasks: list[AtomicTask] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "goal": self.goal,
            "created_at": self.created_at,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectContract":
        """Deserialize from a dict. Unknown top-level keys are silently ignored."""
        tasks = [AtomicTask.from_dict(t) for t in d.get("tasks", [])]
        return cls(
            run_id=str(d.get("run_id", "")),
            project=str(d.get("project", "")),
            goal=str(d.get("goal", "")),
            created_at=str(d.get("created_at", "")),
            tasks=tasks,
        )


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_contract(path: str | Path) -> ProjectContract:
    """Load a ProjectContract from a JSON file.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file is not valid JSON.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"contract file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"contract file is not valid JSON: {exc}") from exc
    return ProjectContract.from_dict(data)


def save_contract(contract: ProjectContract, path: str | Path) -> None:
    """Serialize a ProjectContract to a JSON file (atomic write via temp+rename)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(contract.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)


def validate_contract(contract: ProjectContract) -> ValidationResult:
    """Validate a ProjectContract against the V26 schema rules.

    All validation is fail-closed:
    - Unknown check types → ERROR (not silent pass)
    - Missing required fields → ERROR
    - Semantic issues → WARNING

    Returns a ValidationResult with errors and warnings lists.
    """
    res = ValidationResult()

    # --- Contract-level checks ---
    if not contract.tasks:
        res.errors.append("contract must contain at least one task")
        return res  # no point checking tasks if there are none

    # --- Task-level checks ---
    seen_ids: set[str] = set()
    all_ids: set[str] = {t.id for t in contract.tasks}

    for task in contract.tasks:
        prefix = f"task {task.id!r}"

        # id uniqueness
        if task.id in seen_ids:
            res.errors.append(f"duplicate task id: {task.id!r}")
        seen_ids.add(task.id)

        # required non-empty fields
        if not str(task.goal).strip():
            res.errors.append(f"{prefix}: 'goal' must not be empty")
        if not str(task.verifier_criterion).strip():
            res.errors.append(f"{prefix}: 'verifier_criterion' must not be empty")

        # max_retries must be >= 0
        if not isinstance(task.max_retries, int) or task.max_retries < 0:
            res.errors.append(
                f"{prefix}: 'max_retries' must be an integer >= 0, "
                f"got {task.max_retries!r}"
            )

        # status must be valid
        if task.status not in VALID_TASK_STATUS:
            res.errors.append(
                f"{prefix}: invalid status {task.status!r} "
                f"(allowed: {sorted(VALID_TASK_STATUS)})"
            )

        # prerequisites must resolve within this contract
        for prereq in task.prerequisites:
            if prereq not in all_ids:
                res.errors.append(
                    f"{prefix}: prerequisite {prereq!r} not found in contract tasks"
                )

        # checks validation (fail-closed)
        for i, chk in enumerate(task.checks or []):
            ctype = str(chk.get("type", ""))
            cprefix = f"{prefix} check[{i}]"
            if ctype not in VALID_CHECK_TYPES:
                res.errors.append(
                    f"{cprefix}: unknown check type {ctype!r} "
                    f"(allowed: {sorted(VALID_CHECK_TYPES)}) — fail-closed"
                )
                continue
            if ctype == "file_contains":
                if "text" not in chk or not str(chk.get("text", "")).strip():
                    res.errors.append(
                        f"{cprefix}: file_contains check requires a non-empty 'text' field"
                    )
            if ctype == "cmd_ok":
                if "cmd" not in chk or not str(chk.get("cmd", "")).strip():
                    res.errors.append(
                        f"{cprefix}: cmd_ok check requires a non-empty 'cmd' field"
                    )

        # warnings
        if task.status in ("verified", "done") and not task.evidence_paths:
            res.warnings.append(
                f"{prefix}: status={task.status!r} but 'evidence_paths' is empty "
                "(NO FAKE DONE — add evidence paths)"
            )
        if task.workspace_scope and not task.allowed_roles:
            res.warnings.append(
                f"{prefix}: 'workspace_scope' is set but 'allowed_roles' is empty "
                "(any role can access the workspace)"
            )

    return res


def new_contract(run_id: str, project: str, goal: str,
                 tasks: list[AtomicTask] | None = None) -> ProjectContract:
    """Convenience constructor for a new ProjectContract with a timestamp."""
    return ProjectContract(
        run_id=run_id,
        project=project,
        goal=goal,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        tasks=tasks or [],
    )
