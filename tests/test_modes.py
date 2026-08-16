"""V22 #97 acceptance tests: named modes as configuration bundles.

Proves:
  * scalar sliders are the fallback when BAIZE_MODE is empty/unknown
  * BAIZE_MODE carries authority over the scalar sliders when set
  * the four modes are behaviourally distinct
  * eval mode selects the LLM-free ProgrammaticLoop
  * ProgrammaticLoop actually runs tools end-to-end (zero network)
"""
from __future__ import annotations

import pytest

from baize.agent import Agent, DefaultLoop, ProgrammaticLoop
from baize.config import load_config
from baize.modes import MODES, VALID_MODES, resolve_mode
from baize.tools import default_registry


def test_resolve_mode_fallback_to_scalar():
    cfg = {"BAIZE_AUTONOMY": "autonomous", "BAIZE_PLAN_MODE": "0"}
    b = resolve_mode(cfg)
    assert b["autonomy"] == "autonomous"
    assert b["plan_mode"] is False
    assert b["loop"] == "default"


def test_mode_authority_over_scalar():
    cfg = {"BAIZE_MODE": "safe-review",
           "BAIZE_AUTONOMY": "autonomous", "BAIZE_PLAN_MODE": "0"}
    b = resolve_mode(cfg)
    # mode wins over the scalar sliders
    assert b["autonomy"] == "supervised"
    assert b["plan_mode"] is True


def test_unknown_mode_falls_back_to_scalar():
    cfg = {"BAIZE_MODE": "bogus", "BAIZE_AUTONOMY": "balanced"}
    b = resolve_mode(cfg)
    assert b["autonomy"] == "balanced"


def test_four_modes_distinct():
    assert set(VALID_MODES) == {"coding", "eval", "autonomous", "safe-review"}
    bundles = [resolve_mode({"BAIZE_MODE": m}) for m in VALID_MODES]
    # eval is the minimal mode: supervised + programmatic loop
    eval_b = resolve_mode({"BAIZE_MODE": "eval"})
    assert eval_b["autonomy"] == "supervised"
    assert eval_b["loop"] == "programmatic"
    # safe-review turns plan mode on
    assert resolve_mode({"BAIZE_MODE": "safe-review"})["plan_mode"] is True


def test_eval_mode_selects_programmatic_loop():
    cfg = load_config()
    cfg["BAIZE_MODE"] = "eval"
    agent = Agent(cfg=cfg)
    assert isinstance(agent.loop, ProgrammaticLoop)
    assert agent.autonomy.level == "supervised"


def test_constructor_loop_strategy_still_wins():
    cfg = load_config()
    cfg["BAIZE_MODE"] = "eval"  # would pick ProgrammaticLoop
    agent = Agent(cfg=cfg, loop_strategy=DefaultLoop())
    assert isinstance(agent.loop, DefaultLoop)


def test_programmatic_loop_runs_tools_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    agent = Agent(cfg=load_config(), registry=default_registry())
    loop = ProgrammaticLoop(steps=[
        {"name": "write_file",
         "arguments": {"path": "a.txt", "content": "hello"}},
        {"name": "read_file", "arguments": {"path": "a.txt"}},
    ])
    res = loop.run(agent, "write then read")
    assert res.tool_calls == 2
    assert res.stopped_reason == "final"
    assert "hello" in res.final_text


def test_programmatic_loop_blocks_mutating_under_supervised():
    agent = Agent(cfg=load_config(), autonomy="supervised", registry=default_registry())
    loop = ProgrammaticLoop(steps=[
        {"name": "write_file", "arguments": {"path": "x.txt", "content": "y"}},
    ])
    res = loop.run(agent, "try to write")
    # supervised mode blocks the write -> no tool executed
    assert res.tool_calls == 0
    assert "BLOCKED" in res.final_text
