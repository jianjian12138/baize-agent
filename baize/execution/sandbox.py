"""Fail-closed shell guardrails, safe command execution, and sandbox runner."""

from __future__ import annotations

# ===========================================================================
# Section: safe_exec.py
# ===========================================================================

from typing import Any

#: Builtins exposed to executed code. Deliberately excludes every name that can
#: reach the filesystem, the process, the interpreter's import machinery or the
#: type graph: open, eval, exec, compile, globals, locals, vars, getattr/setattr/
#: delattr, input, breakpoint, memoryview, object, type.
#:
#: ``__import__`` IS present, but only as :func:`_safe_import`, which resolves
#: against :data:`ALLOWED_MODULES` and raises ImportError for everything else.
SAFE_BUILTINS: dict[str, Any] = {
    # --- numeric / sequence constructors and helpers ---
    "abs": abs, "all": all, "any": any, "bool": bool, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float, "int": int,
    "len": len, "list": list, "map": map, "max": max, "min": min, "pow": pow,
    "range": range, "reversed": reversed, "round": round, "set": set,
    "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    "dict": dict, "frozenset": frozenset, "bytes": bytes, "bytearray": bytearray,
    "complex": complex, "hash": hash, "id": id, "iter": iter, "next": next,
    "repr": repr, "slice": slice, "format": format, "chr": chr, "ord": ord,
    "hex": hex, "oct": oct, "bin": bin, "ascii": ascii, "isinstance": isinstance,
    "issubclass": issubclass, "callable": callable, "divmod": divmod,
    # --- constants ---
    "True": True, "False": False, "None": None,
    # --- exception types, so user code can raise/catch sanely ---
    "Exception": Exception, "AssertionError": AssertionError,
    "ArithmeticError": ArithmeticError, "AttributeError": AttributeError,
    "IndexError": IndexError, "KeyError": KeyError, "LookupError": LookupError,
    "NameError": NameError, "NotImplementedError": NotImplementedError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
    "TypeError": TypeError, "ValueError": ValueError, "ZeroDivisionError":
        ZeroDivisionError, "OverflowError": OverflowError,
    "FloatingPointError": FloatingPointError, "UnicodeError": UnicodeError,
    # --- the common base, needed for `except Exception` style handling ---
    "BaseException": BaseException,
}

#: Modules generated tool code may import. DEFAULT-DENY: anything not listed here
#: raises ImportError, so a plain ``import os`` still fails.
#:
#: This is an allowlist of pure-computation stdlib modules. It exists because the
#: synthesizer legitimately emits tool code that does ``import re`` / ``import
#: json``; forbidding all imports outright broke that use case (see
#: tests/test_v30_meta_tool_synthesizer.py).
#:
#: WHAT IT DOES NOT DO: it does not make the namespace a containment boundary.
#: Module objects carry ``__loader__``/``__spec__`` and attribute access is
#: language syntax, so a determined payload can still read files or walk
#: ``object.__subclasses__``. See the module docstring. The access-control gate in
#: baize/serve.py is the real boundary; this list only raises the cost of the
#: naive payload.
#:
#: Notable omissions, on purpose: os, sys, io (io.open is open), pathlib, shutil,
#: subprocess, socket, importlib, builtins, ctypes, pickle, marshal, tempfile,
#: glob, sqlite3, asyncio (asyncio.subprocess), http, urllib.request, platform,
#: resource, signal, threading, multiprocessing, gc, inspect, traceback, logging.
ALLOWED_MODULES = frozenset({
    "abc", "array", "base64", "binascii", "bisect", "calendar", "collections",
    "copy", "csv", "dataclasses", "datetime", "decimal", "difflib", "enum",
    "fractions", "functools", "hashlib", "heapq", "html", "itertools", "json",
    "math", "numbers", "operator", "pprint", "random", "re", "reprlib",
    "statistics", "string", "struct", "textwrap", "time", "typing",
    "unicodedata", "urllib.parse", "uuid",
})

#: Names that must never appear in the namespace. Asserted by
#: tests/test_safe_exec.py so a future edit cannot quietly widen the surface.
FORBIDDEN_BUILTINS = frozenset({
    "open", "eval", "exec", "compile", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "hasattr", "input", "breakpoint",
    "memoryview", "object", "type", "super", "classmethod", "staticmethod",
    "property", "dir", "help", "exit", "quit", "license", "credits",
    "copyright", "reload", "__build_class__", "__loader__", "__spec__",
})


