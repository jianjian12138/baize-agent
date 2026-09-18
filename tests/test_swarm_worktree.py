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
import os
import shutil
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
        # `_verify` records *why* a verify command failed - `error` carries the
        # exit code plus a bounded output excerpt - but this assertion used to
        # report a bare `assert False is True`, so an intermittent failure in a
        # full-suite run stayed unattributable even though the reason had been
        # captured. That is the whole point of keeping the excerpt: surface it.
        assert b["verified"] is True, (
            f"{b['branch_id']}: `{b['verify_command']}` -> "
            f"exit={b['verify_exit_code']} status={b['status']} "
            f"error={b['error']!r}"
        )
        assert b["verify_exit_code"] == 0
    assert res["verified_branches"] == res["checked_branches"] > 0


def test_a_failing_verify_command_reports_false(monkeypatch):
    """A non-zero exit must produce verified=False, not a silent pass.

    The assertion carries the whole branch record, because there is a second way
    to reach a non-`False` value that is not a silent pass: `verified=None`
    means the worktree was not a usable repository *before* the command ran, so
    the command was never run and there is no exit code about the candidate.
    That is the honest answer for that situation, and this assertion has to say
    which one happened or the next reader cannot tell "the code regressed" from
    "the worktree was taken away" - which is exactly the ambiguity that made the
    original intermittent failure expensive to chase.
    """
    monkeypatch.setenv("BAIZE_SWARM_VERIFY_CMD",
                       "git rev-parse --verify refs/heads/pytest-no-such-ref")
    res = run_parallel_swarm_speculation("pytest: verify fail",
                                         base_repo=str(REPO_ROOT))
    for b in res["branches"]:
        assert b["verified"] is False, (
            f"{b['branch_id']}: `{b['verify_command']}` -> "
            f"exit={b['verify_exit_code']} status={b['status']} "
            f"isolation={b['isolation']} path={b['isolation_path']} "
            f"error={b['error']!r}"
        )
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
    """Models the sandbox interface `_verify` depends on.

    `is_usable` is part of that interface now: `_verify` asks it *before* running
    the command, so that a non-zero exit code is never read as a verdict about a
    candidate whose repository was already gone. A stub without it would not
    intercept - which is the failure mode to prefer, since it fails loudly.

    `usable` may be a list, in which case successive calls consume it (the last
    value sticks). That is what lets a test model "usable when the command ran,
    gone afterwards" without a real worktree.
    """

    def __init__(self, path, degraded=False, reason=None, usable=True):
        self.path = path
        self.degraded = degraded
        self.reason = reason
        self._usable_seq = list(usable) if isinstance(usable, (list, tuple)) else None
        self._usable = self._usable_seq[0] if self._usable_seq else usable

    def is_usable(self):
        if self._usable_seq is not None:
            # Read the current value first, *then* advance: advancing before
            # reading makes the first call return the second value, which is
            # exactly backwards for "usable when the command ran, gone later".
            self._usable = self._usable_seq[0]
            if len(self._usable_seq) > 1:
                self._usable_seq.pop(0)
        return self._usable


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


def test_a_verify_that_cannot_run_in_a_vanished_worktree_is_not_a_verdict(
        monkeypatch, tmp_path):
    """No usable repository before the command means the command does not run.

    Observed in a full-suite run: a branch whose `isolation` was recorded as
    `git-worktree` reported `fatal: not a git repository: (NULL)` / exit 128.
    Recorded as `verified=False` that reads as "the candidate failed
    verification" - a verdict about a candidate that was never tested.

    The check is a *precondition*, so there is no exit code to report: `None`,
    not 128. Carrying 128 here would claim a run that never happened.
    """
    branch = _verify_with(
        monkeypatch, tmp_path,
        _StubResult(returncode=128, stderr="fatal: not a git repository: (NULL)\n"),
        sandbox=_StubSandbox(tmp_path, usable=False))
    assert branch.verified is None, "an infrastructure failure is NOT a failed candidate"
    assert branch.verify_exit_code is None, "the command never ran, so it has no exit code"
    assert "worktree" in branch.error


