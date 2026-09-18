"""Parallel swarm speculation over real git worktrees.

What is real here (measured, not asserted)
------------------------------------------
  * each branch gets an actual ``git worktree`` - a second checkout of this
    repository at ``BAIZE_SWARM_GIT_REF``, created with ``git worktree add`` and
    removed with ``git worktree remove``;
  * the branch's candidate code is written into that worktree, so the isolation
    is used rather than merely created;
  * ``churn_lines`` is measured with ``git diff --numstat`` inside the worktree;
  * if ``BAIZE_SWARM_VERIFY_CMD`` is set, it is executed inside the worktree and
    ``verified`` / ``verify_exit_code`` report what actually happened.

What is still an input, not a measurement
-----------------------------------------
The three candidate strategies and their ``risk_score`` values are hypotheses
supplied by the caller (or the defaults below). ``risk_score`` is a heuristic
weight, not an observation. Nothing here invents a test result: when no verify
command is configured, ``verified`` is ``None`` - "not checked" - never ``True``.

Degrading honestly
------------------
If the base path is not a git repository with at least one commit, worktrees
cannot be created. The sandbox then falls back to a scratch directory and the
result says so: ``isolation`` becomes ``scratch-dir-degraded``. It never reports
worktree isolation it did not achieve.

Filesystem cost, and what a host's deletion guard does and does not see
------------------------------------------------------------------------
Each branch is a full second checkout of this repository - ~1100 files here -
and cleanup deletes it. The primary path is ``git worktree remove --force``,
which removes the tree through git's own implementation. A host that intercepts
Python's ``os.remove`` / ``shutil.rmtree`` and the shell's ``rm`` / ``unlink`` /
``rmdir`` (WorkBuddy's safe-delete shim does exactly that) therefore does *not*
see those deletions - verified by listing that shim's wrapped-command directory,
which contains ``rm``, ``rmdir`` and ``unlink`` but not ``git``. The fallback
``shutil.rmtree`` *is* a Python call and *is* subject to such a guard; since it
runs with ``ignore_errors=True``, a block used to be swallowed silently, so
``cleanup`` now logs the leftover and keeps the path set instead of reporting a
cleanup that did not happen.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import proc as proc_mod
from .config import load_config

logger = logging.getLogger("baize.swarm")

__all__ = [
    "CandidateBranch",
    "SwarmResult",
    "WorktreeSandbox",
    "GitWorktreeSandbox",
    "run_parallel_swarm_speculation",
]

#: git invocations are short by nature; a hung git must not hang the swarm.
GIT_TIMEOUT = 60

#: `git worktree add`/`remove` mutate shared state under .git/worktrees and take
#: the same lock file, so concurrent invocations can fail with "index.lock
#: exists". Branches run in parallel threads (see _run_all_async), so every git
#: call is serialized through this. The verify command - the slow part - is
#: deliberately NOT under the lock.
#:
#: Scope, stated because the earlier wording ("every git call is serialized")
#: read as more than it is: this is a `threading.Lock`, so it serializes the git
#: calls of *this process* and nothing else. `.git/worktrees` is shared by every
#: process that touches the repository, and nothing here takes a cross-process
#: file lock (no `O_EXCL`, `flock`, `msvcrt` or `filelock` anywhere under
#: baize/). A `git worktree prune` from another process is therefore outside this
#: lock's reach - and it is not harmless: measured on this host, `prune` deletes
#: the registrations of *live* worktrees, leaving each one reporting
#: `fatal: not a git repository: (NULL)` for every git command.
_GIT_LOCK = threading.Lock()


def _resolve_git() -> str | None:
    override = (load_config().get("BAIZE_GIT_EXE") or "").strip()
    if override:
        return override if Path(override).exists() else None
    return shutil.which("git")


@dataclass
class CandidateBranch:
    """One speculative branch. ``risk_score`` is an input; the rest is measured."""

    branch_id: str
    title: str
    strategy: str
    risk_score: float
    #: Measured by `git diff --numstat` inside the worktree. None = not measured.
    churn_lines: int | None = None
    #: Three-valued, and every value has more than one cause: True = ran and
    #: exited 0; False = ran and exited non-zero; None = NOT CHECKED, which is
    #: what you get when no command was configured, when the sandbox degraded,
    #: or when the branch crashed before verification. ``error`` says which.
    #: None must never be read as "passed".
    verified: bool | None = None
    verify_exit_code: int | None = None
    #: The command this branch was meant to verify with, recorded as soon as one
    #: is known to be configured - including when it never ran, so that "was
    #: meant to be verified but was not" stays distinguishable from "no command
    #: was configured at all". A value here with ``verify_exit_code is None``
    #: means the command was configured but not run.
    verify_command: str | None = None
    latency_ms: float = 0.0
    status: str = "pending"
    generated_code: str = ""
    #: Where the branch actually ran. Never a claim about a mechanism not used.
    isolation: str = "none"
    isolation_path: str | None = None
    artifact_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "title": self.title,
            "strategy": self.strategy,
            "risk_score": self.risk_score,
            "risk_score_is_input": True,
            "churn_lines": self.churn_lines,
            "churn_lines_measured": self.churn_lines is not None,
            "verified": self.verified,
            "verify_exit_code": self.verify_exit_code,
            "verify_command": self.verify_command,
            "latency_ms": round(self.latency_ms, 2),
            "status": self.status,
            "generated_code": self.generated_code,
            "isolation": self.isolation,
            "isolation_path": self.isolation_path,
            "artifact_path": self.artifact_path,
            "error": self.error,
        }


class WorktreeSandbox:
    """A real ``git worktree``, with an honest scratch-directory fallback.

    ``create()`` returns the path to use and sets :attr:`degraded`; it checks
    that the worktree is a usable repository before handing it over, because
    ``git worktree add`` can return 0 and still leave one that is not.
    ``cleanup()`` runs ``git worktree remove --force``, retrying with ``unlock``
    plus a second ``--force`` when that fails. It deliberately does *not* run
    ``git worktree prune``: ``prune`` is repository-wide and, measured on this
    host, deletes the registrations of other *live* worktrees, so a fallback
    prune would break the sibling branches of the run it is cleaning up after.
    """

    def __init__(self, base_repo: str = ".", branch_id: str = "branch_1",
                 ref: str = "HEAD"):
        self.base_repo = Path(base_repo).resolve()
        self.branch_id = branch_id
        self.ref = ref
        self.path: Path | None = None
        self.degraded = False
        self.reason: str | None = None

    # -- helpers ----------------------------------------------------------

    def _git(self, *args: str) -> proc_mod.Completed | None:
        exe = _resolve_git()
        if not exe:
            self.reason = "no git executable on PATH"
            return None
        with _GIT_LOCK:
            return proc_mod.run([exe, "-C", str(self.base_repo), *args],
                                timeout=GIT_TIMEOUT)

    def _usable_repo(self) -> bool:
        """A worktree needs a git repo *with a commit* to check out."""
        res = self._git("rev-parse", "--git-dir")
        if res is None or res.timed_out or res.returncode != 0:
            self.reason = self.reason or "base path is not a git repository"
            return False
        head = self._git("rev-parse", "--verify", self.ref)
        if head is None or head.timed_out or head.returncode != 0:
            self.reason = f"repository has no usable {self.ref} to check out"
            return False
        return True

    # -- lifecycle --------------------------------------------------------

    def create(self) -> Path:
        if not self._usable_repo():
            self.degraded = True
            self.path = Path(tempfile.mkdtemp(prefix=f"baize_wt_{self.branch_id}_"))
            return self.path

        # Two attempts: `worktree add` can return 0 and still leave a worktree
        # that is not a repository. Measured on this host, a `git worktree prune`
        # deletes the registration of a *live* worktree, and that worktree then
        # reports `fatal: not a git repository: (NULL)` for every git command -
        # including the verify command, whose non-zero exit would otherwise be
        # recorded as `verified=False`, a verdict about a candidate that was
        # never run. Retrying is cheap; handing a dead worktree to the verify
        # step is not.
        #
        # The ordering story - "the registration is written before the `.git`
        # file, so a prune lands in the window between them" - was my first
        # explanation and it is not supported: `add` writes its `locked` file
        # first (measured, ~200ms in) and removes it only at the end, so the
        # entry is locked for the whole add; and the effect reproduces with no
        # add in flight at all, from a plain `add` followed by a plain `prune`.
        # What is established is the consequence, which is all this retry needs.
        for _attempt in (1, 2):
            target = Path(tempfile.mkdtemp(prefix=f"baize_wt_{self.branch_id}_"))
            # mkdtemp created the directory; `git worktree add` wants to create it.
            target.rmdir()
            res = self._git("worktree", "add", "--detach", str(target), self.ref)
            if res is None or res.timed_out or res.returncode != 0:
                self.degraded = True
                self.reason = ((res.stderr.strip() if res else "")
                               or "git worktree add failed")
                self.path = Path(tempfile.mkdtemp(prefix=f"baize_wt_{self.branch_id}_"))
                return self.path
            self.path = target
            if self.is_usable():
                return target
            self.reason = (
                "worktree add returned 0 but the worktree is not a usable git "
                "repository - every git command inside it fails with `not a git "
                "repository`, and a `git worktree prune` against this repository "
                "is one cause (measured here to delete the registration of a live "
                "worktree, without reporting that it did)")
            logger.warning("swarm %s: %s; retrying", self.branch_id, self.reason)
            # Deregister the worktree being abandoned. In the real failure the
            # registration is already gone - that is *why* it is dangling - so
            # this normally fails. It is a targeted `remove` rather than the
            # repo-wide `prune`, which is measured to delete the registrations of
            # other live worktrees.
            self._git("worktree", "remove", "--force", str(target))
            shutil.rmtree(target, ignore_errors=True)

        self.degraded = True
        self.path = Path(tempfile.mkdtemp(prefix=f"baize_wt_{self.branch_id}_"))
        return self.path

    def cleanup(self) -> None:
        if self.path is None:
            return
        if self.degraded:
            shutil.rmtree(self.path, ignore_errors=True)
        else:
            # --force: the branch may have written files. `remove` deregisters the
            # worktree, which is the whole job.
            res = self._git("worktree", "remove", "--force", str(self.path))
            if res is None or res.timed_out or res.returncode != 0:
                # A locked worktree is one reason `remove` fails; `unlock` plus a
                # second `--force` is the targeted way through it. Do NOT fall
                # back to `prune`: it is repository-wide, and it deletes the
                # registrations of *other* live worktrees - measured on this host,
                # including 4 of 4 worktrees in one loop, each left reporting
                # `fatal: not a git repository: (NULL)`. The branches of one swarm
                # run are concurrent, so that fallback would take out the siblings
                # of the run it is cleaning up after, and their verify would come
                # back as `verified=None` rather than as a tested candidate. A
                # registration left behind is inert by comparison, and the warning
                # below reports it.
                self._git("worktree", "unlock", str(self.path))
                self._git("worktree", "remove", "--force", "--force", str(self.path))
            if self.path.exists():
                shutil.rmtree(self.path, ignore_errors=True)
        if self.path.exists():
            # `ignore_errors=True` cannot say *why* it failed, and one real cause
            # is a host that guards bulk deletion. Setting self.path = None here
            # regardless would report a cleanup that did not happen, so the
            # leftover is reported and the path stays set for a retry.
            logger.warning(
                "swarm cleanup left %s behind: git worktree remove failed and "
                "shutil.rmtree could not finish. A host that requires "
                "confirmation for bulk deletion is one cause.", self.path)
            return
        self.path = None

    # -- measurement ------------------------------------------------------

    def measure_churn(self) -> int | None:
        """Lines added+removed by whatever was written into the worktree."""
        if self.path is None or self.degraded:
            return None
        add = self._git_here("add", "-A")
        if add is None or add.returncode != 0:
            return None
        res = self._git_here("diff", "--cached", "--numstat", self.ref)
        if res is None or res.returncode != 0:
            return None
        total = 0
        for line in res.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            for value in parts[:2]:
                if value.isdigit():
                    total += int(value)
        return total

    def _git_here(self, *args: str) -> proc_mod.Completed | None:
        exe = _resolve_git()
        if not exe or self.path is None:
            return None
        with _GIT_LOCK:
            return proc_mod.run([exe, "-C", str(self.path), *args],
                                timeout=GIT_TIMEOUT)

    def is_usable(self) -> bool:
        """Is this sandbox still a git repository that a verify command can speak for?

        ``create()`` recorded the isolation once; this re-checks it *now*. A
        worktree can be invalidated after it was created - observed as a dangling
        ``.git`` file whose target admin directory is gone, which makes every git
        command inside it exit 128 with ``fatal: not a git repository: (NULL)``.
        That is a fact about the worktree, not about the candidate, so a failing
        verify command must not be reported as a failed candidate.
        """
        if self.path is None or self.degraded:
            return False
        res = self._git_here("rev-parse", "--git-dir")
        return res is not None and not res.timed_out and res.returncode == 0


class GitWorktreeSandbox(WorktreeSandbox):
    """Backwards-compatible name for :class:`WorktreeSandbox`.

    Kept because it is the name external callers and older tests use. Unlike the
    previous holder of this name - which was a plain ``tempfile.mkdtemp()`` with
    no git involvement at all - this one really creates a worktree.
    """


@dataclass
class SwarmResult:
    goal: str
    branches: list[CandidateBranch]
    total_elapsed_ms: float
    winner: CandidateBranch = field(init=False)
    isolation: str = "git-worktree"

    def __post_init__(self) -> None:
        self.winner = self._elect_winner()
        if all(b.isolation.startswith("scratch-dir") for b in self.branches):
            self.isolation = "scratch-dir-degraded"

    def _elect_winner(self) -> CandidateBranch:
        """Elect a winner, preferring branches that actually verified.

        Ordering is explicit because the honest states are three-valued:
        True (verified), None (not checked), False (checked and failed).
        `verified is True` sorts first, then None, then False; ties break on the
        input risk score and then on measured churn. The previous version
        filtered on `tests_passed == total_tests`, which was vacuous - both were
        the literal 4 for every branch, so it never excluded anything.
        """
        rank = {True: 0, None: 1, False: 2}
        return min(self.branches, key=lambda b: (
            rank.get(b.verified, 1),
            b.risk_score,
            b.churn_lines if b.churn_lines is not None else 0,
        ))

    def _verify_note(self) -> str:
        """Explain the verification outcome, reading the reason off the branches.

        The previous version asserted one cause for "nothing was checked" -
        "no verify command configured" - without looking at anything. A run in
        which every branch degraded, and a run in which every branch crashed
        before the verify step, also end with nothing checked, and the summary
        then named a cause that was not true - in the body of a 200 response
        from ``POST /v30/swarm/speculate``. A sentence that states a reason has
        to read that reason off the data.
        """
        total = len(self.branches)
        verified = sum(1 for b in self.branches if b.verified is True)
        checked = sum(1 for b in self.branches if b.verified is not None)
        unchecked = total - checked

        if checked:
            note = f"{verified}/{checked} checked branches passed"
            if unchecked:
                # Silence about the gap is how "1/1 passed" gets read as "all
                # good" when 2 of the 3 branches were never checked at all.
                note += f"; {unchecked}/{total} branches were not checked"
            return note

        if all(b.verify_command is None and b.error is None for b in self.branches):
            return ("no verify command configured (BAIZE_SWARM_VERIFY_CMD); "
                    "no branch was checked")
        reason = next((b.error for b in self.branches if b.error), "reason not recorded")
        return (f"no branch was checked: {unchecked}/{total} branches never ran the "
                f"verify command ({reason})")

    def to_dict(self) -> dict[str, Any]:
        verified = sum(1 for b in self.branches if b.verified is True)
        checked = sum(1 for b in self.branches if b.verified is not None)
        verify_note = self._verify_note()
        return {
            "goal": self.goal,
            "total_elapsed_ms": round(self.total_elapsed_ms, 2),
            "branches_count": len(self.branches),
            "branches": [b.to_dict() for b in self.branches],
            "winner": self.winner.to_dict(),
            "isolation": self.isolation,
            "verified_branches": verified,
            "checked_branches": checked,
            "message": (
                f"Swarm 推演完成（隔离方式: {self.isolation}）：从 {len(self.branches)} "
                f"条策略路线中选出 [{self.winner.branch_id}]"
                f"（预设风险分 {self.winner.risk_score}, {self._churn_note()}）。"
                f"{verify_note}。"
            ),
        }

    def _churn_note(self) -> str:
        """Describe the winner's churn without claiming a measurement that never
        happened.

        ``churn_lines`` is None when a branch never reached ``measure_churn()``
        (it crashed, or the sandbox gave it nothing to measure). The summary
        used to interpolate it unconditionally as "实测代码抖动 None 行" - the
        word 实测 (measured) attached to a value that was not measured, which is
        the same defect as reporting a verdict from a stale data file.
        """
        if self.winner.churn_lines is None:
            return "代码抖动未测量"
        return f"实测代码抖动 {self.winner.churn_lines} 行"


def _verify_output_excerpt(res, limit: int = 300) -> str:
    """The most informative slice of a failed verify command's output.

    ``git`` explains itself on stderr; some commands only use stdout. A failure
    recorded without either is a failure nobody can diagnose - which is exactly
    what happened once: a verify command exited non-zero in a full-suite run,
    the exit code was kept and the reason thrown away, and the resulting test
    failure (`assert False is True`) could not be attributed to anything.
    """
    for stream in (res.stderr, res.stdout):
        text = (stream or "").strip()
        if text:
            return text if len(text) <= limit else text[:limit] + " ..."
    return "(no output)"


def _verify(branch: CandidateBranch, sandbox: WorktreeSandbox) -> None:
    """Run BAIZE_SWARM_VERIFY_CMD inside the worktree, if configured.

    ``verify_command`` is recorded as soon as a command is known to be
    configured, *before* the early returns. That is what lets a caller tell
    "this branch was meant to be verified and was not" apart from "no command
    was configured at all" - without it, a run in which every branch degraded
    is indistinguishable from a run with verification switched off, and the
    summary then names a cause it never checked.
    """
    cmd = (load_config().get("BAIZE_SWARM_VERIFY_CMD") or "").strip()
    if not cmd:
        # Not "passed" - not checked. None is the honest value.
        branch.verified = None
        return
    branch.verify_command = cmd
    if sandbox.path is None:
        branch.verified = None
        branch.error = ("not verified: the sandbox has no path, so there was "
                        "nowhere to run the verify command")
        return
    if sandbox.degraded:
        # The branch ran in a plain scratch directory, not a worktree, so a
        # verify command there says nothing about the candidate. Observed:
        # `git status --porcelain` exits 128 ("not a git repository") in that
        # directory, and `verified` became False - the same value as "the
        # candidate failed verification", which it is not. The module already
        # ranks None ("not checked") above False ("failed"), so the honest value
        # is None, with the degradation recorded as the reason.
        branch.verified = None
        branch.error = ("not verified: the sandbox degraded to a scratch "
                        f"directory ({sandbox.reason or 'reason not recorded'}), "
                        "so a verify command there would not test the candidate")
        return
    res = proc_mod.run(cmd, shell=True, timeout=300, cwd=str(sandbox.path))
    if res.timed_out:
        branch.verified = False
        branch.verify_exit_code = -1
        branch.error = ("verify command timed out after 300s; last output: "
                        + _verify_output_excerpt(res))
        return
    branch.verify_exit_code = res.returncode
    branch.verified = res.returncode == 0
    if not branch.verified:
        # A non-zero exit is a verdict about the *candidate* only if the sandbox
        # was still a usable repository while the command ran. Observed: a branch
        # whose `isolation` was recorded as `git-worktree` (i.e. not degraded)
        # failed with `fatal: not a git repository: (NULL)` / exit 128 - the
        # worktree had been invalidated underneath it. Recorded as `False`, that
        # reads as "the candidate failed verification": a verdict about a
        # candidate that was never tested, which is the one thing this module's
        # tri-state exists to prevent. Re-check the mechanism, not the message.
        if not sandbox.is_usable():
            branch.verified = None
            branch.error = (
                "not verified: the worktree was no longer a usable git "
                "repository when the verify command ran, so its exit code says "
                "nothing about the candidate (exit "
                f"{res.returncode}: " + _verify_output_excerpt(res) + ")")
            return
        # Keep the reason. A bare exit code is not a diagnosis.
        branch.error = (f"verify command exited {res.returncode}: "
                        + _verify_output_excerpt(res))


def _run_branch(branch: CandidateBranch, goal: str, base_repo: str, ref: str) -> None:
    """Create the branch's worktree, write its candidate, measure, verify, clean up."""
    start = time.perf_counter()
    branch.status = "running"
    sandbox = WorktreeSandbox(base_repo=base_repo, branch_id=branch.branch_id, ref=ref)
    try:
        path = sandbox.create()
        branch.isolation = ("scratch-dir-degraded" if sandbox.degraded
                            else "git-worktree")
        branch.isolation_path = str(path)
        if sandbox.degraded:
            branch.error = sandbox.reason

        # Actually use the isolation: write the candidate into the sandbox. The
        # previous implementation created a directory and wrote nothing into it,
        # which is why the isolation claim could not mean anything.
        artifact = load_config().get("BAIZE_SWARM_ARTIFACT",
                                     "baize_swarm_candidate.py")
        target = path / artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(branch.generated_code + "\n", encoding="utf-8")
        branch.artifact_path = str(target)

        branch.churn_lines = sandbox.measure_churn()
        _verify(branch, sandbox)
        branch.status = "completed"
    except Exception as exc:  # noqa: BLE001 - a failed branch is data, not a crash
        branch.status = "failed"
        branch.error = f"{type(exc).__name__}: {exc}"
    finally:
        sandbox.cleanup()
        branch.latency_ms = (time.perf_counter() - start) * 1000


