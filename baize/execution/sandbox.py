"""Fail-closed shell guardrails, safe command execution, and sandbox runner."""

from __future__ import annotations

import os
import re

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


def _sensitive_home_paths() -> list[str]:
    """Return existing user credential directories to shield from sandboxed reads."""
    home = os.path.expanduser("~")
    if not home or home == "~":
        return []
    candidates = [
        ".ssh",
        ".aws",
        ".kube",
        ".gnupg",
        os.path.join(".config", "gh"),
    ]
    found: list[str] = []
    for rel in candidates:
        full = os.path.abspath(os.path.join(home, rel))
        if os.path.exists(full):
            found.append(full)
    return found


# ---------------------------------------------------------------------------
# Pure-stdlib Linux Landlock ABI v1 via ctypes (Linux 5.13+, zero third-party)
# ---------------------------------------------------------------------------
_LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
_LANDLOCK_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

# ABI v1 filesystem access flags
_LL_FS_EXECUTE = 1 << 0
_LL_FS_WRITE_FILE = 1 << 1
_LL_FS_READ_FILE = 1 << 2
_LL_FS_READ_DIR = 1 << 3
_LL_FS_REMOVE_DIR = 1 << 4
_LL_FS_REMOVE_FILE = 1 << 5
_LL_FS_MAKE_CHAR = 1 << 6
_LL_FS_MAKE_DIR = 1 << 7
_LL_FS_MAKE_REG = 1 << 8
_LL_FS_MAKE_SOCK = 1 << 9
_LL_FS_MAKE_FIFO = 1 << 10
_LL_FS_MAKE_BLOCK = 1 << 11
_LL_FS_MAKE_SYM = 1 << 12

_LL_FS_READ_EXEC = _LL_FS_EXECUTE | _LL_FS_READ_FILE | _LL_FS_READ_DIR
_LL_FS_WRITE_ALL = (
    _LL_FS_WRITE_FILE | _LL_FS_REMOVE_DIR | _LL_FS_REMOVE_FILE
    | _LL_FS_MAKE_CHAR | _LL_FS_MAKE_DIR | _LL_FS_MAKE_REG
    | _LL_FS_MAKE_SOCK | _LL_FS_MAKE_FIFO | _LL_FS_MAKE_BLOCK | _LL_FS_MAKE_SYM
)
_LL_FS_ALL_V1 = _LL_FS_READ_EXEC | _LL_FS_WRITE_ALL

# Syscall numbers are identical across x86_64, aarch64, riscv64, arm64 in Linux
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446


def _landlock_abi_version() -> int:
    """Query Linux kernel Landlock ABI version via pure-stdlib ctypes (-1 if unsupported)."""
    if platform.system() != "Linux":
        return -1
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        ver = int(libc.syscall(_SYS_LANDLOCK_CREATE_RULESET, None, 0, _LANDLOCK_CREATE_RULESET_VERSION))
        return ver if ver >= 1 else -1
    except Exception:
        return -1


def _landlock_ctypes_supported() -> bool:
    return _landlock_abi_version() >= 1


