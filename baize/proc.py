"""Process execution whose timeout is actually enforced.

Why this exists
---------------
``subprocess.run(cmd, shell=True, timeout=N)`` does **not** bound wall time on
Windows. Python spawns ``cmd.exe /c <command>``; when the timeout fires it calls
``process.kill()``, which terminates ``cmd.exe`` alone. The grandchild the shell
started keeps running and keeps the stdout/stderr pipe handles open, so the
``communicate()`` that ``subprocess.run`` performs internally never reaches EOF
and blocks until the grandchild exits on its own.

Measured on this machine before the fix: a hook configured with ``timeout=0.5``
whose command slept ~11s returned after **11.35s** wall time. The caller was told
the hook timed out, and the timeout had not been enforced - the only reason the
call ever returned was that the grandchild eventually finished.

``run()`` below fixes that with three changes:

  1. the child is put in its own process group (POSIX) / new process group
     (Windows), so the tree can be addressed as a unit;
  2. on timeout the whole tree is killed - ``taskkill /F /T`` on Windows,
     ``killpg`` with SIGKILL on POSIX;
  3. the pipes are then drained with a *bounded* second wait, so a process that
     survives the kill cannot block the caller forever.

Point 3 matters as much as point 2: draining without a bound is how a "fixed"
timeout turns into an unbounded hang instead.

What ``run`` is, and is not, the only instance of
-------------------------------------------------
An earlier revision of this docstring said "this is the only place in the package
allowed to spawn a timed subprocess". That was **false**, and nothing asserted
it, so it stayed false. What is actually true, and is now checked by
``tests/test_proc_timeout.py::test_run_is_the_only_tree_killing_spawn``:

* ``run`` is the only place that puts the child in its own process group and
  kills the **whole tree** on timeout. Every other timed spawn in the package
  either is a short-lived probe (``docker info``, ``wsl -l -q``, the PowerShell
  version probe, ``taskkill`` itself) or has been routed through ``run``.
* ``sandbox.py``'s landlock branch used to be the last hold-out: it needs a
  ``preexec_fn`` to install the kernel restriction, so it kept calling
  ``subprocess.run`` directly and kept the unbounded timeout with it. ``run``
  therefore accepts ``preexec_fn`` and forwards it.
* ``docker_sandbox.py`` keeps a direct ``subprocess.run`` for the ``docker run``
  **client**, because killing that client does not stop the container - the leak
  is the container, not the process tree. It therefore gives the container an
  explicit name and force-removes it by name on timeout.

The enforceable claim is the narrow one: *tree-bounded timed spawns all go
through ``run``*. Widening it back to "all timed spawns" requires deleting the
probes and the docker client, which is not what anyone wants.
"""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass

__all__ = ["Completed", "kill_tree", "run"]

#: How long to wait for the pipes to close after killing the tree. Short on
#: purpose: the kill has already been issued, and this is only the drain.
DRAIN_TIMEOUT = 5.0

#: How long to wait for the OS to reap the killed tree.
KILL_TIMEOUT = 10.0


@dataclass
class Completed:
    """Result of :func:`run`. ``timed_out`` distinguishes a kill from an exit."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def kill_tree(pid: int) -> None:
    """Kill ``pid`` and every descendant. Never raises.

    Best-effort by design: the caller is already on a failure path, and an
    exception here would mask the timeout it is reporting.
    """
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=KILL_TIMEOUT)
        except Exception:  # noqa: BLE001 - best effort
            pass
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        # Already gone, or not ours to kill (no separate group). Fall back to
        # the single process so we still do not leave it running.
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def run(
    cmd,
    *,
    timeout: float,
    cwd: str | None = None,
    input_text: str | None = None,
    env: dict | None = None,
    shell: bool = False,
    encoding: str = "utf-8",
    preexec_fn=None,
) -> Completed:
    """Run ``cmd`` with a timeout that kills the whole process tree.

    ``timed_out=True`` means the tree was killed, not that the command exited.
    On timeout ``returncode`` is -1, which callers must not read as a real exit
    status.

    ``preexec_fn`` is forwarded to ``Popen`` and exists for the landlock sandbox
    path, which installs the kernel restriction in the child just before exec.
    It is POSIX-only: ``Popen`` rejects it on Windows, and a caller that passes
    it there has a bug, so this raises instead of silently dropping the
    restriction - a sandbox that quietly stops confining is worse than one that
    refuses to start.
    """
    popen_kwargs: dict = {}
    if os.name == "nt":
        if preexec_fn is not None:
            raise ValueError(
                "preexec_fn is not supported on Windows (Popen rejects it); "
                "the landlock sandbox path that needs it is Linux-only")
        # CREATE_NEW_PROCESS_GROUP so the console is not shared with the parent;
        # taskkill /T walks the tree from the pid regardless.
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        # Own session => own process group => killpg reaches every descendant,
        # including the shell that `shell=True` inserts.
        popen_kwargs["start_new_session"] = True
        if preexec_fn is not None:
            popen_kwargs["preexec_fn"] = preexec_fn

    stdin = subprocess.PIPE if input_text is not None else subprocess.DEVNULL
    proc = subprocess.Popen(
        cmd,
        shell=shell,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        text=True,
        encoding=encoding,
        errors="replace",
        **popen_kwargs,
    )

    try:
        out, err = proc.communicate(input=input_text, timeout=timeout)
        return Completed(proc.returncode, out or "", err or "", False)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=DRAIN_TIMEOUT)
        except subprocess.TimeoutExpired:
            # The tree survived the kill and still holds the pipes. Give up on
            # the output rather than blocking: the timeout is the answer.
            proc.kill()
            out, err = "", ""
        note = f"command timed out after {timeout}s (process tree killed)"
        return Completed(-1, out or "", f"{err or ''}\n{note}".strip(), True)
