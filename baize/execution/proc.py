"""Subprocess execution with interactive prompt detection and bounded timeouts."""

from __future__ import annotations

# ===========================================================================
# Section: interactive_detector.py
# ===========================================================================

import re
from typing import Any

__all__ = [
    "detect_interactive_prompt",
    "get_safe_auto_answer",
]

# Patterns for common blocking CLI prompts
_INTERACTIVE_PATTERNS = [
    (r'(?i)\[y/n\]|\(y/n\)|\(yes/no\)|\[yes/no\]', "confirmation", "y\n"),
    (r'(?i)password\b.*:\s*$', "password_prompt", "\n"),
    (r'(?i)passphrase\b.*:\s*$', "password_prompt", "\n"),
    (r'(?i)press\s+(?:any\s+key|enter)\s+to\s+continue', "press_enter", "\n"),
    (r'(?i)package\s+name\s*:\s*(?:\([^)]*\))?\s*$', "npm_init_field", "\n"),
    (r'(?i)version\s*:\s*(?:\([^)]*\))?\s*$', "npm_init_field", "\n"),
    (r'(?i)author\s*:\s*(?:\([^)]*\))?\s*$', "npm_init_field", "\n"),
    (r'(?i)license\s*:\s*(?:\([^)]*\))?\s*$', "npm_init_field", "\n"),
    (r'(?i)is\s+this\s+ok\?\s*\(yes\)\s*$', "npm_confirm", "yes\n"),
    (r'(?i)are\s+you\s+sure\s+you\s+want\s+to\s+continue\s+connecting', "ssh_fingerprint", "yes\n"),
]


def detect_interactive_prompt(text: str) -> dict[str, Any]:
    """Scan stdout/stderr text chunk to detect if subprocess is waiting for interactive user input."""
    if not text:
        return {"is_interactive": False, "prompt_type": None, "suggested_answer": None}

    cleaned = text.strip()
    # Check last line or last 200 chars
    tail = cleaned[-200:] if len(cleaned) > 200 else cleaned

    for pattern, ptype, answer in _INTERACTIVE_PATTERNS:
        if re.search(pattern, tail):
            return {
                "is_interactive": True,
                "prompt_type": ptype,
                "suggested_answer": answer,
                "matched_snippet": tail[-80:],
                "message": f"嗅探到交互式 CLI 提示 [{ptype}]，已自动注入安全默认应答避免 60s 超时死锁！"
            }

    return {"is_interactive": False, "prompt_type": None, "suggested_answer": None}


def get_safe_auto_answer(prompt_type: str) -> str:
    """Return default safe newline response."""
    for _, ptype, answer in _INTERACTIVE_PATTERNS:
        if ptype == prompt_type:
            return answer
    return "\n"

# ===========================================================================
# Section: proc.py
# ===========================================================================

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

    proc_env = dict(env if env is not None else os.environ)
    if "PYTHONIOENCODING" not in proc_env:
        proc_env["PYTHONIOENCODING"] = "utf-8"
    if "PYTHONUTF8" not in proc_env:
        proc_env["PYTHONUTF8"] = "1"

    stdin = subprocess.PIPE if input_text is not None else subprocess.DEVNULL
    proc = subprocess.Popen(
        cmd,
        shell=shell,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=proc_env,
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
