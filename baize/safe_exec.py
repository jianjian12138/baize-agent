"""Constrained namespace for executing caller-supplied Python.

THIS IS A GUARDRAIL, NOT A SANDBOX.

Be precise about what this buys you, because the difference matters:

  * It removes the trivial escape hatches. ``import os``, ``open(...)``,
    ``eval``, ``exec`` and ``compile`` are not usable: the first is refused by
    the allowlisted ``__import__``, the rest are simply absent from the
    namespace, so the obvious payloads fail with ImportError or NameError.
  * It does NOT contain a determined attacker. Anything reachable through the
    exposed builtins can still be walked: ``getattr`` plus string concatenation
    defeats any name-based check, ``object.__subclasses__`` remains reachable
    from a bare literal, and every allowed module object exposes
    ``__loader__.get_data(path)``, which reads arbitrary files. The import
    allowlist raises the cost of a payload; it does not bound what a payload can
    reach. ``baize/tools.py`` documents the same limitation for ``run_python``.

So this module is the *second* line. The first line is the caller's
authorisation gate - see ``baize/serve.py::_code_exec_gate``, which requires a
configured bearer token and an explicit opt-in before any of this is reached.
Never treat a restricted namespace as a substitute for an access-control check.

Used by:
  * ``baize/tooling/synthesizer.py``  (meta-tool self-certification)
  * ``baize/orchestration/adversarial.py``  (red/blue battle rounds)
"""
from __future__ import annotations

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