def test_a_failure_that_already_happened_is_not_erased_by_a_later_teardown(
        monkeypatch, tmp_path):
    """A post-hoc check must not be able to launder a failing candidate.

    Regression guard for a defect introduced while fixing the one above:
    `is_usable()` was first evaluated *after* the command, so a branch whose
    verify command correctly failed (`fatal: Needed a single revision`, exit
    128) came back as `verified=None` - because its worktree was taken away a
    moment after the command had produced its exit code. Reproduced 4/4 in a
    clone run. "Not checked" is the value for a command that could not speak;
    it is not a place to put a failure out of sight.
    """
    branch = _verify_with(
        monkeypatch, tmp_path,
        _StubResult(returncode=128, stderr="fatal: Needed a single revision\n"),
        sandbox=_StubSandbox(tmp_path, usable=[True, False]))
    assert branch.verified is False, (
        "the command ran and failed; the worktree's later removal is not a reason "
        f"to erase that (error={branch.error!r})")
    assert branch.verify_exit_code == 128
    assert "Needed a single revision" in branch.error


def test_calibration_a_real_failure_in_a_live_worktree_is_still_false(
        monkeypatch, tmp_path):
    """The mirror of the test above, so it cannot pass by never saying False."""
    branch = _verify_with(
        monkeypatch, tmp_path,
        _StubResult(returncode=128, stderr="fatal: not a git repository: (NULL)\n"),
        sandbox=_StubSandbox(tmp_path, usable=True))
    assert branch.verified is False
    assert branch.verify_exit_code == 128
    assert "exited 128" in branch.error


def test_is_usable_is_false_once_the_worktree_registration_is_gone():
    """The mechanism behind that intermittent failure, reproduced directly.

    Removing a worktree's admin directory leaves its `.git` file pointing at
    nothing, and every git command inside then exits 128 with
    `fatal: not a git repository: (NULL)`. `is_usable()` is what lets `_verify`
    tell "the worktree was taken away" apart from "the candidate is broken".

    The admin directory is *renamed*, not deleted, and the observable effect is
    identical: the path recorded in the worktree's `.git` file stops existing.
    The reason is not tidiness. Deleting a directory that is not under the OS
    temp directory can be intercepted by a host's bulk-delete guard, which
    raises `SystemExit` - and `shutil.rmtree(..., ignore_errors=True)` does not
    swallow it, because `SystemExit` is a `BaseException`, not an `Exception`.
    Observed on this host: a full-suite run deletes enough files that the guard
    starts refusing, and this test then failed with
    `SAFE_DELETE_BULK_CONFIRM_REQUIRED ... targets: [".git/worktrees/..."]`
    while passing when the file was run alone. A rename is a move, not a
    delete, so no guard is involved and the test does not depend on how much
    ran before it.
    """
    sb = WorktreeSandbox(base_repo=str(REPO_ROOT), branch_id="pytest-usable", ref="HEAD")
    gitdir = None
    stash = None
    try:
        path = sb.create()
        assert not sb.degraded, sb.reason
        assert sb.is_usable() is True

        gitdir = Path(subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--absolute-git-dir"],
            capture_output=True, text=True).stdout.strip())
        assert gitdir.is_dir(), f"expected a real git dir, got {gitdir!r}"
        stash = gitdir.with_name(gitdir.name + ".stashed")
        os.rename(gitdir, stash)

        # The `.git` file survives and points at nothing - that is the signature
        # the verify command's error message reports as "(NULL)".
        assert (Path(path) / ".git").exists()
        assert sb.is_usable() is False
    finally:
        # Put the registration back before cleanup, so `cleanup` can deregister
        # the worktree normally instead of leaving a stale entry behind.
        if stash is not None and gitdir is not None and stash.is_dir() and not gitdir.exists():
            os.rename(stash, gitdir)
        sb.cleanup()


def test_a_worktree_that_is_born_dangling_is_retried(monkeypatch):
    """`worktree add` can return 0 and still leave an unusable worktree.

    Measured with a concurrent `git worktree prune`: 4 of 4 adds returned 0 and
    4 of 4 worktrees were unusable. Accepting one hands `verified=False` to the
    caller - a verdict about a candidate that was never run.
    """
    adds = {"n": 0}
    checks = {"n": 0}
    real_git = WorktreeSandbox._git

    def spy_git(self, *args):
        if args[:2] == ("worktree", "add"):
            adds["n"] += 1
        return real_git(self, *args)

    def fake_usable(self):
        checks["n"] += 1
        return checks["n"] > 1          # first worktree dangles, the retry is fine

    monkeypatch.setattr(WorktreeSandbox, "_git", spy_git)
    monkeypatch.setattr(WorktreeSandbox, "is_usable", fake_usable)

    sb = WorktreeSandbox(base_repo=str(REPO_ROOT), branch_id="pytest-retry", ref="HEAD")
    try:
        sb.create()
        assert adds["n"] == 2, "a dangling worktree must be retried, not accepted"
        assert sb.degraded is False
    finally:
        sb.cleanup()
        # The abandoned first attempt is deregistered by `create` itself; this is
        # belt-and-braces so a failing test cannot leave the repo dirty.
        # This prune is deliberate and is not a counter-example to the rule the
        # tests pin: it targets an entry whose worktree directory is already gone
        # (a known-stale registration), and no other worktree is live at this
        # point because the tests in this file run one at a time.
        subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "prune"],
                       capture_output=True, text=True)


