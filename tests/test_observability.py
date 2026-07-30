"""Coverage for observability, secrets, and the tool SDK extension point.

These modules are small and fully functional (only a Vault *integration point*
is reserved), so they earn their keep in coverage rather than being omitted.
"""
from __future__ import annotations

import importlib

from baize import secrets as secrets_mod
from baize.observability import obs
from baize.tool_sdk import tool


def test_obs_counters_and_prometheus():
    obs.reset()
    obs.inc("llm_calls")
    obs.inc("llm_calls", 2)
    obs.gauge("active_sessions", 3.0)
    obs.record_error("boom")
    text = obs.prometheus()
    assert "baize_llm_calls 3" in text
    assert "baize_active_sessions 3.0" in text
    assert "baize_boom 1" in text
    # bounded span buffer + spans() accessor
    assert obs.spans(5) == []


def test_obs_disabled_is_noop():
    obs.reset()
    obs.enable(False)
    obs.inc("x")
    obs.gauge("y", 1.0)
    assert obs.prometheus() == "\n"
    obs.enable(True)


def test_obs_span_records_failure_and_reraises():
    obs.reset()
    with obs.span("work"):
        pass
    try:
        with obs.span("failing"):
            raise ValueError("nope")
    except ValueError:
        pass
    assert obs._counters.get("errors", 0) == 1


def test_get_secret_env_then_config_then_default(monkeypatch):
    monkeypatch.delenv("MY_TOKEN", raising=False)
    monkeypatch.setenv("MY_TOKEN", "from-env")
    assert secrets_mod.get_secret("MY_TOKEN") == "from-env"

    # unset env -> falls back to config (via BAIZE_* style key)
    monkeypatch.delenv("MY_TOKEN", raising=False)
    monkeypatch.setenv("BAIZE_FOO", "from-config")
    assert secrets_mod.get_secret("BAIZE_FOO") == "from-config"

    # nothing set -> default
    assert secrets_mod.get_secret("NEVER_SET_XYZ", default="fallback") == "fallback"


def test_get_secret_vault_not_implemented_records_error(monkeypatch):
    monkeypatch.delenv("MY_API_KEY", raising=False)
    # emulate a configured-but-unimplemented vault endpoint
    monkeypatch.setenv("BAIZE_VAULT_URL", "https://vault.example")
    before = obs._counters.get("vault_not_implemented", 0)
    assert secrets_mod.get_secret("MY_API_KEY", default="d") == "d"
    assert obs._counters.get("vault_not_implemented", 0) == before + 1


def test_tool_decorator_registers_into_registry():
    registry = __import__("baize.tools", fromlist=["default_registry"]).default_registry()

    @tool(name="demo", description="demo tool", args={"x": "string"})
    def demo(x: str) -> str:
        return f"got {x}"

    # the decorated function is still callable directly
    assert demo("hi") == "got hi"
    # it is discoverable via the registry's public API
    names = registry.names()
    assert "demo" in names
    schema = next(s for s in registry.schemas() if s["function"]["name"] == "demo")
    assert schema["function"]["description"] == "demo tool"
    # execution forwards arguments to the real function
    assert registry.execute("demo", {"x": "yo"}) == "got yo"
    # clean up: the singleton would otherwise leak into other tests
    registry.unregister("demo")
