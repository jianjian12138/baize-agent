"""V30 Neuro-Symbolic State Checkpointing (Pure Python Standard Library).

Captures unified neuro-symbolic snapshots (assumptions, decisions, facts, active roles,
neural token usage, and filesystem deltas) with atomic serialization.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExecutionSnapshot:
    snapshot_id: str
    run_id: str
    step_index: int
    active_role: str
    assumptions: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    file_deltas: dict[str, str] = field(default_factory=dict)
    token_usage: dict[str, int] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionSnapshot:
        return cls(
            snapshot_id=data.get("snapshot_id", ""),
            run_id=data.get("run_id", ""),
            step_index=data.get("step_index", 0),
            active_role=data.get("active_role", "executor"),
            assumptions=data.get("assumptions", []),
            decisions=data.get("decisions", []),
            facts=data.get("facts", []),
            file_deltas=data.get("file_deltas", {}),
            token_usage=data.get("token_usage", {}),
            timestamp=data.get("timestamp", "")
        )


class SnapshotStore:
    """Manages snapshot disk persistence under persistence/snapshots/."""

    def __init__(self, storage_dir: str | None = None):
        if storage_dir:
            self.storage_dir = pathlib.Path(storage_dir).resolve()
        else:
            self.storage_dir = pathlib.Path("persistence/snapshots").resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: ExecutionSnapshot) -> pathlib.Path:
        target = self.storage_dir / f"{snapshot.snapshot_id}.json"
        tmp_target = self.storage_dir / f"{snapshot.snapshot_id}.tmp"
        with open(tmp_target, "w", encoding="utf-8") as f:
            json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp_target, target)
        return target

    def load(self, snapshot_id: str) -> ExecutionSnapshot | None:
        target = self.storage_dir / f"{snapshot_id}.json"
        if not target.exists():
            return None
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ExecutionSnapshot.from_dict(data)

    def list_snapshots(self, run_id: str | None = None) -> list[str]:
        results = []
        for p in self.storage_dir.glob("*.json"):
            if run_id:
                snap = self.load(p.stem)
                if snap and snap.run_id == run_id:
                    results.append(p.stem)
            else:
                results.append(p.stem)
        return sorted(results)
