"""Tests for V30 Neuro-Symbolic Snapshot & Time-Travel Replay."""
import pytest
from baize.core.snapshot import ExecutionSnapshot, SnapshotStore
from baize.knowledge.replay import TimeTravelReplayer


def test_snapshot_serialization_and_storage(tmp_path):
    """ExecutionSnapshot correctly serializes to disk and reloads."""
    store = SnapshotStore(storage_dir=str(tmp_path))
    snap = ExecutionSnapshot(
        snapshot_id="snap_test_01",
        run_id="run_01",
        step_index=3,
        active_role="executor",
        assumptions=["items may be None"],
        decisions=["use defensive dict access"],
        facts=["process_user_order throws TypeError"],
        file_deltas={"main.py": "x = 10\n"},
        token_usage={"prompt": 500, "completion": 120}
    )
    saved_path = store.save(snap)
    assert saved_path.exists()

    loaded = store.load("snap_test_01")
    assert loaded is not None
    assert loaded.snapshot_id == "snap_test_01"
    assert loaded.active_role == "executor"
    assert loaded.assumptions == ["items may be None"]


def test_time_travel_replayer_scrubbing():
    """Replayer steps forward, backward, and seeks correctly."""
    snaps = [
        ExecutionSnapshot("s0", "r1", step_index=0, active_role="director", assumptions=[], decisions=[], facts=[], file_deltas={}, token_usage={}),
        ExecutionSnapshot("s1", "r1", step_index=1, active_role="planner", assumptions=["a1"], decisions=[], facts=[], file_deltas={}, token_usage={}),
        ExecutionSnapshot("s2", "r1", step_index=2, active_role="executor", assumptions=["a1"], decisions=["d1"], facts=[], file_deltas={}, token_usage={}),
    ]
    replayer = TimeTravelReplayer(snaps)
    assert replayer.current_step == 0
    assert replayer.current_frame.snapshot_id == "s0"

    f1 = replayer.step_forward()
    assert f1.snapshot_id == "s1"
    assert replayer.current_step == 1

    f2 = replayer.step_forward()
    assert f2.snapshot_id == "s2"

    # Step backward
    prev = replayer.step_backward()
    assert prev.snapshot_id == "s1"
    assert replayer.current_step == 1


def test_time_travel_fork_at_step():
    """Forking at a historical step generates a new session id inheriting state."""
    snaps = [
        ExecutionSnapshot("s0", "r1", step_index=0, active_role="director", assumptions=[], decisions=[], facts=[], file_deltas={}, token_usage={}),
        ExecutionSnapshot("s1", "r1", step_index=1, active_role="planner", assumptions=["a1"], decisions=[], facts=[], file_deltas={}, token_usage={}),
    ]
    replayer = TimeTravelReplayer(snaps)
    new_session_id = replayer.fork_at_step(1)
    assert new_session_id.startswith("fork_s1_")
