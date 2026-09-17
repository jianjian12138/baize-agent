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


# ---------------------------------------------- a failure must say why it failed
#
# `_verify` used to keep the exit code and discard stdout/stderr. A verify
# command then exited non-zero once in a full-suite run, and the resulting
# failure - `assert False is True` - could not be attributed to anything,
# because the reason had been thrown away at the point of failure. These tests
# drive `_verify` with a stubbed process result so the recorded text is pinned
# exactly, with no shell quoting in the way.


class _StubResult:
    def __init__(self, returncode=0, stdout="", stderr="", timed_out=False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out


class _StubSandbox:
    def __init__(self, path, degraded=False, reason=None):
        self.path = path
        self.degraded = degraded
        self.reason = reason


def _branch():
    from baize.swarm import CandidateBranch

    return CandidateBranch(branch_id="b1", title="t", strategy="s",
                           risk_score=0.1)


def _verify_with(monkeypatch, tmp_path, result, sandbox=None):
    from baize import swarm

    monkeypatch.setenv("BAIZE_SWARM_VERIFY_CMD", "a-verify-command")
    monkeypatch.setattr(swarm.proc_mod, "run", lambda *a, **k: result)
    branch = _branch()
    swarm._verify(branch, sandbox or _StubSandbox(tmp_path))
    return branch


def test_a_failing_verify_command_records_why(monkeypatch, tmp_path):
    """The reason must survive, not just the exit code."""
    branch = _verify_with(monkeypatch, tmp_path,
                          _StubResult(returncode=3, stderr="fatal: BOOM-marker\n"))
    assert branch.verified is False
    assert branch.verify_exit_code == 3
    assert "BOOM-marker" in branch.error
    assert "3" in branch.error, "the exit code must be in the message"


def test_a_passing_verify_command_records_no_error(monkeypatch, tmp_path):
    """Calibration: nothing is recorded when the command passes, so the test
    above cannot pass by writing a message unconditionally."""
    branch = _verify_with(monkeypatch, tmp_path, _StubResult(returncode=0))
    assert branch.verified is True
    assert branch.error is None


def test_a_timed_out_verify_command_says_so(monkeypatch, tmp_path):
    branch = _verify_with(monkeypatch, tmp_path,
                          _StubResult(returncode=-1, stderr="partial output",
                                      timed_out=True))
    assert branch.verified is False
    assert branch.verify_exit_code == -1
    assert "timed out" in branch.error
    assert "partial output" in branch.error


def test_a_silent_failure_is_reported_as_silent(monkeypatch, tmp_path):
    """No output is a fact about the command, and saying so beats an empty
    message that reads like 'no reason'."""
    branch = _verify_with(monkeypatch, tmp_path, _StubResult(returncode=1))
    assert branch.verified is False
    assert "no output" in branch.error


def test_stdout_is_used_when_stderr_is_empty(monkeypatch, tmp_path):
    """Some commands explain themselves on stdout; either stream is a reason."""
    branch = _verify_with(monkeypatch, tmp_path,
                          _StubResult(returncode=2, stdout="stdout-explains\n"))
    assert "stdout-explains" in branch.error


def test_a_very_long_failure_reason_is_truncated(monkeypatch, tmp_path):
    """A reason is a pointer, not a transcript: keep it bounded."""
    branch = _verify_with(monkeypatch, tmp_path,
                          _StubResult(returncode=1, stderr="x" * 5000))
    assert len(branch.error) < 500
    assert branch.error.endswith("...")


# ------------------------------------------------- degraded is not "failed"
#
# When `git worktree add` fails, `create()` falls back to a plain temp
# directory. A verify command run there tests the directory, not the candidate:
# `git status --porcelain` exits 128 ("not a git repository"). Reporting that as
# `verified=False` is indistinguishable from "the candidate failed
# verification". Reproduced with a non-repo base path: all three branches came
# back verified=False, rc=128, isolation=scratch-dir-degraded.


def test_a_degraded_sandbox_reports_not_checked_not_failed(monkeypatch, tmp_path):
    called = []
    from baize import swarm

    monkeypatch.setenv("BAIZE_SWARM_VERIFY_CMD", "a-verify-command")
    monkeypatch.setattr(swarm.proc_mod, "run",
                        lambda *a, **k: called.append(a) or _StubResult(128))

    branch = _branch()
    sandbox = _StubSandbox(tmp_path, degraded=True,
                           reason="base path is not a git repository")
    swarm._verify(branch, sandbox)

    assert branch.verified is None, (
        "a meaningless verify must be 'not checked', not 'failed'")
    assert branch.verify_exit_code is None
    assert "degraded" in branch.error
    assert "not a git repository" in branch.error
    assert called == [], "no verify command should be run outside the worktree"


def test_a_degraded_sandbox_ranks_above_a_failed_one(monkeypatch, tmp_path):
    """The module's own ranking: True, then None, then False. A branch we could
    not check must not be ranked below one that genuinely failed."""
    from baize.swarm import SwarmResult

    checked = _branch()
    checked.verified = True
    checked.risk_score = 0.9          # deliberately the riskiest of the three

    unchecked = _verify_with(monkeypatch, tmp_path, _StubResult(128),
                             sandbox=_StubSandbox(tmp_path, degraded=True,
                                                  reason="no worktree"))
    failed = _verify_with(monkeypatch, tmp_path, _StubResult(1, stderr="boom"))

    assert checked.verified is True
    assert unchecked.verified is None, "degraded must be not-checked"
    assert failed.verified is False, "a real failure is still a failure"

    res = SwarmResult(goal="g", branches=[failed, unchecked, checked],
                      total_elapsed_ms=1.0)
    assert res.winner is checked, "True must outrank None, which outranks False"
    rep = res.to_dict()
    assert rep["verified_branches"] == 1
    assert rep["checked_branches"] == 2, "an unchecked branch is not 'checked'"


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
