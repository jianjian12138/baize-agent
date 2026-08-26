"""Verify chaos fault injection is wired into LLMClient's default transport.

When BAIZE_CHAOS_ENABLED=1 and a failure rate > 0, the default HTTP transport is
wrapped so real failures are injected - proving the retry / fail-closed paths
actually run (NO FAKE DONE). Chaos is OFF by default, so normal runs are
untouched and an explicitly injected transport is never wrapped (test isolation).

Chaos reads its flags from the resolved config (``load_config`` -> .env), which
is exactly how it is driven in production; these tests pass the same keys via the
``cfg`` dict to exercise the real code path without touching the filesystem.
"""
from __future__ import annotations

import pytest

from baize.chaos import ChaosError
from baize.llm import LLMClient, LLMError


def _cfg(**extra):
    base = {
        "BAIZE_MODEL_BASE_URL": "https://example.invalid/v1",
        "BAIZE_MODEL_NAME": "stub",
        "BAIZE_MODEL_API_KEY": "sk-stub",
    }
    base.update(extra)
    return base


def test_explicit_transport_is_never_wrapped(monkeypatch):
    """An injected transport stays untouched - chaos only wraps the default."""
    monkeypatch.delenv("BAIZE_CHAOS_ENABLED", raising=False)
    calls = []

    def fake(url, headers, payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    client = LLMClient(cfg=_cfg(), transport=fake)
    assert client.chat([{"role": "user", "content": "hi"}])["content"] == "ok"
    assert calls  # the fake was actually used
    # the injected one must remain the bare callable we passed, not a wrapper.
    assert client.transport is fake


def test_chaos_enabled_injects_transport_fault():
    client = LLMClient(cfg=_cfg(
        BAIZE_CHAOS_ENABLED="1",
        BAIZE_CHAOS_FAILURE_RATE="1.0",
        BAIZE_CHAOS_SEED="deterministic",
    ))
    # Every call faults before reaching the network, so chat exhausts its
    # retries and raises LLMError - proving the wrapped transport fired.
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}])


def test_chaos_report_records_injections():
    client = LLMClient(cfg=_cfg(
        BAIZE_CHAOS_ENABLED="1",
        BAIZE_CHAOS_FAILURE_RATE="1.0",
        BAIZE_CHAOS_SEED="r2",
    ))
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}])
    rep = client._chaos.report()
    assert rep["enabled"] is True
    assert rep["total_injected"] > 0
