"""Regression tests for ``baize/proc.py`` - the timeout must be *enforced*.

WHY THESE EXIST
    ``baize/proc.py`` was written for one reason: ``subprocess.run(cmd,
    shell=True, timeout=N)`` does not bound wall time on Windows. Python spawns
    ``cmd.exe /c <command>``; the timeout kills ``cmd.exe`` alone, the
    grandchild keeps the stdout pipe open, and the ``communicate()`` that
    ``subprocess.run`` performs internally blocks until the grandchild decides
    to exit. The caller is told "timed out" by a call that already ran to
    completion.

    The module shipped with no test asserting ``timed_out`` and no test touching
    ``kill_tree`` at all. Reverting ``run`` to ``subprocess.run`` would have left
    the entire suite green - and a fix that nothing can falsify is a fix nobody
    should trust. The wall-time assertions below are that falsification: under
    the revert they fail, because the call then takes as long as the sleeper
    sleeps.

    Measured on the authoring machine (Windows, timeout=0.5s, sleeper 11s):
    ``subprocess.run`` returned after 11.88s, ``proc.run`` after 1.44s.

FALSIFICATION (run before trusting these tests)
    Two wrong implementations were injected, each as a pytest plugin that
    rebinds ``baize.proc.run`` - no product code was touched:

      A. the naive one - ``subprocess.run(shell=True, timeout=...)``
      B. the plausible wrong fix - Popen, kill the direct child on timeout,
         drain with a bounded wait. Wall time IS bounded; the tree is not
         walked, so the grandchild is orphaned.

    Result:

      ============================  =============  ==============
      injected defect               wall-time      grandchild
      ============================  =============  ==============
      A - unbounded timeout         FAIL (10.82s)  pass (it waits
                                                   for the child)
      B - bounded, direct child     FAIL (stderr    FAIL (pid
          killed only                message)       survived)
      ============================  =============  ==============

    Neither test is redundant, and neither is sufficient alone: A is caught
    only by the wall-time bound, B only by the liveness check on the
    grandchild. A wall-time-only test would have called B a fix.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from baize import proc

#: The sleeper outlives the timeout by a wide margin.
SLEEP_SECONDS = 10
#: Long enough that Python has certainly started and written its pid file, short
#: enough that the test does not drag.
TIMEOUT = 2.5
#: Between TIMEOUT and SLEEP_SECONDS. A call that fails to bound wall time takes
#: ~SLEEP_SECONDS and trips this; an enforced one finishes in ~TIMEOUT + ~1s of
#: kill-and-drain overhead.
WALL_TIME_CEILING = 6.0


def _sleeper_script(tmp_path: Path, *, record_pid: bool) -> Path:
    """A script that optionally records its own pid and then sleeps."""
    lines = ["import os", "import sys", "import time"]
    if record_pid:
        lines.append("open(sys.argv[1], 'w').write(str(os.getpid()))")
    lines.append(f"time.sleep({SLEEP_SECONDS})")
    path = tmp_path / "sleeper.py"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _cmd(script: Path, *extra: str) -> str:
    """A shell command string, quoted for ``shell=True``."""
    return " ".join([f'"{sys.executable}"', f'"{script}"',
                     *(f'"{e}"' for e in extra)])


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _pid_alive(pid: int) -> bool:
    """Liveness check that must not disturb the target process.

    ``os.kill(pid, 0)`` is used on POSIX. On Windows it is not a probe - Python
    routes non-console signals to ``TerminateProcess`` - so ``tasklist`` is used
    instead, and a matching task is recognised by its CSV row (a miss prints an
    ``INFO``/``信息`` line instead, which never starts with a quote).
    """
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout.strip()
        return out.startswith('"')
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# --------------------------------------------------------------------------- #
# The contract that matters
# --------------------------------------------------------------------------- #

def test_run_bounds_wall_time_when_the_command_outlives_the_timeout(tmp_path):
    """The entire reason ``proc.py`` exists.

    Revert ``run`` to ``subprocess.run(shell=True, timeout=...)`` and this fails.
    """
    script = _sleeper_script(tmp_path, record_pid=False)
    started = time.monotonic()
    res = proc.run(_cmd(script), shell=True, timeout=TIMEOUT)
    elapsed = time.monotonic() - started

    assert res.timed_out is True
    assert elapsed < WALL_TIME_CEILING, (
        f"the timeout was not enforced: {elapsed:.2f}s wall for a "
        f"{TIMEOUT}s limit (sleeper runs {SLEEP_SECONDS}s)")
    assert res.returncode == -1
    assert "timed out" in res.stderr
    assert "process tree killed" in res.stderr


def test_run_kills_the_grandchild_not_only_the_shell(tmp_path):
    """``shell=True`` inserts a shell; killing only it leaves the work running."""
    pidfile = tmp_path / "child.pid"
    script = _sleeper_script(tmp_path, record_pid=True)

    res = proc.run(_cmd(script, pidfile), shell=True, timeout=TIMEOUT)

    assert res.timed_out is True
    assert pidfile.exists(), (
        "the sleeper never recorded a pid, so this test proves nothing about "
        "the grandchild - treat it as inconclusive, not as a pass")
    child_pid = int(pidfile.read_text(encoding="utf-8").strip())
    assert child_pid != os.getpid(), "the sleeper reported our own pid"
    assert not _pid_alive(child_pid), (
        f"pid {child_pid} survived the timeout: the shell was killed and its "
        f"child was orphaned")


def test_run_reports_a_nonzero_exit_without_claiming_a_timeout(tmp_path):
    """``timed_out`` must distinguish a kill from an exit."""
    script = _script(tmp_path, "fail.py", "import sys\nsys.exit(3)\n")
    res = proc.run(_cmd(script), shell=True, timeout=30)

    assert res.timed_out is False
    assert res.returncode == 3
    assert "timed out" not in res.stderr


# --------------------------------------------------------------------------- #
# The rest of the contract
# --------------------------------------------------------------------------- #

def test_run_returns_stdout_and_exit_code(tmp_path):
    script = _script(tmp_path, "hello.py", "print('hello from proc')\n")
    res = proc.run(_cmd(script), shell=True, timeout=30)

    assert res.timed_out is False
    assert res.returncode == 0
    assert "hello from proc" in res.stdout


def test_run_keeps_stdout_and_stderr_apart(tmp_path):
    script = _script(tmp_path, "noisy.py",
                     "import sys\n"
                     "print('to out')\n"
                     "print('to err', file=sys.stderr)\n")
    res = proc.run(_cmd(script), shell=True, timeout=30)

    assert "to out" in res.stdout
    assert "to err" in res.stderr
    assert "to err" not in res.stdout


def test_run_feeds_input_text_to_stdin(tmp_path):
    script = _script(tmp_path, "echo.py",
                     "import sys\nprint(sys.stdin.read().strip().upper())\n")
    res = proc.run(_cmd(script), shell=True, timeout=30, input_text="ping")

    assert res.timed_out is False
    assert res.stdout.strip() == "PING"


def test_run_honours_cwd(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    script = _script(sub, "where.py", "import os\nprint(os.getcwd())\n")
    res = proc.run(_cmd(script), shell=True, timeout=30, cwd=str(sub))

    assert res.returncode == 0
    # samefile rather than string equality: Windows may hand back a short (8.3)
    # or differently-cased spelling of the same directory.
    assert os.path.samefile(res.stdout.strip(), str(sub))


def test_run_passes_env_through(tmp_path):
    script = _script(tmp_path, "env.py",
                     "import os\nprint(os.environ.get('BAIZE_PROC_PROBE', ''))\n")
    env = dict(os.environ, BAIZE_PROC_PROBE="sentinel")
    res = proc.run(_cmd(script), shell=True, timeout=30, env=env)

    assert res.returncode == 0
    assert res.stdout.strip() == "sentinel"


def test_completed_defaults_to_not_timed_out():
    res = proc.Completed(0, "out", "err")

    assert res.timed_out is False


def test_kill_tree_never_raises_when_the_pid_is_gone():
    """It runs on a failure path; raising here would mask the timeout itself."""
    proc.kill_tree(2 ** 31 - 1)  # no live process holds this pid


# --------------------------------------------------------------------------- #
# preexec_fn: the landlock path's escape hatch from subprocess.run
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(os.name != "nt", reason="Popen rejects preexec_fn on Windows")
def test_preexec_fn_is_refused_on_windows_rather_than_silently_dropped(tmp_path):
    """A dropped preexec_fn means the landlock restriction never got applied.

    ``sandbox.py`` uses this argument to install a kernel restriction in the
    child. Ignoring it would produce a sandbox that reports success while
    confining nothing, so it must fail loudly instead.
    """
    script = _script(tmp_path, "noop.py", "print('x')\n")
    with pytest.raises(ValueError, match="preexec_fn"):
        proc.run(_cmd(script), shell=True, timeout=30, preexec_fn=lambda: None)


@pytest.mark.skipif(os.name == "nt", reason="preexec_fn is POSIX-only")
def test_preexec_fn_reaches_the_child(tmp_path):
    """The landlock branch needs it, so it must actually be forwarded."""
    marker = tmp_path / "marker"
    script = _script(tmp_path, "noop.py", "print('x')\n")

    def _record():
        marker.write_text("ran", encoding="utf-8")

    res = proc.run(_cmd(script), shell=True, timeout=30, preexec_fn=_record)

    assert res.returncode == 0
    assert marker.read_text(encoding="utf-8") == "ran"


# --------------------------------------------------------------------------- #
# The docstring's claim, checked instead of asserted
# --------------------------------------------------------------------------- #
#
# ``baize/proc.py`` used to open with "This is the only place in the package
# allowed to spawn a timed subprocess." Nothing checked it and it was **false**:
# an AST scan found 7 other `subprocess.*(..., timeout=...)` call sites. Two of
# them were real defects of the same class this module exists to prevent
# (`docker_sandbox` timed out and left the container running; the PowerShell
# fallback timed out and left the wrapped command running), one was on the live
# `git` tool path, and four were short probes.
#
# The claim is now the narrow, checkable one, and the two real defects were
# routed through ``proc.run``. The probes below are the remaining direct calls;
# each is a *claim* that it cannot leak a process tree. Adding a new direct
# timed spawn on an execution path fails this test.

#: ``(module path, enclosing function)`` -> why it may bypass ``proc.run``.
ALLOWED_DIRECT_TIMED_SPAWNS: dict[tuple[str, str], str] = {
    ("baize/docker_sandbox.py", "is_docker_available"):
        "`docker info` daemon probe, 5s, no child processes",
    ("baize/docker_sandbox.py", "_force_remove_container"):
        "`docker rm -f` cleanup for the timeout path, 30s, no child processes",
    ("baize/powershell.py", "kill_process_tree"):
        "`taskkill /F /T` is the tree killer itself",
    ("baize/powershell.py", "detect_wsl2_status"):
        "`wsl -l -q` probe, 3s",
    ("baize/powershell.py", "get_powershell_status"):
        "`$PSVersionTable` version probe, 5s",
}

#: Any `subprocess.<fn>` that accepts a timeout.
_SPAWN_FNS = ("run", "Popen", "call", "check_call", "check_output")


def _direct_timed_spawns() -> list[tuple[str, str, int]]:
    """Every ``subprocess.*(..., timeout=...)`` outside ``proc.py``.

    AST rather than grep: a line-oriented search cannot tell a keyword argument
    on a continuation line from one that is absent, and it counts *lines* where
    the question is about *calls*.
    """
    pkg_root = Path(proc.__file__).resolve().parent
    repo_root = pkg_root.parent
    found: list[tuple[str, str, int]] = []
    for path in sorted(pkg_root.rglob("*.py")):
        if path.name == "proc.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        rel = path.relative_to(repo_root).as_posix()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                f = call.func
                if not (isinstance(f, ast.Attribute) and f.attr in _SPAWN_FNS):
                    continue
                base = f.value
                if not (isinstance(base, ast.Name) and base.id == "subprocess"):
                    continue
                if not any(k.arg == "timeout" for k in call.keywords):
                    continue
                found.append((rel, fn.name, call.lineno))
    return found


def test_the_timed_spawn_scanner_sees_the_known_probes():
    """Calibrate the scanner before trusting its verdict.

    Without this, ``test_run_is_the_only_tree_killing_spawn`` would pass by
    finding nothing - an assertion about an empty list, i.e. the "gate that
    cannot fail" defect this package is about. Every allowlisted probe must be
    visible to the scanner, and the scanner must find at least one hit.
    """
    seen = {(f, fn) for f, fn, _ in _direct_timed_spawns()}
    assert seen, "the scanner found no timed spawns at all - it is broken"
    missing = sorted(set(ALLOWED_DIRECT_TIMED_SPAWNS) - seen)
    assert not missing, (
        f"the scanner did not see allowlisted probe(s) {missing}; the allowlist "
        f"has drifted from the code and is no longer guarding anything")


def test_run_is_the_only_tree_killing_spawn():
    """No timed spawn bypasses ``proc.run`` except the documented probes.

    Fails if someone adds ``subprocess.run(..., timeout=...)`` on an execution
    path. Fix by routing it through ``proc.run``; add it to
    ``ALLOWED_DIRECT_TIMED_SPAWNS`` only if it genuinely cannot leak a child.
    """
    unexpected = [
        (f, fn, line) for f, fn, line in _direct_timed_spawns()
        if (f, fn) not in ALLOWED_DIRECT_TIMED_SPAWNS
    ]
    assert not unexpected, (
        "timed spawn(s) bypassing proc.run and not on the allowlist: "
        + ", ".join(f"{f}:{line} in {fn}()" for f, fn, line in unexpected)
        + " - route them through proc.run (baize/proc.py), or allowlist them "
          "with the reason they cannot leak a process tree")
