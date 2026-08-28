"""V30 Speculative Time-Travel Forking Engine (Pure Python Standard Library).

Allows the agent to explore multiple parallel/speculative timelines in memory
or shadow workspaces, scoring them objectively and atomically merging the
winning diff without real workspace corruption.
"""
from __future__ import annotations

import difflib
import os
import pathlib
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SpeculativeTimeline:
    timeline_id: str
    strategy: str  # minimal_patch | modular_refactor | contract_driven
    status: str = "pending"  # pending | running | verified | failed
    score: float = 0.0
    checks_passed: int = 0
    total_checks: int = 0
    churn_lines: int = 0
    duration_ms: int = 0
    modified_files: dict[str, str] = field(default_factory=dict)  # rel_path -> content
    error_message: str | None = None


class VirtualWorkspace:
    """Manages an isolated ephemeral filesystem sandbox for speculative exploration."""

    def __init__(self, source_dir: str):
        self.source_dir = pathlib.Path(source_dir).resolve()
        self._temp_dir = tempfile.TemporaryDirectory(prefix="baize_shadow_")
        self.path = pathlib.Path(self._temp_dir.name)
        self._copy_source()

    def _copy_source(self) -> None:
        """Copies source files into shadow space ignoring transient folders."""
        ignore = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "persistence")
        for item in self.source_dir.iterdir():
            dest = self.path / item.name
            if item.is_dir():
                if item.name in {".git", "__pycache__", ".pytest_cache", "persistence"}:
                    continue
                shutil.copytree(item, dest, ignore=ignore)
            else:
                shutil.copy2(item, dest)

    def diff_from_source(self) -> dict[str, str]:
        """Calculates modified files compared to the original workspace."""
        modified = {}
        for root, _, filenames in os.walk(self.path):
            for f in filenames:
                shadow_file = pathlib.Path(root) / f
                rel_path = shadow_file.relative_to(self.path).as_posix()
                orig_file = self.source_dir / rel_path
                content = shadow_file.read_text(encoding="utf-8", errors="replace")
                if not orig_file.exists():
                    modified[rel_path] = content
                else:
                    orig_content = orig_file.read_text(encoding="utf-8", errors="replace")
                    if content != orig_content:
                        modified[rel_path] = content
        return modified

    def cleanup(self) -> None:
        """Clean up the shadow temporary directory."""
        try:
            self._temp_dir.cleanup()
        except Exception:
            pass


class SpeculativeEngine:
    """Evaluates multiple speculative timelines and applies the best diff."""

    def __init__(self, workspace: str | None = None):
        self.workspace = pathlib.Path(workspace).resolve() if workspace else None

    def evaluate_timeline(self, timeline: SpeculativeTimeline) -> float:
        """Calculates a multi-dimensional score for a timeline."""
        if timeline.status != "verified" or timeline.total_checks == 0:
            timeline.score = 0.0
            return 0.0

        # Check ratio [0.0, 1.0]
        check_ratio = timeline.checks_passed / max(1, timeline.total_checks)

        # Churn penalty: more churn lines decrease score slightly
        churn_penalty = min(0.3, (timeline.churn_lines / 200.0) * 0.3)

        # Speed bonus
        speed_score = max(0.0, 1.0 - (timeline.duration_ms / 5000.0)) * 0.1

        # Composite score
        score = (0.6 * check_ratio) + (0.3 * (1.0 - churn_penalty)) + speed_score
        timeline.score = round(max(0.0, min(1.0, score)), 4)
        return timeline.score

    def select_and_merge(self, timelines: list[SpeculativeTimeline]) -> SpeculativeTimeline:
        """Picks the highest-scoring verified timeline and writes files to workspace."""
        for t in timelines:
            self.evaluate_timeline(t)

        sorted_timelines = sorted(timelines, key=lambda t: (t.score, -t.churn_lines), reverse=True)
        winner = sorted_timelines[0]

        if winner.score > 0 and self.workspace:
            for rel_path, content in winner.modified_files.items():
                target_file = self.workspace / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content, encoding="utf-8")

        return winner
