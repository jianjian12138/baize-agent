"""Tests for the swarm's honesty contract.

The swarm used to be a simulation that reported hardcoded results: it created a
`tempfile.mkdtemp()` per branch, wrote nothing into it, ran no test, and returned
`tests_passed == total_tests == 4` for every branch - so its "winner" was decided
by a literal risk score and the numbers meant nothing.

It now really creates git worktrees and really measures churn. These tests pin the
properties that make that claim checkable, and in particular the three-valued
`verified` field:

    True  - a verify command ran and exited 0
    False - a verify command ran and exited non-zero
    None  - no verify command configured: NOT CHECKED, not "passed"

The None case is the one that matters most. Collapsing it to True would restore
exactly the fabrication this rewrite removed.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.swarm import (  # noqa: E402
    GitWorktreeSandbox,
    WorktreeSandbox,
    run_parallel_swarm_speculation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_worktree_list() -> str:
    return subprocess.run(
        ["git", "worktree", "list"], cwd=REPO_ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace").stdout


# ---------------------------------------------------------------------------
# the sandbox really is a worktree
# ---------------------------------------------------------------------------

def test_sandbox_creates_a_real_worktree_and_leaves_no_registration():
    before = _git_worktree_list()
    sb = WorktreeSandbox(base_repo=str(REPO_ROOT), branch_id="pytest_probe")
    path = sb.create()
    try:
        assert path.exists()
        if not sb.degraded:
            # A linked worktree has a .git FILE (a gitdir pointer), not a dir.
            assert (path / ".git").is_file(), "not a real linked worktree"
            assert "pytest_probe" in _git_worktree_list()
    finally:
        sb.cleanup()
    assert not path.exists()
    # The critical property: no dangling registration is left behind, and the
    # repository is back to exactly the worktrees it started with.
    assert _git_worktree_list() == before


def test_git_worktree_sandbox_is_an_alias_for_the_real_thing():
    sb = GitWorktreeSandbox(base_repo=str(REPO_ROOT), branch_id="pytest_alias")
    assert isinstance(sb, WorktreeSandbox)
    p = sb.create()
    try:
        assert p.exists()
    finally:
        sb.cleanup()


def test_non_repo_degrades_honestly(tmp_path):
    """A directory that is not a git repo must report degradation, not fake it."""
    sb = WorktreeSandbox(base_repo=str(tmp_path), branch_id="pytest_norepo")
    path = sb.create()
    try:
        assert sb.degraded is True
        assert sb.reason, "degradation must carry a reason"
        assert path.exists()
    finally:
        sb.cleanup()
    assert not path.exists()


# ---------------------------------------------------------------------------
# the result distinguishes measurement from input
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def unverified_result():
    """One swarm run with no verify command configured (the default)."""
    return run_parallel_swarm_speculation("pytest: honesty contract",
                                          base_repo=str(REPO_ROOT))


def test_no_verify_command_means_none_not_true(unverified_result):
    """The central honesty assertion."""
    for b in unverified_result["branches"]:
        assert b["verified"] is None, (
            f"{b['branch_id']} reports verified={b['verified']!r} with no verify "
            f"command configured - 'not checked' must never read as 'passed'"
        )
        assert b["verify_exit_code"] is None
    assert unverified_result["checked_branches"] == 0
    assert unverified_result["verified_branches"] == 0
    assert "no branch was checked" in unverified_result["message"]


def test_churn_is_measured_not_preset(unverified_result):
    for b in unverified_result["branches"]:
        assert b["churn_lines_measured"] is True
        assert isinstance(b["churn_lines"], int)
        assert b["churn_lines"] > 0, "the artifact was written, so churn cannot be 0"


def test_risk_score_is_labelled_as_an_input(unverified_result):
    """risk_score is a caller-supplied heuristic, and the payload says so."""
    for b in unverified_result["branches"]:
        assert b["risk_score_is_input"] is True


def test_isolation_is_reported_honestly(unverified_result):
    assert unverified_result["isolation"] in ("git-worktree", "scratch-dir-degraded")
    for b in unverified_result["branches"]:
        assert b["isolation"] in ("git-worktree", "scratch-dir-degraded")
        assert b["isolation_path"]
        # The path is cleaned up, so it must not still exist after the run.
        assert not Path(b["isolation_path"]).exists(), (
            "a branch sandbox survived the run"
        )


def test_no_test_counts_are_fabricated(unverified_result):
    """The old payload had tests_passed/total_tests hardcoded to 4."""
    for b in unverified_result["branches"]:
        assert "tests_passed" not in b
        assert "total_tests" not in b


def test_a_passing_verify_command_reports_true(monkeypatch):
    monkeypatch.setenv("BAIZE_SWARM_VERIFY_CMD", "git status --porcelain")
    res = run_parallel_swarm_speculation("pytest: verify pass",
                                         base_repo=str(REPO_ROOT))
    for b in res["branches"]:
        assert b["verified"] is True
        assert b["verify_exit_code"] == 0
    assert res["verified_branches"] == res["checked_branches"] > 0


def test_a_failing_verify_command_reports_false(monkeypatch):
    """A non-zero exit must produce verified=False, not a silent pass."""
    monkeypatch.setenv("BAIZE_SWARM_VERIFY_CMD",
                       "git rev-parse --verify refs/heads/pytest-no-such-ref")
    res = run_parallel_swarm_speculation("pytest: verify fail",
                                         base_repo=str(REPO_ROOT))
    for b in res["branches"]:
        assert b["verified"] is False
        assert b["verify_exit_code"] != 0
    assert res["verified_branches"] == 0
    assert res["checked_branches"] > 0


def test_cleanup_reports_a_leftover_it_could_not_remove(tmp_path, monkeypatch,
                                                        caplog):
    """A cleanup that did not happen must not be reported as one that did.

    ``cleanup`` used to clear ``self.path`` unconditionally after
    ``shutil.rmtree(..., ignore_errors=True)``. ``ignore_errors=True`` cannot say
    *why* a removal failed, and a host that requires confirmation for bulk
    deletion is one real cause - so a blocked cleanup was indistinguishable from
    a successful one. The path is now kept and a warning logged instead.
    """
    from baize import swarm

    sb = swarm.WorktreeSandbox(base_repo=str(tmp_path), branch_id="pytest_leftover")
    path = sb.create()
    assert path.exists()

    # Simulate every removal failing - the shape of a host that blocks deletes.
    monkeypatch.setattr(swarm.shutil, "rmtree", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING, logger="baize.swarm"):
        sb.cleanup()

    assert path.exists(), "the test did not actually leave anything behind"
    assert sb.path is not None, (
        "cleanup cleared the path although the directory survived - that reports "
        "a cleanup which never happened")
    assert any("left" in r.getMessage() for r in caplog.records), caplog.text

    # The leftover must stay retryable: once deletion is permitted, a second
    # cleanup finishes the job rather than being short-circuited by a None path.
    monkeypatch.undo()
    sb.cleanup()
    assert not path.exists()
    assert sb.path is None
