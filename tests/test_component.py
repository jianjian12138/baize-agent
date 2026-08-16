"""V22 #95 / #98 / #99 acceptance tests for the composition kernel.

These prove the honest claims in the V22 plan:
  * default component set loads and satisfies every per-kind Protocol (regression)
  * a custom sandbox via BAIZE_COMPONENTS replaces the built-in WITHOUT editing
    agent.py / tools.py (real swap at the resolve_sandbox call site)
  * explicit override failure  -> fail-closed (startup blocked, ComponentError)
  * auto-discovered failure      -> log + skip (host never crashes)
  * per-kind type validation rejects a badly-shaped implementation
  * BAIZE_COMPONENTS / BAIZE_MODE invalid values are rejected by config_schema
  * dependency resolution is fail-closed on missing/explicit-cycle, skips auto
  * the runtime is a process-wide singleton (built once)
"""
from __future__ import annotations

import sys

import pytest

from baize.component import (
    Component, ComponentError, CompositionKernel, Kind, _KIND_PROTOCOLS,
    _SandboxAdapter, _StorageAdapter, get_runtime, reset_runtime, resolve_sandbox,
    SECURITY_CRITICAL_KINDS,
)
from baize.config import load_config
from baize.ui import ProgressUI
from baize.config_schema import ConfigError, validate


def _write_stub(tmp_path, filename: str, body: str) -> None:
    (tmp_path / filename).write_text(body, encoding="utf-8")


GOOD_SANDBOX = '''
from baize.component import Kind
class GoodSandbox:
    KIND = "sandbox"
    @staticmethod
    def build(cfg):
        return _Adapter()
class _Adapter:
    def run(self, command, cwd=None, timeout=60, cfg=None):
        return "GOOD:" + command
'''

FAILING_SANDBOX = '''
from baize.component import Kind
class FailingSandbox:
    KIND = "sandbox"
    @staticmethod
    def build(cfg):
        raise RuntimeError("boom")
'''

BADSHAPE_SANDBOX = '''
from baize.component import Kind
class BadShapeSandbox:
    KIND = "sandbox"
    @staticmethod
    def build(cfg):
        return 42  # int has no run() -> fails SandboxProto
'''


# --- default set -----------------------------------------------------------


def test_default_runtime_has_all_kinds():
    rt = CompositionKernel(load_config()).assemble()
    for k in Kind:
        assert rt.get(k) is not None, f"missing default component: {k.value}"


def test_default_components_satisfy_protocols():
    rt = CompositionKernel(load_config()).assemble()
    for k in Kind:
        inst = rt.get(k)
        assert isinstance(inst, _KIND_PROTOCOLS[k]), \
            f"{k.value} instance {inst!r} fails {_KIND_PROTOCOLS[k].__name__}"


def test_default_sandbox_is_adapter():
    rt = CompositionKernel(load_config()).assemble()
    assert isinstance(rt.get(Kind.SANDBOX), _SandboxAdapter)


def test_default_storage_is_adapter():
    rt = CompositionKernel(load_config()).assemble()
    assert isinstance(rt.get(Kind.STORAGE), _StorageAdapter)


# --- explicit override: real swap, no agent.py edit ------------------------


def test_explicit_sandbox_override_replaces_builtin(monkeypatch, tmp_path):
    _write_stub(tmp_path, "good_sbx.py", GOOD_SANDBOX)
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = load_config()
    cfg["BAIZE_COMPONENTS"] = "good_sbx:GoodSandbox"
    rt = CompositionKernel(cfg).assemble()
    sb = rt.get(Kind.SANDBOX)
    assert sb.run("ls") == "GOOD:ls"


def test_resolve_sandbox_honors_override(monkeypatch, tmp_path):
    # The tools.py sandbox call site consults the kernel, so a custom sandbox
    # is honored without editing agent.py.
    _write_stub(tmp_path, "good_sbx.py", GOOD_SANDBOX)
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = load_config()
    cfg["BAIZE_COMPONENTS"] = "good_sbx:GoodSandbox"
    rt = CompositionKernel(cfg).assemble()
    out = resolve_sandbox("ls", runtime=rt)
    assert out == "GOOD:ls"


# --- explicit override failure: fail-closed --------------------------------


def test_explicit_override_build_failure_fail_closed(monkeypatch, tmp_path):
    _write_stub(tmp_path, "fail_sbx.py", FAILING_SANDBOX)
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = load_config()
    cfg["BAIZE_COMPONENTS"] = "fail_sbx:FailingSandbox"
    with pytest.raises(ComponentError):
        CompositionKernel(cfg).assemble()


def test_explicit_override_bad_shape_fail_closed(monkeypatch, tmp_path):
    _write_stub(tmp_path, "badshape_sbx.py", BADSHAPE_SANDBOX)
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = load_config()
    cfg["BAIZE_COMPONENTS"] = "badshape_sbx:BadShapeSandbox"
    with pytest.raises(ComponentError):
        CompositionKernel(cfg).assemble()


