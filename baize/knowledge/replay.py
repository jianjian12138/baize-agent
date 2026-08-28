"""V30 Time-Travel Stepping Replayer & Forking Engine (Pure Python Stdlib).

Provides frame-by-frame scrubbing (forward, backward, seek) and historical timeline
forking across neuro-symbolic snapshots.
"""
from __future__ import annotations

import uuid
from typing import Sequence
from ..core.snapshot import ExecutionSnapshot


class TimeTravelReplayer:
    """Stepping replayer that traverses execution snapshots."""

    def __init__(self, snapshots: Sequence[ExecutionSnapshot]):
        if not snapshots:
            raise ValueError("Snapshots sequence cannot be empty")
        self.snapshots = list(snapshots)
        self.current_step = 0

    @property
    def current_frame(self) -> ExecutionSnapshot:
        return self.snapshots[self.current_step]

    def step_forward(self) -> ExecutionSnapshot:
        if self.current_step < len(self.snapshots) - 1:
            self.current_step += 1
        return self.current_frame

    def step_backward(self) -> ExecutionSnapshot:
        if self.current_step > 0:
            self.current_step -= 1
        return self.current_frame

    def jump_to_step(self, index: int) -> ExecutionSnapshot:
        if 0 <= index < len(self.snapshots):
            self.current_step = index
        return self.current_frame

    def fork_at_step(self, index: int) -> str:
        snap = self.jump_to_step(index)
        new_session_id = f"fork_{snap.snapshot_id}_{uuid.uuid4().hex[:6]}"
        return new_session_id