#: Default candidate strategies. These are INPUTS - hypotheses to explore - not
#: measurements. `risk_score` is a heuristic prior supplied by the caller.
DEFAULT_STRATEGIES: tuple[dict[str, Any], ...] = (
    {
        "branch_id": "minimal_patch",
        "title": "路线 A: 极简外科手术修补",
        "strategy": "最小代码修改，零破坏性抖动",
        "risk_score": 0.12,
        "code": "# Minimal Surgical Patch\ndef handle(x):\n    return x + 1 if x >= 0 else 0",
    },
    {
        "branch_id": "modular_refactor",
        "title": "路线 B: 模块化解耦重构",
        "strategy": "提炼为独立单一职责类与接口",
        "risk_score": 0.28,
        "code": "# Clean Modular Refactor\nclass Handler:\n    def execute(self, x):\n        return max(0, x + 1)",
    },
    {
        "branch_id": "contract_driven",
        "title": "路线 C: 强契约防御性设计",
        "strategy": "OpenAPI/Type-Safe 严格断言前置",
        "risk_score": 0.15,
        "code": ('# Strict Contract Specification\n'
                 'def handle(x: int) -> int:\n'
                 '    """Guaranteed invariant x >= 0."""\n'
                 '    assert isinstance(x, int)\n'
                 '    return max(0, x + 1)'),
    },
)