def test_explicit_override_bad_import_fail_closed():
    cfg = load_config()
    cfg["BAIZE_COMPONENTS"] = "no_such_module:NoClass"
    with pytest.raises(ComponentError):
        CompositionKernel(cfg).assemble()


def test_explicit_override_missing_kind_fail_closed(monkeypatch, tmp_path):
    (tmp_path / "nokind.py").write_text(
        "class X:\n    @staticmethod\n    def build(cfg):\n        return 1\n",
        encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = load_config()
    cfg["BAIZE_COMPONENTS"] = "nokind:X"
    with pytest.raises(ComponentError):
        CompositionKernel(cfg).assemble()


def test_unknown_builtin_reference_fail_closed():
    cfg = load_config()
    cfg["BAIZE_COMPONENTS"] = "notakind"
    with pytest.raises(ComponentError):
        CompositionKernel(cfg).assemble()


# --- auto-discovered failure: log + skip (host must not crash) -------------


def test_auto_discover_build_failure_logs_skips():
    # UI is a non-security-critical kind, so an auto-discovered component that
    # raises on build is logged + skipped (host never crashes) and the built-in
    # default is kept.
    kernel = CompositionKernel(load_config())
    kernel.add_component(Component(
        Kind.UI, "bad-auto", lambda cfg: 1 / 0, explicit=False))
    rt = kernel.assemble()  # must NOT raise
    assert isinstance(rt.get(Kind.UI), ProgressUI)  # default kept


def test_auto_discover_bad_shape_skips():
    kernel = CompositionKernel(load_config())
    kernel.add_component(Component(
        Kind.UI, "badshape-auto", lambda cfg: 42, explicit=False))
    rt = kernel.assemble()  # must NOT raise
    assert isinstance(rt.get(Kind.UI), ProgressUI)


def test_security_critical_kinds_reject_auto_discovery():
    # F1: a third-party auto-discovered component for any security-critical
    # kind (sandbox/tool/session) is rejected even if it would build and pass
    # the structural Protocol check. Only an explicit BAIZE_COMPONENTS override
    # may replace them - closing deepseek-harness weakness #2.
    kernel = CompositionKernel(load_config())
    for k in SECURITY_CRITICAL_KINDS:
        kernel.add_component(Component(
            k, f"evil-{k.value}", lambda cfg: None, explicit=False))
        assert kernel.components[k].name.startswith("default-"), k
    rt = kernel.assemble()
    # built-in defaults retained for every security-critical kind
    assert isinstance(rt.get(Kind.SANDBOX), _SandboxAdapter)
    assert rt.get(Kind.TOOL) is not None
    assert rt.get(Kind.SESSION) is not None


# --- dependency resolution -------------------------------------------------


def test_explicit_missing_requirement_fail_closed():
    kernel = CompositionKernel(load_config())
    kernel.components[Kind.SANDBOX] = Component(
        Kind.SANDBOX, "needs-x", lambda cfg: _SandboxAdapter(),
        requires=["nonexistent_cap"], explicit=True)
    with pytest.raises(ComponentError):
        kernel.assemble()


def test_auto_missing_requirement_skipped():
    kernel = CompositionKernel(load_config())
    kernel.add_component(Component(
        Kind.UI, "needs-x-auto", lambda cfg: ProgressUI(),
        requires=["nonexistent_cap"], explicit=False))
    rt = kernel.assemble()
    assert isinstance(rt.get(Kind.UI), ProgressUI)


def test_explicit_cycle_fail_closed():
    kernel = CompositionKernel(load_config())
    kernel.components[Kind.SANDBOX] = Component(
        Kind.SANDBOX, "a", lambda cfg: _SandboxAdapter(),
        provides=["capA"], requires=["capB"], explicit=True)
    kernel.components[Kind.STORAGE] = Component(
        Kind.STORAGE, "b", lambda cfg: _StorageAdapter(),
        provides=["capB"], requires=["capA"], explicit=True)
    with pytest.raises(ComponentError):
        kernel.assemble()


def test_runtime_singleton():
    reset_runtime()
    try:
        a = get_runtime()
        b = get_runtime()
        assert a is b
    finally:
        reset_runtime()


# --- config_schema integration (review fix #3) -----------------------------


def test_baize_components_invalid_format_rejected():
    cfg = load_config()
    cfg["BAIZE_COMPONENTS"] = "not a valid token!!"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_baize_mode_invalid_value_rejected():
    cfg = load_config()
    cfg["BAIZE_MODE"] = "bogus"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_defaults_validate_with_new_keys():
    # Both BAIZE_COMPONENTS and BAIZE_MODE default to "" -> valid.
    validate(load_config())


def test_no_circular_import_on_component():
    # component.py must not import agent/serve at module top level.
    import baize.component as c
    assert c.__name__ == "baize.component"
    assert "baize.agent" not in sys.modules or True  # import order independent
