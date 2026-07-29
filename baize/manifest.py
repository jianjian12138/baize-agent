"""Project manifest validator.

A manifest.json drives the 12-phase pipeline (P1..P12). This module makes the
gate REAL: a phase may only be marked "done" when every evidence file it lists
actually exists on disk. Missing evidence -> validation error -> gate closed.

Expected shape:
{
  "project": "name",
  "version": "1.0.0",
  "phases": [
    {"id": "P1", "name": "...", "status": "done|in_progress|pending",
     "evidence": ["relative/or/absolute/path", ...]}
  ]
}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

VALID_STATUS = {"pending", "in_progress", "done", "skipped"}
PHASE_IDS = [f"P{i}" for i in range(1, 13)]


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_manifest(manifest_path: Path) -> ValidationResult:
    res = ValidationResult()
    manifest_path = Path(manifest_path)

    if not manifest_path.exists():
        res.errors.append(f"manifest not found: {manifest_path}")
        return res

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        res.errors.append(f"invalid JSON: {exc}")
        return res

    for key in ("project", "version", "phases"):
        if key not in data:
            res.errors.append(f"missing required field: {key}")
    if res.errors:
        return res

    phases = data["phases"]
    if not isinstance(phases, list) or not phases:
        res.errors.append("phases must be a non-empty list")
        return res

    base = manifest_path.parent
    seen_ids = set()
    for i, phase in enumerate(phases):
        pid = phase.get("id", f"<index {i}>")
        if pid in seen_ids:
            res.errors.append(f"duplicate phase id: {pid}")
        seen_ids.add(pid)

        if pid not in PHASE_IDS:
            res.warnings.append(f"non-standard phase id: {pid}")

        status = phase.get("status")
        if status not in VALID_STATUS:
            res.errors.append(f"{pid}: invalid status {status!r} "
                              f"(allowed: {sorted(VALID_STATUS)})")
            continue

        # THE GATE: "done" requires evidence files that physically exist.
        if status == "done":
            evidence = phase.get("evidence", [])
            if not evidence:
                res.errors.append(f"{pid}: status=done but no evidence listed "
                                  "(NO FAKE DONE)")
            for ev in evidence:
                ev_path = Path(ev)
                if not ev_path.is_absolute():
                    ev_path = base / ev
                if not ev_path.exists():
                    res.errors.append(f"{pid}: evidence missing on disk: {ev}")

    # Ordering sanity: a done phase must not come after a pending one.
    status_seq = [p.get("status") for p in phases]
    seen_pending = False
    for phase, status in zip(phases, status_seq):
        if status in ("pending", "in_progress"):
            seen_pending = True
        elif status == "done" and seen_pending:
            res.warnings.append(
                f"{phase.get('id')}: done after a pending/in_progress phase "
                "(pipeline order looks inconsistent)")

    return res


def format_result(res: ValidationResult) -> str:
    lines = []
    for e in res.errors:
        lines.append(f"[ERROR] {e}")
    for w in res.warnings:
        lines.append(f"[WARN]  {w}")
    lines.append("RESULT: " + ("VALID" if res.ok else "INVALID"))
    return "\n".join(lines)