async def _run_all_async(branches: list[CandidateBranch], goal: str,
                         base_repo: str, ref: str) -> None:
    """Run the branches concurrently in worker threads.

    Real parallelism, which is why every git call is serialized through
    :data:`_GIT_LOCK` - `git worktree add` is not safe to run concurrently against
    one repository. The verify command runs outside the lock, so the slow part is
    what actually overlaps.
    """
    await asyncio.gather(*[
        asyncio.to_thread(_run_branch, b, goal, base_repo, ref) for b in branches
    ])


def run_parallel_swarm_speculation(goal: str = "优化系统并发安全性",
                                   base_repo: str | None = None) -> dict[str, Any]:
    """Explore the candidate strategies in parallel git worktrees.

    Returns a result dict whose fields distinguish measurement from input - see
    the module docstring. ``goal`` is carried through for reporting and for a
    real implementation to consume; it does not currently select the strategies.

    ``base_repo`` defaults to the configured workspace, not to ``"."``: the
    server's working directory is not necessarily the repository the agent is
    working on, and silently branching from the wrong repo would be worse than
    degrading to a scratch directory.
    """
    cfg = load_config()
    if base_repo is None:
        base_repo = cfg.get("BAIZE_WORKSPACE_DIR") or "."
    ref = (cfg.get("BAIZE_SWARM_GIT_REF") or "HEAD").strip() or "HEAD"
    branches = [
        CandidateBranch(
            branch_id=spec["branch_id"], title=spec["title"],
            strategy=spec["strategy"], risk_score=spec["risk_score"],
            generated_code=spec["code"],
        )
        for spec in DEFAULT_STRATEGIES
    ]

    start_all = time.perf_counter()
    # asyncio.run() cannot be called from inside a running loop, which happens
    # when this is reached from an async caller (e.g. a server handler). Detect
    # that case and run the coroutine in a worker thread instead.
    try:
        asyncio.get_running_loop()
        inside_loop = True
    except RuntimeError:
        inside_loop = False

    if inside_loop:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(
                _run_all_async(branches, goal, base_repo, ref))).result()
    else:
        asyncio.run(_run_all_async(branches, goal, base_repo, ref))

    result = SwarmResult(goal=goal, branches=branches,
                         total_elapsed_ms=(time.perf_counter() - start_all) * 1000)
    return result.to_dict()