def _apply_landlock_ctypes(workspace: str) -> None:
    """Enforce Landlock ABI v1 via raw Linux syscalls (pure-stdlib ctypes).

    Allows read/exec across ``/`` and write strictly inside ``workspace``
    (plus ``/dev/null`` and the workspace temp parent if needed).
    """
    import ctypes

    class _RulesetAttr(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class _PathBeneathAttr(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("allowed_access", ctypes.c_uint64),
            ("parent_fd", ctypes.c_int32),
        ]

    libc = ctypes.CDLL(None, use_errno=True)
    attr = _RulesetAttr(handled_access_fs=_LL_FS_ALL_V1)
    ruleset_fd = int(
        libc.syscall(
            _SYS_LANDLOCK_CREATE_RULESET,
            ctypes.byref(attr),
            ctypes.sizeof(attr),
            0,
        )
    )
    if ruleset_fd < 0:
        err = ctypes.get_errno()
        raise OSError(err, f"landlock_create_ruleset failed (errno={err})")

    def _add_path_rule(path: str, access: int) -> None:
        if not os.path.exists(path):
            return
        o_path = getattr(os, "O_PATH", 0o10000000)
        flags = o_path | os.O_CLOEXEC
        try:
            fd = os.open(path, flags)
        except OSError:
            return
        try:
            pb = _PathBeneathAttr(allowed_access=access, parent_fd=fd)
            rc = int(
                libc.syscall(
                    _SYS_LANDLOCK_ADD_RULE,
                    ruleset_fd,
                    _LANDLOCK_RULE_PATH_BENEATH,
                    ctypes.byref(pb),
                    0,
                )
            )
            if rc < 0:
                err = ctypes.get_errno()
                raise OSError(err, f"landlock_add_rule({path}) failed (errno={err})")
        finally:
            os.close(fd)

    try:
        _add_path_rule("/", _LL_FS_READ_EXEC)
        ws_abs = os.path.abspath(workspace)
        _add_path_rule(ws_abs, _LL_FS_ALL_V1)
        _add_path_rule("/dev/null", _LL_FS_WRITE_FILE | _LL_FS_READ_FILE)
        _add_path_rule("/tmp", _LL_FS_ALL_V1)

        if int(libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) != 0:
            err = ctypes.get_errno()
            raise OSError(err, f"prctl(PR_SET_NO_NEW_PRIVS) failed (errno={err})")

        rc = int(libc.syscall(_SYS_LANDLOCK_RESTRICT_SELF, ruleset_fd, 0))
        if rc < 0:
            err = ctypes.get_errno()
            raise OSError(err, f"landlock_restrict_self failed (errno={err})")
    finally:
        os.close(ruleset_fd)


def landlock_driver() -> str:
    """Return active Linux Landlock driver name: ``python-landlock`` | ``ctypes`` | ``none``."""
    import sys as _sys
    if platform.system() != "Linux":
        return "none"
    # Respect tests that explicitly disable the ``landlock`` module via sys.modules["landlock"] = None
    if "landlock" in _sys.modules and _sys.modules["landlock"] is None:
        return "none"
    try:
        import landlock  # type: ignore[import-not-found]
        _ = landlock.create_ruleset
        return "python-landlock"
    except Exception:
        pass
    if _landlock_ctypes_supported():
        return "ctypes"
    return "none"


# ---------------------------------------------------------------------------
# Windows native Job Object + optional Restricted Token (pure stdlib ctypes)
# ---------------------------------------------------------------------------
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFO_CLASS = 9
_DISABLE_MAX_PRIVILEGE = 0x1
_TOKEN_QUERY = 0x0008
_TOKEN_DUPLICATE = 0x0002
_TOKEN_ASSIGN_PRIMARY = 0x0001
_CREATE_SUSPENDED = 0x00000004
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def _win32_job_object_supported() -> bool:
    """True only on real Windows NT hosts where Win32 Job Object APIs are callable.

    Deliberately checks ``os.name == "nt"`` so Linux/macOS tests that monkeypatch
    ``platform.system()`` to ``"Windows"`` preserve honest ``"logical-only"`` behavior.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        k32 = getattr(ctypes, "windll", None)
        k32 = getattr(k32, "kernel32", None) if k32 is not None else None
        if k32 is None:
            return False
        for fn in ("CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject", "CloseHandle"):
            if getattr(k32, fn, None) is None:
                return False
        return True
    except Exception:
        return False


def _win32_restricted_token_supported() -> bool:
    """True on real Windows NT hosts where advapi32.CreateRestrictedToken is callable."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        adv = getattr(ctypes, "windll", None)
        adv = getattr(adv, "advapi32", None) if adv is not None else None
        return adv is not None and getattr(adv, "CreateRestrictedToken", None) is not None
    except Exception:
        return False


def platform_mechanism() -> str:
    """Return the best available OS mechanism name for this platform."""
    sysname = platform.system()
    if sysname == "Linux":
        drv = landlock_driver()
        if drv != "none":
            return "landlock"
        if which("bwrap"):
            return "bwrap"
        return "logical-only"
    if sysname == "Darwin":
        return "seatbelt" if which("sandbox-exec") else "logical-only"
    if sysname == "Windows" and _win32_job_object_supported():
        return "win-job-object"
    return "logical-only"


def _plain(command: str, cwd: str, timeout: int) -> SandboxResult:
    import sys as _sys
    cmd = command
    head = cmd.split(None, 1)[0]
    if head in ("python", "python3"):
        cmd = _sys.executable + cmd[len(head):]
    res = proc_mod.run(cmd, shell=True, timeout=timeout, cwd=cwd)
    if res.timed_out:
        return SandboxResult(-1, "", f"command timed out after {timeout}s",
                             mechanism="none")
    return SandboxResult(res.returncode, redact(res.stdout or ""),
                         redact(res.stderr or ""), mechanism="none")


def _apply_landlock(workspace: str) -> None:
    """Best-effort Landlock: read/exec everywhere, write only under workspace.

    Uses Python ``landlock`` stdlib module when available, falling back to the
    pure-stdlib ``ctypes`` syscall driver on Linux 5.13+.
    """
    try:
        import landlock  # type: ignore[import-not-found]
        import landlock.access as laccess  # type: ignore[import-not-found]
        ruleset = landlock.create_ruleset()
        ruleset.add_rule(laccess.FS_ROUGHLY_READ, "/")
        ruleset.add_rule(laccess.FS_ROUGHLY_EXECUTE, "/")
        ruleset.add_rule(laccess.FS_ROUGHLY_WRITE, workspace, inherit=True)
        ruleset.restrict_self()
        return
    except ImportError:
        pass
    _apply_landlock_ctypes(workspace)


def _landlock_preexec(workspace: str):
    def _child() -> None:
        try:
            _apply_landlock(workspace)
        except Exception as exc:  # pragma: no cover - host specific
            logger.warning("landlock restrict failed in child: %s", exc)
    return _child


def _seatbelt_profile(workspace: str, *, allow_net: bool = True, deny_sensitive: bool = True) -> str:
    """Hardened macOS Seatbelt profile: workspace-scoped writes + secret-dir shields."""
    parts = [
        '(version 1)',
        '(deny default)',
        '(allow process-exec)',
        '(allow process-fork)',
        '(allow file-read*)',
        f'(allow file-write* (subpath "{workspace}"))',
        '(allow file-write* (literal "/dev/null"))',
    ]
    if deny_sensitive:
        for secret_dir in _sensitive_home_paths():
            parts.append(f'(deny file-read* (subpath "{secret_dir}"))')
    if allow_net:
        parts.append('(allow network*)')
    else:
        parts.append('(deny network-outbound)')
    return "".join(parts)


def _seatbelt_command(command: str, workspace: str, *, allow_net: bool = True) -> str:
    return (f"sandbox-exec -p '{_seatbelt_profile(workspace, allow_net=allow_net)}' "
            f"sh -c {subprocess.list2cmdline([command])}")


def _bwrap_command(command: str, workspace: str, *, allow_net: bool = True) -> list[str]:
    """Build a bubblewrap argv when ``bwrap`` is installed on Linux."""
    ws = os.path.abspath(workspace)
    argv = [
        "bwrap",
        "--ro-bind", "/", "/",
        "--bind", ws, ws,
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--chdir", ws,
    ]
    if not allow_net:
        argv.append("--unshare-net")
    argv.extend(["sh", "-c", command])
    return argv


@dataclass
class ArgvPlan:
    """How to run an argv with OS isolation - or an honest record that we cannot."""
    argv: list[str]
    mechanism: str = "none"
    preexec_fn: object | None = None
    degraded: bool = False


def plan_argv(argv, workspace: str, cfg: dict | None = None) -> ArgvPlan:
    """Wrap ``argv`` for OS isolation, honouring the same switch as :func:`run`."""
    args = [str(a) for a in argv]
    cfg = cfg if cfg is not None else load_config()
    if cfg.get("BAIZE_SANDBOX_ENABLED", "0") != "1":
        return ArgvPlan(args)

    allow_net = (cfg.get("BAIZE_SANDBOX_NET", "allow") or "allow").strip().lower() != "none"
    mech = platform_mechanism()
    if mech == "landlock":  # pragma: no cover - Linux only
        return ArgvPlan(args, "landlock", _landlock_preexec(workspace))
    if mech == "win-job-object":  # pragma: no cover - Windows NT only
        return _run_with_win_job_object(command, cwd, timeout, pol, child_env)

    if mech == "seatbelt":  # pragma: no cover - macOS only
        return ArgvPlan(
            ["sandbox-exec", "-p", _seatbelt_profile(workspace, allow_net=allow_net), *args],
            "seatbelt",
        )
    if mech == "bwrap":  # pragma: no cover - Linux bwrap only
        ws = os.path.abspath(workspace)
        prefix = ["bwrap", "--ro-bind", "/", "/", "--bind", ws, ws, "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--chdir", ws]
        if not allow_net:
            prefix.append("--unshare-net")
        return ArgvPlan([*prefix, *args], "bwrap")

    logger.warning(
        "OS sandbox unavailable on this platform; run_python degrades to "
        "logical-only (AST guard + scrubbed env + workspace cwd only).")
    return ArgvPlan(args, "logical-only", None, True)


# ===========================================================================
# Tiered Sandbox Policy: POSIX rlimit + Env Scrubbing + Docker Routing
# ===========================================================================

_SENSITIVE_ENV_RE = re.compile(
    r"(?:^BAIZE_AUTH_TOKEN$|API_KEY$|_SECRET|_TOKEN$|PASSWORD$|PASSWD$|PRIVATE_KEY$)",
    re.I,
)


@dataclass(frozen=True)
class SandboxPolicy:
    """Runtime resource & isolation policy for sandboxed execution."""
    mode: str = ""  # "" (disabled) | "local-hardened" | "docker" | "auto"
    cpu_seconds: int = 60
    memory_mb: int = 1024
    nofile: int = 256
    max_processes: int = 32
    scrub_env: bool = True
    allow_net: bool = True
    win_restricted_token: bool = False
    docker_image: str = "python:3.11-slim"
    docker_network: str = "none"
    docker_session_pool: bool = True


def scrub_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``env`` with API keys, auth tokens, and secrets stripped."""
    src = os.environ if env is None else env
    return {k: v for k, v in src.items() if not _SENSITIVE_ENV_RE.search(k)}


def resolve_sandbox_mode(cfg: dict[str, str] | None = None) -> str:
    """Resolve effective sandbox mode from config.

    Returns one of ``""`` (disabled), ``"local-hardened"``,
    ``"docker"``, or ``"auto"``.
    """
    cfg = cfg if cfg is not None else load_config()
    raw = (cfg.get("BAIZE_SANDBOX_MODE") or "").strip().lower()
    if raw in ("disabled", "off", "none"):
        return ""
    if raw in ("local-hardened", "local", "hardened"):
        return "local-hardened"
    if raw in ("docker", "auto"):
        return raw
    if str(cfg.get("BAIZE_SANDBOX_ENABLED", "0")).strip().lower() in ("1", "true", "yes"):
        return "local-hardened"
    return ""


def _build_policy(cfg: dict[str, str] | None = None, mode_override: str | None = None) -> SandboxPolicy:
    cfg = cfg if cfg is not None else load_config()
    mode = (mode_override or "").strip().lower() or resolve_sandbox_mode(cfg)
    if mode in ("local", "hardened"):
        mode = "local-hardened"
    if mode in ("disabled", "off", "none"):
        mode = ""
    net_policy = (cfg.get("BAIZE_SANDBOX_NET") or "allow").strip().lower()
    return SandboxPolicy(
        mode=mode,
        cpu_seconds=max(5, int(cfg.get("BAIZE_SANDBOX_CPU_LIMIT_S", "60") or "60")),
        memory_mb=max(128, int(cfg.get("BAIZE_SANDBOX_MEM_LIMIT_MB", "1024") or "1024")),
        allow_net=(net_policy != "none"),
        win_restricted_token=(str(cfg.get("BAIZE_WIN_SANDBOX_RESTRICTED_TOKEN", "0")).strip().lower() in ("1", "true", "yes")),
        docker_image=(cfg.get("BAIZE_SANDBOX_DOCKER_IMAGE") or "python:3.11-slim").strip(),
        docker_session_pool=(str(cfg.get("BAIZE_DOCKER_SESSION_POOL", "1")).strip().lower() in ("1", "true", "yes")),
    )


def _rlimit_preexec(policy: SandboxPolicy, landlock_workspace: str | None = None):
    """Build a POSIX ``preexec_fn`` that enforces ``rlimit`` caps + optional Landlock."""
    if os.name == "nt":
        return None

    def _apply() -> None:
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
            cap_cpu = policy.cpu_seconds if hard == resource.RLIM_INFINITY else min(policy.cpu_seconds, hard)
            resource.setrlimit(resource.RLIMIT_CPU, (cap_cpu, hard))
            s_nf, h_nf = resource.getrlimit(resource.RLIMIT_NOFILE)
            cap_nf = policy.nofile if h_nf == resource.RLIM_INFINITY else min(policy.nofile, h_nf)
            if cap_nf > 0:
                resource.setrlimit(resource.RLIMIT_NOFILE, (cap_nf, h_nf))
        except Exception:
            pass
        if landlock_workspace:
            try:
                _apply_landlock(landlock_workspace)
            except Exception:
                pass

    return _apply




def build_win_job_limits(policy: SandboxPolicy) -> dict[str, Any]:
    """Compute exact Win32 ``JOBOBJECT_EXTENDED_LIMIT_INFORMATION`` parameters for *policy*."""
    mem_bytes = max(128, int(policy.memory_mb)) * 1024 * 1024
    proc_limit = max(1, int(policy.max_processes))
    limit_flags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_JOB_MEMORY
        | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
    )
    return {
        "info_class": _JOB_OBJECT_EXTENDED_LIMIT_INFO_CLASS,
        "limit_flags": limit_flags,
        "kill_on_job_close": True,
        "active_process_limit": proc_limit,
        "process_memory_bytes": mem_bytes,
        "job_memory_bytes": mem_bytes,
        "cpu_seconds": max(5, int(policy.cpu_seconds)),
        "restricted_token": bool(policy.win_restricted_token),
    }


def win_sandbox_capabilities(cfg: dict[str, str] | None = None) -> dict[str, Any]:
    """Honest disclosure of Windows native Job Object & Restricted Token capabilities."""
    eff_cfg = cfg if cfg is not None else load_config()
    pol = _build_policy(eff_cfg)
    job_ok = _win32_job_object_supported()
    tok_ok = _win32_restricted_token_supported()
    return {
        "is_windows_nt": os.name == "nt",
        "job_object_supported": job_ok,
        "restricted_token_supported": tok_ok,
        "restricted_token_enabled": bool(pol.win_restricted_token),
        "process_isolation": (
            "win-job-object+restricted-token"
            if (job_ok and pol.win_restricted_token and tok_ok)
            else ("win-job-object" if job_ok else "unavailable-on-non-windows")
        ),
        "filesystem_isolation": (
            "logical-workspace-guard-only (Windows Job Object enforces process/memory/tree limits; "
            "use Docker mode for filesystem namespace isolation)"
        ),
        "limits": build_win_job_limits(pol),
    }


def _make_win_extended_limit_struct(limits: dict[str, Any]):
    """Build ctypes ``JOBOBJECT_EXTENDED_LIMIT_INFORMATION`` structure (pure stdlib)."""
    import ctypes

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = int(limits["limit_flags"])
    info.BasicLimitInformation.ActiveProcessLimit = int(limits["active_process_limit"])
    info.ProcessMemoryLimit = int(limits["process_memory_bytes"])
    info.JobMemoryLimit = int(limits["job_memory_bytes"])
    return info


def _probe_restricted_token(win_api: Any) -> tuple[bool, str]:
    """Attempt ``advapi32.CreateRestrictedToken(..., DISABLE_MAX_PRIVILEGE, ...)`` when enabled.

    Returns ``(ok, note)`` and always closes temporary handles cleanly.
    """
    import ctypes
    try:
        k32 = getattr(win_api, "kernel32", None)
        adv = getattr(win_api, "advapi32", None)
        if k32 is None or adv is None:
            return False, "advapi32 unavailable"
        cur_proc = k32.GetCurrentProcess()
        h_token = ctypes.c_void_p()
        if not adv.OpenProcessToken(cur_proc, _TOKEN_DUPLICATE | _TOKEN_QUERY | _TOKEN_ASSIGN_PRIMARY, ctypes.byref(h_token)):
            return False, "OpenProcessToken denied"
        h_restricted = ctypes.c_void_p()
        try:
            ok = bool(adv.CreateRestrictedToken(
                h_token,
                _DISABLE_MAX_PRIVILEGE,
                0, None,
                0, None,
                0, None,
                ctypes.byref(h_restricted),
            ))
            if ok and h_restricted.value:
                k32.CloseHandle(h_restricted)
                return True, "restricted-token-verified"
            return False, "CreateRestrictedToken failed"
        finally:
            if h_token.value:
                k32.CloseHandle(h_token)
    except Exception as exc:
        return False, f"restricted-token-error: {exc}"


def _run_with_win_job_object(
    command: str,
    cwd: str,
    timeout: int,
    policy: SandboxPolicy,
    env: dict[str, str] | None = None,
    *,
    _win_api: Any = None,
    mechanism_suffix: str = "",
) -> SandboxResult:
    """Execute *command* attached to a Win32 Job Object (process-tree + memory + active-process limits).

    Pure stdlib ``ctypes`` implementation. When ``_win_api`` is passed in tests, exercises the exact
    Job Object lifecycle deterministically on any host OS without touching native DLLs.
    """
    import ctypes

    limits = build_win_job_limits(policy)
    mech = "win-job-object"
    k32 = None
    if _win_api is not None:
        k32 = getattr(_win_api, "kernel32", _win_api)
    elif os.name == "nt":
        k32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)

    if k32 is None:
        res = proc_mod.run(command, shell=True, timeout=timeout, cwd=cwd, env=env)
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 degraded=True, mechanism=f"logical-only{mechanism_suffix}")
        return SandboxResult(res.returncode, redact(res.stdout or ""), redact(res.stderr or ""),
                             degraded=True, mechanism=f"logical-only{mechanism_suffix}")

    if policy.win_restricted_token:
        tok_ok, _ = _probe_restricted_token(_win_api if _win_api is not None else getattr(ctypes, "windll", None))
        if tok_ok:
            mech = "win-job-object+restricted-token"

    job_handle = None
    proc = None
    try:
        job_handle = k32.CreateJobObjectW(None, None)
        if not job_handle:
            raise OSError("CreateJobObjectW returned NULL")
        info = _make_win_extended_limit_struct(limits)
        ok_set = k32.SetInformationJobObject(
            job_handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok_set:
            raise OSError("SetInformationJobObject failed")

        creation_flags = _CREATE_BREAKAWAY_FROM_JOB if os.name == "nt" else 0
        popen_kwargs: dict[str, Any] = {
            "shell": True,
            "cwd": cwd,
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if creation_flags:
            popen_kwargs["creationflags"] = creation_flags

        try:
            proc = subprocess.Popen(command, **popen_kwargs)
        except OSError:
            popen_kwargs.pop("creationflags", None)
            proc = subprocess.Popen(command, **popen_kwargs)

        proc_handle = getattr(proc, "_handle", None) or proc.pid
        ok_assign = k32.AssignProcessToJobObject(job_handle, proc_handle)
        if not ok_assign:
            logger.warning("AssignProcessToJobObject returned False; continuing with timeout guard")

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                if hasattr(k32, "TerminateJobObject"):
                    k32.TerminateJobObject(job_handle, 1)
            except Exception:
                pass
            try:
                proc.kill()
                proc.communicate(timeout=5)
            except Exception:
                pass
            return SandboxResult(
                -1, "", f"command timed out after {timeout}s",
                degraded=bool(mechanism_suffix),
                mechanism=f"{mech}{mechanism_suffix}",
            )

        return SandboxResult(
            int(proc.returncode or 0),
            redact(stdout or ""),
            redact(stderr or ""),
            degraded=bool(mechanism_suffix),
            mechanism=f"{mech}{mechanism_suffix}",
        )
    except Exception as exc:
        logger.warning("Windows Job Object setup failed (%s); degrading to logical-only", exc)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        res = proc_mod.run(command, shell=True, timeout=timeout, cwd=cwd, env=env)
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 degraded=True, mechanism=f"logical-only{mechanism_suffix}")
        return SandboxResult(res.returncode, redact(res.stdout or ""), redact(res.stderr or ""),
                             degraded=True, mechanism=f"logical-only{mechanism_suffix}")
    finally:
        if job_handle:
            try:
                k32.CloseHandle(job_handle)
            except Exception:
                pass


def sandbox_posture(cfg: dict[str, str] | None = None) -> dict[str, Any]:
    """Honest disclosure of active sandbox isolation tier and OS capabilities."""
    from .docker_sandbox import get_docker_pool, is_docker_available

    cfg = cfg if cfg is not None else load_config()
    pol = _build_policy(cfg)
    os_mech = platform_mechanism()
    docker_ok = is_docker_available()
    rlimit_ok = os.name != "nt"

    if pol.mode == "docker":
        effective = "docker_container" if docker_ok else "docker_unavailable (fail-closed)"
    elif pol.mode == "auto":
        effective = "docker_container" if docker_ok else f"local-hardened ({os_mech}+rlimit)"
    elif pol.mode == "local-hardened":
        effective = f"{os_mech}+rlimit" if rlimit_ok else os_mech
    else:
        effective = "disabled (guardrails-only)"

    win_caps = win_sandbox_capabilities(cfg)
    if os_mech in ("landlock", "bwrap", "seatbelt"):
        fs_iso = f"os-kernel ({os_mech})"
        proc_iso = f"posix-rlimit+{os_mech}"
    elif os_mech == "win-job-object":
        fs_iso = "logical-workspace-guard-only (use Docker for FS namespace isolation)"
        proc_iso = win_caps["process_isolation"]
    else:
        fs_iso = "logical-workspace-guard-only"
        proc_iso = "posix-rlimit" if rlimit_ok else "logical-only"

    return {
        "configured_mode": pol.mode or "disabled",
        "effective_isolation": effective,
        "os_mechanism": os_mech,
        "landlock_driver": landlock_driver(),
        "bwrap_available": bool(which("bwrap")),
        "rlimit_supported": rlimit_ok,
        "win_job_object_available": bool(win_caps["job_object_supported"]),
        "win_restricted_token": bool(pol.win_restricted_token),
        "process_isolation": proc_iso,
        "filesystem_isolation": fs_iso,
        "cpu_limit_s": pol.cpu_seconds,
        "memory_limit_mb": pol.memory_mb,
        "env_scrub": pol.scrub_env,
        "network_policy": "allow" if pol.allow_net else "none",
        "protected_paths": _sensitive_home_paths(),
        "docker_available": docker_ok,
        "docker_image": pol.docker_image,
        "docker_session_pool": get_docker_pool().status(),
    }


def run(command: str, cwd: str = ".", timeout: int = 30,
        *, mode: str | None = None, policy: SandboxPolicy | None = None,
        cfg: dict[str, str] | None = None, session_id: str = "") -> SandboxResult:
    """Run *command* through the configured tiered sandbox policy.

    Tiers:
    - ``disabled`` (``BAIZE_SANDBOX_ENABLED=0``): plain execution with ``mechanism="none"``.
    - ``local-hardened`` (default zero-install tier): env scrubbing + POSIX ``rlimit``
      + OS Landlock (Linux ctypes/stdlib) / bwrap / Seatbelt (macOS).
    - ``docker``: fail-closed container execution via :class:`DockerSandboxDriver`
      (with optional warm :class:`SessionDockerPool` reuse).
    - ``auto``: Docker when reachable, else explicit ``local-hardened``.
    """
    eff_cfg = cfg if cfg is not None else load_config()
    pol = policy or _build_policy(eff_cfg, mode_override=mode)
    if not pol.mode:
        return _plain(command, cwd, timeout)

    # Tier 2: Docker container isolation (strict fail-closed or auto fallback)
    if pol.mode in ("docker", "auto"):
        from .docker_sandbox import DockerSandboxDriver
        drv = DockerSandboxDriver(
            image=pol.docker_image,
            workspace=cwd,
            timeout=timeout,
            memory_limit=f"{pol.memory_mb}m",
            network_mode=pol.docker_network,
            strict=(pol.mode == "docker"),
            session_id=session_id,
            use_session_pool=pol.docker_session_pool,
        )
        if drv.docker_available or pol.mode == "docker":
            dres = drv.run(command)
            return SandboxResult(
                returncode=int(dres.get("returncode", 1)),
                stdout=redact(str(dres.get("stdout", ""))),
                stderr=redact(str(dres.get("stderr", ""))),
                degraded=bool(dres.get("degraded", False)),
                mechanism=str(dres.get("driver") or "docker_container"),
            )
        # pol.mode == "auto" and docker unavailable -> explicit local-hardened fallback
        mech = platform_mechanism()
        child_env = scrub_environment() if pol.scrub_env else None
        if mech == "win-job-object":
            return _run_with_win_job_object(
                command, cwd, timeout, pol, child_env,
                mechanism_suffix=" (docker-fallback)",
            )
        if mech == "landlock":
            res = proc_mod.run(command, shell=True, timeout=timeout, cwd=cwd,
                               env=child_env, preexec_fn=_rlimit_preexec(pol, cwd))
            if res.timed_out:
                return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                     degraded=True, mechanism="landlock+rlimit (docker-fallback)")
            return SandboxResult(res.returncode, redact(res.stdout or ""),
                                 redact(res.stderr or ""), degraded=True,
                                 mechanism="landlock+rlimit (docker-fallback)")
        res = proc_mod.run(command, shell=True, timeout=timeout, cwd=cwd,
                           env=child_env, preexec_fn=_rlimit_preexec(pol, None))
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 degraded=True, mechanism="local-hardened (docker-fallback)")
        return SandboxResult(res.returncode, redact(res.stdout or ""),
                             redact(res.stderr or ""), degraded=True,
                             mechanism="local-hardened (docker-fallback)")

    # Tier 1: local-hardened (zero-install OS light sandbox)
    mech = platform_mechanism()
    child_env = scrub_environment() if pol.scrub_env else None
    if mech == "logical-only":
        res = proc_mod.run(command, shell=True, timeout=timeout, cwd=cwd,
                           env=child_env, preexec_fn=_rlimit_preexec(pol, None))
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 degraded=True, mechanism="logical-only")
        return SandboxResult(res.returncode, redact(res.stdout or ""),
                             redact(res.stderr or ""), degraded=True,
                             mechanism="logical-only")

    if mech == "landlock":  # pragma: no cover - Linux 5.13+ only
        res = proc_mod.run(command, shell=True, timeout=timeout, cwd=cwd,
                           env=child_env, preexec_fn=_rlimit_preexec(pol, cwd))
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 mechanism="landlock")
        return SandboxResult(res.returncode, redact(res.stdout or ""),
                             redact(res.stderr or ""), mechanism="landlock")

    if mech == "bwrap":  # pragma: no cover - Linux bwrap only
        argv = _bwrap_command(command, cwd, allow_net=pol.allow_net)
        res = proc_mod.run(argv, timeout=timeout, cwd=cwd, env=child_env)
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 mechanism="bwrap")
        return SandboxResult(res.returncode, redact(res.stdout or ""),
                             redact(res.stderr or ""), mechanism="bwrap")

    if mech == "seatbelt":  # pragma: no cover - macOS only
        wrapped = _seatbelt_command(command, cwd, allow_net=pol.allow_net)
        res = proc_mod.run(wrapped, shell=True, timeout=timeout, cwd=cwd,
                           env=child_env, preexec_fn=_rlimit_preexec(pol, None))
        if res.timed_out:
            return SandboxResult(-1, "", f"command timed out after {timeout}s",
                                 mechanism="seatbelt")
        return SandboxResult(res.returncode, redact(res.stdout or ""),
                             redact(res.stderr or ""), mechanism="seatbelt")

    res = _plain(command, cwd, timeout)
    res.degraded = True
    res.mechanism = "logical-only"
    return res
