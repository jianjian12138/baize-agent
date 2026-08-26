"""W2 F4 — team thin configuration layer (zero deps, JSON only).

Verifies that a roles.json drives a thin-config team that reuses the existing
Orchestrator (Director -> Executor -> Verifier) without reimplementing it, and
that malformed configs fail closed (red line B) rather than silently defaulting.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from baize.orchestrator import Orchestrator
from baize.team import Role, TeamConfig, build_team, load_roles


def _write_cfg(d: dict) -> str:
    fd, p = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f)
    return p


def test_role_from_dict_validates_name():
    r = Role.from_dict({"name": "Researcher", "description": "find facts",
                        "tools": ["web_search"], "model": "gpt"})
    assert r.name == "Researcher"
    assert r.tools == ["web_search"]
    assert r.model == "gpt"
    with pytest.raises(ValueError):
        Role.from_dict({"description": "no name"})
    with pytest.raises(ValueError):
        Role.from_dict("not a dict")


def test_team_config_roundtrip_and_validation():
    cfg = TeamConfig(roles=[Role(name="A"), Role(name="B")],
                     max_retries_per_task=3, team_id="t1")
    cfg2 = TeamConfig.from_dict(cfg.to_dict())
    assert [r.name for r in cfg2.roles] == ["A", "B"]
    assert cfg2.max_retries_per_task == 3
    with pytest.raises(ValueError):
        TeamConfig.from_dict({"max_retries_per_task": -1})
    with pytest.raises(ValueError):
        TeamConfig.from_dict({"max_retries_per_task": "x"})
    with pytest.raises(ValueError):
        TeamConfig.from_dict("nope")


def test_load_roles_reads_json_and_fails_closed():
    p = _write_cfg({"team_id": "demo",
                    "roles": [{"name": "Researcher", "description": "r"}]})
    cfg = load_roles(p)
    assert cfg.roles[0].name == "Researcher"
    os.remove(p)
    with pytest.raises(FileNotFoundError):
        load_roles("/no/such/roles.json")
    bad = _write_cfg({})
    open(bad, "w").write("{not valid json")
    with pytest.raises(ValueError):
        load_roles(bad)
    os.remove(bad)


def test_build_team_reuses_orchestrator(monkeypatch):
    # Stub TeamMemory so the test leaves no on-disk memory artifacts.
    import baize.team as team_mod

    class _FakeTM:
        def post(self, role, text, tags=None):
            return {"role": role}

    monkeypatch.setattr(team_mod, "TeamMemory", lambda *a, **k: _FakeTM())
    cfg = TeamConfig(roles=[Role(name="Researcher")], max_retries_per_task=2)
    orch = build_team(cfg, client=None)
    assert isinstance(orch, Orchestrator)
    assert orch.team_config is cfg
    assert orch.max_retries == 2  # config wired through to the orchestrator