def test_a_worktree_that_stays_dangling_degrades_honestly(monkeypatch):
    """If the retry also dangles, say so - do not hand over a dead worktree."""
    adds = {"n": 0}
    real_git = WorktreeSandbox._git

    def spy_git(self, *args):
        if args[:2] == ("worktree", "add"):
            adds["n"] += 1
        return real_git(self, *args)

    monkeypatch.setattr(WorktreeSandbox, "_git", spy_git)
    monkeypatch.setattr(WorktreeSandbox, "is_usable", lambda self: False)

    sb = WorktreeSandbox(base_repo=str(REPO_ROOT), branch_id="pytest-dangle", ref="HEAD")
    try:
        sb.create()
        assert adds["n"] == 2
        assert sb.degraded is True
        assert "prune" in sb.reason, "the likely cause must be named"
    finally:
        sb.cleanup()
        # This prune is deliberate and is not a counter-example to the rule the
        # tests pin: it targets an entry whose worktree directory is already gone
        # (a known-stale registration), and no other worktree is live at this
        # point because the tests in this file run one at a time.
        subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "prune"],
                       capture_output=True, text=True)


def _describe_git_calls(calls):
    """Render spied `_git` calls with their outcome.

    A bare "prune was called" is not a diagnosis: the assertion has to carry the
    exit code and stderr of the call that led there, or the next reader is back
    to guessing.
    """
    out = []
    for args, res in calls:
        if res is None:
            out.append(f"{' '.join(args)} -> None")
            continue
        stderr = (res.stderr or "").strip().replace("\n", " ")[:200]
        out.append(f"{' '.join(args)} -> rc={res.returncode} "
                   f"timed_out={getattr(res, 'timed_out', None)} stderr={stderr!r}")
    return out


def test_a_real_cleanup_never_prunes_the_repository(monkeypatch):
    """`prune` is repository-wide and deletes the registrations of live worktrees.

    Measured on this host: a plain `git worktree add` followed by a plain
    `git worktree prune` leaves the worktree reporting `fatal: not a git
    repository: (NULL)`; 4 of 4 worktrees died that way in one loop. The branches
    of one swarm run are concurrent, so `cleanup` must never issue it - not even
    when `remove` failed, which is when the old code did.

    The spy is installed *after* `create` so the calls it records are `cleanup`'s
    own: `create` also issues a `remove` when it abandons a worktree that is not
    a usable repository, and mixing the two would make this red for a reason that
    has nothing to do with cleanup.
    """
    sb = WorktreeSandbox(base_repo=str(REPO_ROOT), branch_id="pytest-noprune", ref="HEAD")
    sb.create()

    calls = []
    real_git = WorktreeSandbox._git

    def spy_git(self, *args):
        res = real_git(self, *args)
        calls.append((args, res))
        return res

    monkeypatch.setattr(WorktreeSandbox, "_git", spy_git)
    sb.cleanup()

    prunes = [(a, r) for a, r in calls if a[:2] == ("worktree", "prune")]
    assert not prunes, \
        f"cleanup must never prune; calls were: {_describe_git_calls(calls)}"

    removes = [(a, r) for a, r in calls if a[:2] == ("worktree", "remove")]
    assert removes, f"expected cleanup to remove the worktree; saw {_describe_git_calls(calls)}"
    res = removes[0][1]
    remove_failed = res is None or res.timed_out or res.returncode != 0
    if remove_failed:
        # `remove` can fail for reasons that belong to git or to the host rather
        # than to this code - one full-suite run had it fail for a freshly created
        # worktree, and the next run at the same commit was clean. The retry is
        # the targeted way through, and it must be what happened.
        unlocks = [a for a, _ in calls if a[:2] == ("worktree", "unlock")]
        assert unlocks, ("a failed remove must be retried by unlocking, not by "
                         f"pruning; calls were: {_describe_git_calls(calls)}")


