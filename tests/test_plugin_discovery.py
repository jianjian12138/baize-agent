"""V22 #99 acceptance tests + F1 hardening: component discovery trust boundary.

Proves third-party components are auto-discovered from the plugin roots,
registered into the kernel, and - critically - ISOLATED:
  * a broken/malicious component is logged + skipped (host never crashes);
  * a security-critical component (sandbox/tool/session) is REJECTED even on
    the success path (never trusted by default) - closing deepseek-harness's
    "third-party plugins trusted by default" weakness (#2). Extensibility is
    preserved for non-security-critical kinds (e.g. ui).
"""
from __future__ import annotations

from baize.component import Kind, get_kernel, reset_runtime, _SandboxAdapter
from baize.plugin import registry


GOOD_UI = '''
from baize.plugin import Plugin
from baize.component import Kind

class MyPlugin(Plugin):
    name = "my-plugin"

class MyUI:
    KIND = "ui"
    def __init__(self):
        self.events = []
    def event(self, kind, detail=""):
        self.events.append((kind, detail))
    @staticmethod
    def build(cfg):
        return MyUI()
'''

EVIL_SANDBOX = '''
from baize.plugin import Plugin
from baize.component import Kind

class MyPlugin(Plugin):
    name = "my-plugin"

class MySandbox:
    KIND = "sandbox"
    @staticmethod
    def build(cfg):
        return _A()
class _A:
    def run(self, command, cwd=None, timeout=60, cfg=None):
        return "PLUGIN:" + command
'''

BROKEN = '''
from baize.component import Kind

class BrokenSandbox:
    KIND = "sandbox"
    @staticmethod
    def build(cfg):
        raise RuntimeError("malicious/buggy component")
'''


def test_plugin_discovers_non_critical_component(monkeypatch, tmp_path):
    reset_runtime()
    registry.plugins.clear()
    try:
        (tmp_path / "good_plug.py").write_text(GOOD_UI, encoding="utf-8")
        monkeypatch.setenv("BAIZE_PLUGINS_DIR", str(tmp_path))
        found = registry.discover()
        assert found >= 1  # the MyPlugin Plugin subclass is loaded
        kernel = get_kernel()
        assert Kind.UI in kernel.components
        rt = kernel.assemble()  # must resolve the discovered (non-critical) component
        ui = rt.get(Kind.UI)
        ui.event("x", "y")
        assert ("x", "y") in ui.events
    finally:
        reset_runtime()
        registry.plugins.clear()


def test_plugin_security_critical_sandbox_rejected(monkeypatch, tmp_path):
    """F1: an auto-discovered SANDBOX is rejected; the trusted built-in default
    is kept and actually runs (not the plugin's "PLUGIN:ls")."""
    reset_runtime()
    registry.plugins.clear()
    try:
        (tmp_path / "evil_plug.py").write_text(EVIL_SANDBOX, encoding="utf-8")
        monkeypatch.setenv("BAIZE_PLUGINS_DIR", str(tmp_path))
        registry.discover()
        kernel = get_kernel()
        rt = kernel.assemble()
        assert isinstance(rt.get(Kind.SANDBOX), _SandboxAdapter)
        assert not str(rt.get(Kind.SANDBOX).run("ls")).startswith("PLUGIN:")
    finally:
        reset_runtime()
        registry.plugins.clear()


def test_plugin_broken_component_isolated(monkeypatch, tmp_path):
    reset_runtime()
    registry.plugins.clear()
    try:
        (tmp_path / "broken_plug.py").write_text(BROKEN, encoding="utf-8")
        monkeypatch.setenv("BAIZE_PLUGINS_DIR", str(tmp_path))
        # discovery must NOT raise even though the component is broken
        registry.discover()
        kernel = get_kernel()
        # assemble must not crash; the broken sandbox is rejected at registration
        # (security-critical) and the built-in default is kept.
        rt = kernel.assemble()
        assert isinstance(rt.get(Kind.SANDBOX), _SandboxAdapter)
    finally:
        reset_runtime()
        registry.plugins.clear()


PLUGIN_HOOK = '''
from baize.plugin import Plugin

class Recorder(Plugin):
    name = "recorder"
    hooks = ["on_tool_call"]
    def __init__(self):
        self.seen = []
    def on_tool_call(self, tool, args):
        self.seen.append(tool)
'''


def test_plugin_lifecycle_load_and_fire(monkeypatch, tmp_path):
    """The pre-existing Plugin hook system: a plugin is loaded on discover and
    its hooks fire via registry.fire() (lifecycle observation, not core-unit
    replacement)."""
    (tmp_path / "rec_plug.py").write_text(PLUGIN_HOOK, encoding="utf-8")
    monkeypatch.setenv("BAIZE_PLUGINS_DIR", str(tmp_path))
    registry.discover()
    rec = next((p for p in registry.plugins if p.name == "recorder"), None)
    assert rec is not None, "plugin was not loaded"
    registry.fire("on_tool_call", "bash", {"command": "ls"})
    assert "bash" in rec.seen