def _safe_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
    """``__import__`` restricted to :data:`ALLOWED_MODULES`.

    ``level != 0`` (relative import) is always refused: it resolves through the
    caller's package and would sidestep the name check entirely.
    """
    if level != 0:
        raise ImportError("relative imports are not allowed in generated code")
    if name in ALLOWED_MODULES:
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(
        f"module '{name}' is not on the allowlist for generated code "
        f"(baize/safe_exec.py::ALLOWED_MODULES)"
    )


SAFE_BUILTINS["__import__"] = _safe_import


def restricted_globals() -> dict[str, Any]:
    """Globals mapping for executing untrusted code. Fresh dict every call."""
    return {"__builtins__": dict(SAFE_BUILTINS)}


def exec_restricted(source: str, seed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute ``source`` with only :data:`SAFE_BUILTINS` available.

    Returns the resulting namespace so the caller can pull definitions back out.

    ``source`` is passed as *both* globals and locals on purpose. With separate
    dicts, a function defined at top level lands in locals while a call to it
    from another top-level function resolves through globals and raises
    NameError - which silently breaks any legitimate multi-function snippet.
    """
    ns = restricted_globals()
    if seed:
        ns.update(seed)
    exec(source, ns, ns)  # noqa: S102 - the point of this module
    return ns

# ===========================================================================
# Section: sandbox.py
# ===========================================================================

import logging
import platform
import subprocess
from dataclasses import dataclass
from shutil import which

from ..core.config import ROOT, load_config
from ..core.config import redact
from . import proc as proc_mod

logger = logging.getLogger("baize.execution.sandbox")


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    degraded: bool = False
    # none | landlock | seatbelt | logical-only
    mechanism: str = "none"


def platform_mechanism() -> str:
    """Return the best available OS mechanism name for this platform."""
    sysname = platform.system()
    if sysname == "Linux":
        try:
            import landlock  # type: ignore[import-not-found]  # stdlib on 3.13+ Linux
            _ = landlock.create_ruleset
            return "landlock"
        except Exception:  # pragma: no cover - depends on host kernel
            return "logical-only"
    if sysname == "Darwin":
        return "seatbelt" if which("sandbox-exec") else "logical-only"
    # Windows restricted token is not implemented -> honest degrade.
    return "logical-only"


def _plain(command: str, cwd: str, timeout: int) -> SandboxResult:
    # Resolve bare "python" / "python3" to the interpreter actually running us.
    # The store-stub "python.exe" alias returns 9009 instead of executing, so
    # sandbox tests against a stock Python install (not on PATH) would always
    # fail. Using sys.executable avoids the alias entirely.
    import sys as _sys
    cmd = command
    head = cmd.split(None, 1)[0]
    if head in ("python", "python3"):
        cmd = _sys.executable + cmd[len(head):]
    # proc.run, not subprocess.run: with shell=True a plain subprocess.run
    # timeout kills the shell but not the grandchild that holds the pipe, so the
    # wall time is unbounded. See baize/proc.py.
    res = proc_mod.run(cmd, shell=True, timeout=timeout, cwd=cwd)
    if res.timed_out:
        return SandboxResult(-1, "", f"command timed out after {timeout}s",
                             mechanism="none")
    return SandboxResult(res.returncode, redact(res.stdout or ""),
                         redact(res.stderr or ""), mechanism="none")


def _apply_landlock(workspace: str) -> None:
    """Best-effort Landlock: read/exec everywhere, write only under workspace."""
    import landlock  # type: ignore[import-not-found]
    import landlock.access as laccess  # type: ignore[import-not-found]

    ruleset = landlock.create_ruleset()
    ruleset.add_rule(laccess.FS_ROUGHLY_READ, "/")
    ruleset.add_rule(laccess.FS_ROUGHLY_EXECUTE, "/")
    ruleset.add_rule(laccess.FS_ROUGHLY_WRITE, workspace, inherit=True)
    ruleset.restrict_self()


def _landlock_preexec(workspace: str):
    def _child() -> None:
        try:
            _apply_landlock(workspace)
        except Exception as exc:  # pragma: no cover - host specific
            logger.warning("landlock restrict failed in child: %s", exc)
    return _child


def _seatbelt_profile(workspace: str) -> str:
    """Minimal Seatbelt profile: read/exec anywhere, write only under workspace."""
    return (
        '(version 1)(deny default)'
        '(allow process-exec)'
        '(allow file-read*)'
        f'(allow file-write* (subpath "{workspace}"))'
    )


def _seatbelt_command(command: str, workspace: str) -> str:
    # Prepend the sandbox wrapper; the original command stays shell-expanded.
    return (f'sandbox-exec -p \'{_seatbelt_profile(workspace)}\' '
            f'sh -c {subprocess.list2cmdline([command])}')


@dataclass
class ArgvPlan:
    """How to run an argv with OS isolation - or an honest record that we cannot.

    ``mechanism`` names the layer actually applied:

      ``none``          sandbox disabled; ``argv`` runs as-is
      ``landlock``      restriction installed in the child via ``preexec_fn``
      ``seatbelt``      ``argv`` is prefixed with ``sandbox-exec``
      ``logical-only``  enabled, but this platform has no mechanism and
                        ``degraded`` is True
    """
    argv: list[str]
    mechanism: str = "none"
    preexec_fn: object | None = None
    degraded: bool = False


def plan_argv(argv, workspace: str, cfg: dict | None = None) -> ArgvPlan:
    """Wrap ``argv`` for OS isolation, honouring the same switch as :func:`run`.

    This exists because ``run_python`` executes ``[python, -I, -c, <code>]`` -
    an argv with no shell, which cannot be expressed as the command *string*
    :func:`run` takes. Without it, ``BAIZE_SANDBOX_ENABLED=1`` confined ``bash``
    and silently left ``run_python`` unconfined: the switch promised one thing
    and delivered another, which is the failure mode this module's docstring
    says it exists to avoid.

    ``preexec_fn`` is returned rather than a wrapped command string on purpose -
    the snippet is arbitrary Python and shell-quoting it would be an injection
    surface. On Windows it is always ``None``: there is no mechanism, so the
    plan degrades honestly instead of pretending to confine.
    """
    args = [str(a) for a in argv]
    cfg = cfg or load_config()
    if cfg.get("BAIZE_SANDBOX_ENABLED", "0") != "1":
        return ArgvPlan(args)

    mech = platform_mechanism()
    if mech == "landlock":  # pragma: no cover - Linux only
        return ArgvPlan(args, "landlock", _landlock_preexec(workspace))
    if mech == "seatbelt":  # pragma: no cover - macOS only
        # sandbox-exec takes the command and its arguments directly, so no shell
        # - and therefore no quoting hazard - is involved.
        return ArgvPlan(["sandbox-exec", "-p", _seatbelt_profile(workspace), *args],
                        "seatbelt")

    logger.warning(
        "OS sandbox unavailable on this platform; run_python degrades to "
        "logical-only (AST guard + scrubbed env + workspace cwd only).")
    return ArgvPlan(args, "logical-only", None, True)


def run(command: str, cwd: str | None = None, timeout: int = 60,
        cfg: dict | None = None) -> SandboxResult:
    """Run ``command`` applying the OS sandbox when enabled.

    When ``BAIZE_SANDBOX_ENABLED != "1"`` this is identical to a plain
    subprocess (mechanism="none", degraded=False). When enabled but the
    platform cannot apply OS isolation, it degrades to a plain run with
    degraded=True and a warning (never a silent fake shield).
    """
    cfg = cfg or load_config()
    cwd = cwd or str(ROOT)
    enabled = cfg.get("BAIZE_SANDBOX_ENABLED", "0") == "1"
    if not enabled:
        return _plain(command, cwd, timeout)

    mech = platform_mechanism()
    if mech == "logical-only":
        res = _plain(command, cwd, timeout)
        res.degraded = True
        res.mechanism = "logical-only"
        logger.warning(
            "OS sandbox unavailable on this platform; degraded to "
            "logical-only (deny-list + workspace confinement only).")
        return res

    if mech == "landlock":  # pragma: no cover - Linux only
        # proc.run, with the kernel restriction installed by preexec_fn. This
        # branch kept a direct subprocess.run after the rest of the package was
        # routed through proc.py - it needs preexec_fn, which proc.run did not
        # accept yet - and so it kept the same unbounded-timeout defect: the
        # timeout killed the shell while the grandchild held the pipe open.
        res = proc_mod.run(command, shell=True, timeout=timeout, cwd=cwd,
                           preexec_fn=_landlock_preexec(cwd))
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 mechanism="landlock")
        return SandboxResult(res.returncode, redact(res.stdout or ""),
                             redact(res.stderr or ""), mechanism="landlock")

    if mech == "seatbelt":  # pragma: no cover - macOS only
        # proc.run (not subprocess.run) so a timeout kills the sandbox-exec tree
        # rather than leaving the sandboxed child holding the pipe. See
        # baize/proc.py.
        wrapped = _seatbelt_command(command, cwd)
        res = proc_mod.run(wrapped, shell=True, timeout=timeout, cwd=cwd)
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 mechanism="seatbelt")
        return SandboxResult(res.returncode, redact(res.stdout or ""),
                             redact(res.stderr or ""), mechanism="seatbelt")

    # Fallback (should be unreachable); be honest.
    res = _plain(command, cwd, timeout)
    res.degraded = True
    res.mechanism = "logical-only"
    return res