def test_a_successful_remove_never_prunes(monkeypatch):
    """Deterministic counterpart: a remove that reported success must not prune.

    The test above drives the real `git worktree remove`, which is the right
    thing to do, but its outcome is a fact about git and the host: on a run
    where that command fails it pins the *other* direction. This one stubs the
    outcome, so the success direction is pinned on every run.
    """
    sb = WorktreeSandbox(base_repo=str(REPO_ROOT), branch_id="pytest-noprune-unit",
                         ref="HEAD")
    sb.create()

    calls = []
    real_git = WorktreeSandbox._git

    def spy_git(self, *args):
        calls.append(args)
        if args[:2] == ("worktree", "remove"):
            return _StubResult(returncode=0)          # a remove that did its job
        return real_git(self, *args)

    monkeypatch.setattr(WorktreeSandbox, "_git", spy_git)
    try:
        sb.cleanup()
        assert any(a[:2] == ("worktree", "remove") for a in calls), \
            f"expected cleanup to attempt a remove; saw {calls}"
        assert not any(a[:2] == ("worktree", "prune") for a in calls), \
            f"a remove that reported success must not be followed by a prune; saw {calls}"
    finally:
        # The stubbed remove deregistered nothing, so the registration is still
        # there (its directory is gone, so prune will collect it). Do that even
        # on failure, so a red test cannot leave the repository with a stale
        # entry for the next reader to trip over.
        # This prune is deliberate and is not a counter-example to the rule the
        # tests pin: it targets an entry whose worktree directory is already gone
        # (a known-stale registration), and no other worktree is live at this
        # point because the tests in this file run one at a time.
        subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "prune"],
                       capture_output=True, text=True)


def test_a_failed_remove_is_retried_by_unlocking_not_by_pruning(monkeypatch):
    """Calibration: a failed `remove` must still be dealt with - but not by prune.

    `remove --force` fails on a locked worktree (a `locked` file is left behind
    when `worktree add` is interrupted; one was observed reading
    "initializing"), and `git worktree unlock` plus a second `--force` is the
    targeted way through. The old fallback was `git worktree prune`, which is
    repository-wide and measured here to delete the registrations of *other* live
    worktrees. Leaking a registration is inert; taking out the siblings of the
    run being cleaned up is not.
    """
    calls = []
    real_git = WorktreeSandbox._git

    def spy_git(self, *args):
        calls.append(args)
        if args[:2] == ("worktree", "remove"):
            return None                      # simulate "could not deregister"
        return real_git(self, *args)

    monkeypatch.setattr(WorktreeSandbox, "_git", spy_git)
    sb = WorktreeSandbox(base_repo=str(REPO_ROOT), branch_id="pytest-fallback", ref="HEAD")
    sb.create()
    try:
        sb.cleanup()
        assert any(a[:2] == ("worktree", "unlock") for a in calls), \
            f"a failed remove must be retried via unlock; saw {calls}"
        forces = [a for a in calls if a[:2] == ("worktree", "remove")]
        assert len(forces) == 2, f"expected a second remove attempt; saw {calls}"
        assert forces[1][2:4] == ("--force", "--force"), \
            f"the retry must escalate to --force --force; saw {forces[1]}"
        assert not any(a[:2] == ("worktree", "prune") for a in calls), \
            f"cleanup must never prune; saw {calls}"
    finally:
        # This prune is deliberate and is not a counter-example to the rule the
        # tests pin: it targets an entry whose worktree directory is already gone
        # (a known-stale registration), and no other worktree is live at this
        # point because the tests in this file run one at a time.
        subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "prune"],
                       capture_output=True, text=True)


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


# ---------------------------------------------------------------------------
# the summary must not name a cause it never checked
#
# `to_dict()["message"]` is returned in the body of a 200 response from
# POST /v30/swarm/speculate (baize/serve.py), so a wrong reason here is a wrong
# reason told to a caller.
# ---------------------------------------------------------------------------

def _degraded_branches(monkeypatch, tmp_path, n=3):
    """n branches that were each meant to be verified but could not be."""
    out = []
    for i in range(n):
        b = _verify_with(monkeypatch, tmp_path, _StubResult(128),
                         sandbox=_StubSandbox(
                             tmp_path, degraded=True,
                             reason="base path is not a git repository"))
        b.branch_id = f"b{i}"
        b.isolation = "scratch-dir-degraded"
        out.append(b)
    return out


