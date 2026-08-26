"""V25 F4 — team thin configuration layer (zero deps, no PyYAML).

Loads a team role configuration from a JSON file and builds an Orchestrator
reusing the proven Director -> Executor -> Verifier topology. The config layer
is *thin*: it does NOT reimplement orchestration. It declares custom roles and
seeds them into the shared TeamMemory blackboard so the existing agents can see
them, and it lets the operator tune ``max_retries_per_task``.

Red line A: pure stdlib (``json`` only). YAML is deliberately NOT supported —
importing PyYAML would break the zero-dependency contract (decided in TC-4).
Red line B: invalid configs fail closed (``ValueError``), never silently
default to a built-in topology.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .orchestrator import Orchestrator
from .team_memory import TeamMemory


@dataclass
class Role:
    name: str
    description: str = ""
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)    # V25 compat: kept for backward compat
    model: str | None = None
    # V26-B1: RolePolicy enforcement fields
    allow_tools: list[str] = field(default_factory=list)  # tool whitelist; [] = no restriction
    workspace_scope: str = ""      # path prefix allowed; empty = no restriction
    memory_visibility: str = "read"  # read | write | none

    _VALID_MEMORY_VISIBILITY = frozenset({"read", "write", "none"})

    def effective_allow_tools(self) -> list[str]:
        """Return the active tool whitelist. allow_tools wins over tools (V26 B1)."""
        return self.allow_tools if self.allow_tools else self.tools

    def effective_memory_visibility(self) -> str:
        """Return normalised memory_visibility. Invalid values → 'none' (fail-closed)."""
        v = str(self.memory_visibility or "read")
        if v not in self._VALID_MEMORY_VISIBILITY:
            return "none"
        return v

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": list(self.tools),
            "model": self.model,
            # V26-B1
            "allow_tools": list(self.allow_tools),
            "workspace_scope": self.workspace_scope,
            "memory_visibility": self.memory_visibility,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Role":
        if not isinstance(d, dict) or not str(d.get("name", "")).strip():
            raise ValueError(f"role requires a non-empty 'name': {d!r}")
        return cls(
            name=str(d["name"]).strip(),
            description=str(d.get("description", "")),
            system_prompt=str(d.get("system_prompt", "")),
            tools=list(d.get("tools", [])),
            model=(str(d["model"]) if d.get("model") else None),
            # V26-B1
            allow_tools=list(d.get("allow_tools", [])),
            workspace_scope=str(d.get("workspace_scope", "")),
            memory_visibility=str(d.get("memory_visibility", "read")),
        )


@dataclass
class TeamConfig:
    roles: list[Role] = field(default_factory=list)
    max_retries_per_task: int = 1
    team_id: str = "default"

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "max_retries_per_task": self.max_retries_per_task,
            "roles": [r.to_dict() for r in self.roles],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TeamConfig":
        if not isinstance(d, dict):
            raise ValueError(f"team config must be an object: {d!r}")
        roles = [Role.from_dict(r) for r in d.get("roles", [])]
        try:
            mrt = int(d.get("max_retries_per_task", 1))
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"max_retries_per_task must be an int: {d.get('max_retries_per_task')!r}"
            ) from e
        if mrt < 0:
            raise ValueError(f"max_retries_per_task must be >= 0: {mrt}")
        return cls(roles=roles, max_retries_per_task=mrt,
                   team_id=str(d.get("team_id", "default")))


def load_roles(path: str | Path) -> TeamConfig:
    """Load a team config from JSON.

    YAML is intentionally unsupported (TC-4: no PyYAML dependency). Malformed
    input raises ``ValueError`` (fail closed) rather than silently falling back.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"roles config not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"roles config is not valid JSON: {e}") from e
    return TeamConfig.from_dict(raw)


def build_team(config: TeamConfig,
               client=None, registry=None, on_event=None) -> Orchestrator:
    """Build an Orchestrator from a TeamConfig, reusing the existing
    Director -> Executor -> Verifier topology. Role declarations are posted to
    the shared TeamMemory blackboard so agents can see them.

    Does NOT rewrite orchestration logic. The config is always attached to the
    orchestrator (``orch.team_config``) for introspection; an empty role list
    simply means the built-in three-role topology is used unchanged.
    """
    tm = TeamMemory(team_id=config.team_id)
    for role in config.roles:
        tm.post(role.name,
                (role.description or role.system_prompt
                 or f"role '{role.name}' declared via team config"),
                tags=["role", "team-config"])
    orch = Orchestrator(
        client=client, registry=registry, on_event=on_event,
        max_retries_per_task=config.max_retries_per_task,
        team_memory=tm,
    )
    orch.team_config = config  # introspection hook (no behavior change)
    return orch
