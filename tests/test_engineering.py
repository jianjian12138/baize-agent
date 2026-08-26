"""V20 engineering layer: structured logging, chaos injection, resilience.

The chaos tests are not theatre: real faults are injected into a real LLM
transport and the real Agent loop must survive them. That is the only way to
prove "defensive design" instead of merely claiming it.
"""
from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.agent import Agent  # noqa: E402
from baize.chaos import Chaos, ChaosError  # noqa: E402
from baize.config import load_config  # noqa: E402
from baize.config_schema import ConfigError, validate  # noqa: E402
from baize.llm import LLMClient  # noqa: E402
from baize.logging_setup import (JsonFormatter, get_logger,  # noqa: E402
                                 redact, setup_logging)
from baize.tools import ToolRegistry  # noqa: E402


# --- redaction (P0: never log credentials) -----------------------------------

@pytest.mark.parametrize("raw,leaked", [
    ("key is sk-abcdefgh12345678", "sk-abcdefgh12345678"),
    ("token ghp_rXZhKpivIE18DyAyDUMnSM7sG98AGL", "ghp_rXZhKpivIE18DyAyDUMnSM"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9", "eyJhbGciOiJIUzI1NiJ9"),
    ('{"api_key": "supersecretvalue"}', "supersecretvalue"),
    ("password=hunter2hunter2", "hunter2hunter2"),
])
def test_redact_masks_credentials(raw, leaked):
    out = redact(raw)
    assert leaked not in out
    assert "***REDACTED***" in out


def test_redact_keeps_normal_text_intact():
    msg = "agent finished in 3 steps with 2 tool calls"
    assert redact(msg) == msg


def test_json_formatter_emits_one_object_per_line():
    rec = logging.LogRecord("baize.test", logging.INFO, __file__, 1,
                            "hello sk-abcdefgh12345678", None, None)
    rec.session_id = "s-1"
    rec.tool = "read_file"
    line = JsonFormatter().format(rec)
    data = json.loads(line)
    assert data["level"] == "INFO"
    assert data["session_id"] == "s-1" and data["tool"] == "read_file"
    assert "sk-abcdefgh" not in data["msg"]      # redaction runs in JSON too
    assert "\n" not in line


def test_setup_logging_is_idempotent():
    buf = io.StringIO()
    for _ in range(3):
        logger = setup_logging({"BAIZE_LOG_LEVEL": "INFO",
                                "BAIZE_LOG_FORMAT": "text"}, stream=buf)
    assert len(logger.handlers) == 1            # handlers replaced, not stacked


def test_logging_json_format_end_to_end():
    buf = io.StringIO()
    setup_logging({"BAIZE_LOG_LEVEL": "DEBUG", "BAIZE_LOG_FORMAT": "json"},
                  stream=buf)
    get_logger("unit").warning("disk almost full")
    payload = json.loads(buf.getvalue().strip())
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "baize.unit"
    assert payload["msg"] == "disk almost full"


def test_log_level_is_respected():
    buf = io.StringIO()
    setup_logging({"BAIZE_LOG_LEVEL": "ERROR", "BAIZE_LOG_FORMAT": "text"},
                  stream=buf)
    log = get_logger("unit")
    log.info("should be filtered")
    log.error("should appear")
    out = buf.getvalue()
    assert "should be filtered" not in out and "should appear" in out


# --- chaos -------------------------------------------------------------------

def test_chaos_disabled_by_default():
    c = Chaos({})
    assert not c.active
    for _ in range(50):
        c.maybe_fail()                 # must never raise when disabled
    assert c.injected == []


def test_chaos_requires_both_flag_and_rate():
    assert not Chaos({"BAIZE_CHAOS_ENABLED": "1",
                      "BAIZE_CHAOS_FAILURE_RATE": "0.0"}).active
    assert not Chaos({"BAIZE_CHAOS_ENABLED": "0",
                      "BAIZE_CHAOS_FAILURE_RATE": "1.0"}).active
    assert Chaos({"BAIZE_CHAOS_ENABLED": "1",
                  "BAIZE_CHAOS_FAILURE_RATE": "1.0"}).active


def test_chaos_always_fails_at_rate_one():
    c = Chaos({"BAIZE_CHAOS_ENABLED": "1", "BAIZE_CHAOS_FAILURE_RATE": "1.0",
               "BAIZE_CHAOS_SEED": "42"})
    with pytest.raises(ChaosError):
        c.maybe_fail("unit")
    assert c.report()["total_injected"] == 1


def test_chaos_is_reproducible_with_seed():
    def faults():
        c = Chaos({"BAIZE_CHAOS_ENABLED": "1",
                   "BAIZE_CHAOS_FAILURE_RATE": "0.5",
                   "BAIZE_CHAOS_SEED": "deterministic"})
        return [c.should_fail() and c.pick_fault() for _ in range(30)]
    assert faults() == faults()        # same seed -> identical fault sequence


def test_chaos_invalid_rate_degrades_safely():
    c = Chaos({"BAIZE_CHAOS_ENABLED": "1", "BAIZE_CHAOS_FAILURE_RATE": "abc"})
    assert c.rate == 0.0 and not c.active
    c2 = Chaos({"BAIZE_CHAOS_ENABLED": "1", "BAIZE_CHAOS_FAILURE_RATE": "9.9"})
    assert c2.rate == 1.0              # clamped, not crashed


# --- resilience: real agent loop under real injected faults ------------------

def _registry():
    reg = ToolRegistry()
    reg.register("echo", "echo text back",
                 {"type": "object", "properties": {"text": {"type": "string"}},
                  "required": ["text"]},
                 lambda text: f"ECHO:{text}")
    return reg


def test_agent_survives_transport_faults_and_still_finishes(env):
    """Chaos raises on the first call; the LLM retry path must recover."""
    calls = {"n": 0}

    def transport(url, headers, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ChaosError("injected transport fault 'connection_reset'")
        return {"choices": [{"message": {"content": "recovered and done"}}]}

    client = LLMClient(cfg=env, transport=transport)
    res = Agent(cfg=env, client=client, registry=_registry()).run("do work")
    assert res.stopped_reason == "final"
    assert "recovered" in res.final_text
    assert calls["n"] >= 2             # proof the retry actually happened


def test_agent_fails_loudly_when_every_call_faults(env):
    """Exhausted retries must surface an error, never a fake success."""
    def transport(url, headers, payload):
        raise ChaosError("injected transport fault 'timeout'")

    client = LLMClient(cfg=env, transport=transport)
    res = Agent(cfg=env, client=client, registry=_registry()).run("do work")
    assert res.stopped_reason != "final"
    assert "ECHO" not in res.final_text


def test_agent_survives_malformed_json_from_chaos(env):
    """A malformed body must degrade gracefully, not crash the loop."""
    chaos = Chaos({"BAIZE_CHAOS_ENABLED": "1",
                   "BAIZE_CHAOS_FAILURE_RATE": "1.0",
                   "BAIZE_CHAOS_SEED": "x"},
                  faults=("malformed_json",))
    real_calls = {"n": 0}

    def real_transport(url, headers, payload):
        real_calls["n"] += 1
        return {"choices": [{"message": {"content": "ok"}}]}

    wrapped = chaos.wrap_transport(real_transport)
    client = LLMClient(cfg=env, transport=wrapped)
    res = Agent(cfg=env, client=client, registry=_registry()).run("do work")
    assert isinstance(res.final_text, str)      # no crash, no exception escape
    assert chaos.report()["total_injected"] > 0


def test_tool_failure_becomes_observation_not_crash(env):
    """A tool that explodes must be reported back to the model, not kill the run."""
    reg = ToolRegistry()

    def boom(**_):
        raise RuntimeError("disk on fire")

    reg.register("boom", "always fails",
                 {"type": "object", "properties": {}}, boom)

    replies = [
        {"content": None, "tool_calls": [{"id": "c1", "type": "function",
         "function": {"name": "boom", "arguments": "{}"}}]},
        {"content": "handled the failure"},
    ]

    def transport(url, headers, payload):
        return {"choices": [{"message": replies.pop(0)}]}

    client = LLMClient(cfg=env, transport=transport)
    agent = Agent(cfg=env, client=client, registry=reg)
    res = agent.run("trigger the failure")
    assert res.stopped_reason == "final"
    tool_msgs = [m for m in agent.session.messages if m.get("role") == "tool"]
    assert "disk on fire" in tool_msgs[0]["content"]


# --- config schema for the new engineering keys ------------------------------

def test_engineering_config_keys_validate():
    cfg = load_config()
    validate(cfg)                       # defaults must be valid


@pytest.mark.parametrize("key,bad", [
    ("BAIZE_LOG_LEVEL", "VERBOSE"),
    ("BAIZE_LOG_FORMAT", "xml"),
    ("BAIZE_CHAOS_FAILURE_RATE", "2.5"),
    ("BAIZE_CHAOS_ENABLED", "maybe"),
])
def test_invalid_engineering_config_rejected(key, bad):
    cfg = dict(load_config())
    cfg[key] = bad
    with pytest.raises(ConfigError):
        validate(cfg)