def test_a_fully_degraded_run_does_not_blame_the_config(monkeypatch, tmp_path):
    """Nothing was checked - but a verify command WAS configured. The summary
    used to assert "no verify command configured", a cause it never looked at."""
    from baize.swarm import SwarmResult

    res = SwarmResult(goal="g", branches=_degraded_branches(monkeypatch, tmp_path),
                      total_elapsed_ms=1.0)
    rep = res.to_dict()

    assert rep["checked_branches"] == 0
    assert "no verify command configured" not in rep["message"], (
        "the command was configured; only the sandbox degraded")
    assert "degraded" in rep["message"]
    assert "no branch was checked" in rep["message"]


def test_a_run_with_no_command_configured_still_says_so(monkeypatch, tmp_path):
    """Calibration: the genuine "nothing configured" case must keep saying it,
    or the test above would pass for a message that says nothing at all."""
    from baize.swarm import SwarmResult

    monkeypatch.delenv("BAIZE_SWARM_VERIFY_CMD", raising=False)
    branches = []
    for i in range(2):
        b = _branch()
        b.branch_id = f"b{i}"
        branches.append(b)

    res = SwarmResult(goal="g", branches=branches, total_elapsed_ms=1.0)
    rep = res.to_dict()

    assert rep["checked_branches"] == 0
    assert "no verify command configured" in rep["message"]


def test_a_branch_that_crashed_before_verifying_does_not_blame_the_config(monkeypatch, tmp_path):
    """A branch that raised never reached `_verify`, so nothing recorded whether
    a command was configured. Quote the error; do not invent the config as the
    reason."""
    from baize.swarm import SwarmResult

    b = _branch()
    b.status = "failed"
    b.error = "RuntimeError: BOOM-marker"

    res = SwarmResult(goal="g", branches=[b], total_elapsed_ms=1.0)
    rep = res.to_dict()

    assert rep["checked_branches"] == 0
    assert "no verify command configured" not in rep["message"]
    assert "BOOM-marker" in rep["message"]


def test_unchecked_branches_are_named_in_the_summary(monkeypatch, tmp_path):
    """"1/1 checked branches passed" is true and reads like "all good". Say how
    many branches were never checked."""
    from baize.swarm import SwarmResult

    checked = _branch()
    checked.verified = True
    res = SwarmResult(goal="g",
                      branches=[checked] + _degraded_branches(monkeypatch, tmp_path, n=2),
                      total_elapsed_ms=1.0)
    rep = res.to_dict()

    assert rep["checked_branches"] == 1
    assert rep["branches_count"] == 3
    assert "1/1 checked branches passed" in rep["message"]
    assert "2/3 branches were not checked" in rep["message"]


def test_a_degraded_branch_records_the_command_it_never_ran(monkeypatch, tmp_path):
    """The fact that makes the distinction possible: the command is recorded
    even when it is not run, so "meant to verify" != "no command configured"."""
    branch = _verify_with(monkeypatch, tmp_path, _StubResult(128),
                          sandbox=_StubSandbox(tmp_path, degraded=True, reason="x"))
    assert branch.verify_command == "a-verify-command"
    assert branch.verify_exit_code is None, "it never ran"
    assert branch.verified is None


def test_no_command_configured_leaves_the_command_unset(monkeypatch, tmp_path):
    """Calibration for the test above."""
    from baize import swarm

    monkeypatch.delenv("BAIZE_SWARM_VERIFY_CMD", raising=False)
    branch = _branch()
    swarm._verify(branch, _StubSandbox(tmp_path))

    assert branch.verify_command is None
    assert branch.error is None


def test_the_summary_does_not_call_an_unmeasured_churn_measured():
    """A branch that never reached `measure_churn()` has churn_lines=None. The
    summary used to render that as "实测代码抖动 None 行" - the word 实测
    (measured) attached to a value nobody measured."""
    from baize.swarm import SwarmResult

    b = _branch()
    b.churn_lines = None
    rep = SwarmResult(goal="g", branches=[b], total_elapsed_ms=1.0).to_dict()

    assert "实测" not in rep["message"]
    assert "代码抖动未测量" in rep["message"]


def test_the_summary_still_reports_a_measured_churn():
    """Calibration: a real measurement must still be reported as one, so the
    test above cannot pass for a message that never says 实测 at all."""
    from baize.swarm import SwarmResult

    b = _branch()
    b.churn_lines = 7
    rep = SwarmResult(goal="g", branches=[b], total_elapsed_ms=1.0).to_dict()

    assert "实测代码抖动 7 行" in rep["message"]


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
