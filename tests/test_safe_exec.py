"""Tests for the restricted-builtin execution namespace.

These pin two opposite obligations, and both matter:

  * it must REFUSE the naive escape payloads (import os, open, eval, ...), and
  * it must still ALLOW legitimate generated tool code, which imports pure
    stdlib modules such as `re` and `json`.

The second obligation is a regression guard: an earlier version of this module
dropped `__import__` entirely, which silently broke
MetaToolSynthesizer.certify_tool for any tool that imports anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.safe_exec import (  # noqa: E402
    ALLOWED_MODULES,
    FORBIDDEN_BUILTINS,
    SAFE_BUILTINS,
    exec_restricted,
    restricted_globals,
)


# ---------------------------------------------------------------------------
# the guardrail must hold
# ---------------------------------------------------------------------------

#: Modules that must never be importable from generated code. Every one of these
#: leads to filesystem, process, or import-machinery access.
BLOCKED_MODULES = (
    "os", "sys", "io", "pathlib", "shutil", "subprocess", "socket",
    "importlib", "builtins", "ctypes", "pickle", "marshal", "tempfile",
    "glob", "sqlite3", "asyncio", "http", "platform", "resource", "signal",
    "threading", "multiprocessing", "gc", "inspect", "traceback",
)


@pytest.mark.parametrize("module", BLOCKED_MODULES)
def test_dangerous_module_is_refused(module):
    with pytest.raises(ImportError):
        exec_restricted(f"import {module}")


def test_from_import_of_dangerous_module_is_refused():
    with pytest.raises(ImportError):
        exec_restricted("from os import system")


def test_relative_import_is_refused():
    """level != 0 resolves through the caller's package and would sidestep the
    name check, so it must be refused outright."""
    with pytest.raises(ImportError, match="relative import"):
        exec_restricted("from . import anything", seed={"__package__": "baize"})


def test_dynamic_import_of_dangerous_module_is_refused():
    """`import x` compiles to a call of the namespace's __import__, so an
    explicit call must hit the same allowlist."""
    with pytest.raises(ImportError):
        exec_restricted("m = __import__('os')")


def test_open_is_not_available():
    with pytest.raises(NameError):
        exec_restricted("open('/tmp/should-never-exist', 'w')")


@pytest.mark.parametrize("name", ["eval", "exec", "compile", "globals", "locals",
                                  "vars", "getattr", "setattr", "input",
                                  "breakpoint", "object", "type", "__build_class__"])
def test_dangerous_builtin_is_not_in_namespace(name):
    with pytest.raises(NameError):
        exec_restricted(f"{name}")


def test_forbidden_builtins_never_overlap_the_exposed_set():
    """The allowlist and the denylist must not contradict each other.

    This is the assertion FORBIDDEN_BUILTINS' docstring promises; without it the
    set is decoration.
    """
    leaked = sorted(FORBIDDEN_BUILTINS & set(SAFE_BUILTINS))
    assert leaked == [], f"forbidden names exposed as builtins: {leaked}"


def test_restricted_globals_is_fresh_per_call():
    a = restricted_globals()
    b = restricted_globals()
    assert a is not b
    assert a["__builtins__"] is not b["__builtins__"]


# ---------------------------------------------------------------------------
# legitimate code must still work
# ---------------------------------------------------------------------------

def test_import_of_allowlisted_module_works():
    ns = exec_restricted("import re\ndef f(): return re.sub(r'\\s+', '-', 'a b')")
    assert ns["f"]() == "a-b"


def test_from_import_of_allowlisted_module_works():
    ns = exec_restricted("from json import dumps\ndef f(): return dumps({'a': 1})")
    assert ns["f"]() == '{"a": 1}'


def test_import_inside_a_function_body_works():
    """`import re` inside a function is the common shape in generated tool code
    and compiles differently from a module-level import."""
    ns = exec_restricted("""
def clean(raw):
    import re
    return re.sub(r'[^a-zA-Z0-9_]', '_', raw.strip())
""")
    assert ns["clean"]("hello-world 123!") == "hello_world_123_"


def test_multi_function_snippet_resolves_cross_references():
    """Regression: separate globals/locals dicts made a top-level function
    invisible to another top-level function (NameError)."""
    ns = exec_restricted("def a(): return 41\ndef b(): return a() + 1")
    assert ns["b"]() == 42


def test_seed_is_visible_to_executed_code():
    ns = exec_restricted("out = base * 2", seed={"base": 21})
    assert ns["out"] == 42


@pytest.mark.parametrize("module", sorted(ALLOWED_MODULES))
def test_every_allowlisted_module_actually_imports(module):
    """A typo in ALLOWED_MODULES would only surface at runtime otherwise."""
    exec_restricted(f"import {module}")
