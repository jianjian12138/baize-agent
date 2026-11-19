"""Multi-role team configuration, role policies, and bounded sub-agent runner."""

from __future__ import annotations

# ===========================================================================
# Section: team.py
# ===========================================================================

import json
from dataclasses import dataclass, field
from pathlib import Path

from .orchestrator import Orchestrator
from ..knowledge.memory import TeamMemory


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

# ===========================================================================
# Section: subagent.py
# ===========================================================================

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..core.agent import Agent, Session
from ..execution.tools import ToolRegistry, default_registry

__all__ = ["SubagentDef", "load_subagent", "build_scoped_registry"]


@dataclass
class SubagentDef:
    name: str
    description: str = ""
    tools: list[str] | None = None          # None/[] => all built-in tools
    disallowed_tools: list[str] = field(default_factory=list)
    model: str = "inherit"
    permission_mode: str = "default"
    skills: list[str] = field(default_factory=list)
    instructions: str = ""

    # --- tool scoping (the isolation primitive) -------------------------
    def effective_tools(self) -> list[str]:
        """Resolve the final allow-list: (all | tools) minus disallowed."""
        src = default_registry()
        if self.tools:
            allowed = [t for t in self.tools if t in src._tools]
        else:
            allowed = list(src.names())
        return [t for t in allowed if t not in self.disallowed_tools]

    def registry(self) -> ToolRegistry:
        """A fresh registry containing ONLY the scoped tools."""
        src = default_registry()
        reg = ToolRegistry()
        for n in self.effective_tools():
            t = src._tools[n]
            reg.register(t.name, t.description, t.parameters, t.fn)
        return reg

    # --- isolated agent construction ------------------------------------
    def build_agent(self, cfg: dict | None = None,
                    client=None) -> Agent:
        """Build an isolated Agent: own Session + scoped tools."""
        session = Session(cfg=cfg)
        return Agent(role=self.name, cfg=cfg, client=client,
                     registry=self.registry(), session=session)

    def run(self, goal: str, cfg: dict | None = None,
            client=None) -> str:
        """Run this sub-agent on a goal; returns only its final summary
        (the sub-agent's raw messages stay inside its own Session)."""
        agent = self.build_agent(cfg, client)
        res = agent.run(goal)
        return res.final_text


# ---------------------------------------------------------------------------
# Frontmatter parsing (stdlib only)
# ---------------------------------------------------------------------------

def _coerce(value: str):
    v = value.strip()
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.lower() in ("none", "null", ""):
        return None
    if v.lstrip("-").isdigit():
        return int(v)
    # list-like: comma or whitespace separated
    if "," in v:
        return [x.strip() for x in v.split(",") if x.strip()]
    return v


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a ``--- ... ---`` block from the body. Returns (fields, body).

    Supports both inline lists (``tools: a, b``) and YAML-style block lists
    (``tools:\\n  - a\\n  - b``) so .agent declarations match the design doc's
    frontmatter schema.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    fields: dict = {}
    body_lines: list[str] = []
    in_fm = True
    list_key: str | None = None
    for line in lines[1:]:
        stripped = line.strip()
        if in_fm and stripped == "---":
            in_fm = False
            list_key = None
            continue
        if in_fm:
            if list_key is not None and stripped.startswith("- "):
                item = stripped[2:].strip()
                if item:
                    fields[list_key].append(item)
                continue
            if ":" not in line:
                list_key = None
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                # possibly a block list; collect following "- " lines
                fields[key] = []
                list_key = key
            else:
                fields[key] = _coerce(val)
                list_key = None
        else:
            body_lines.append(line)
    # drop placeholder lists that had no items
    fields = {k: v for k, v in fields.items()
              if not (isinstance(v, list) and len(v) == 0)}
    return fields, "\n".join(body_lines).strip()


def load_subagent(path) -> SubagentDef:
    """Load a sub-agent definition from a ``.agent`` or ``.json`` file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"sub-agent file not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        data = json.loads(text)
        body = data.pop("instructions", "") or ""
        return SubagentDef(instructions=body, **{
            k: v for k, v in data.items()
            if k in SubagentDef.__dataclass_fields__})
    fields, body = _parse_frontmatter(text)
    # Normalize declaration-schema aliases. The .agent frontmatter follows the
    # design doc's camelCase schema (tools/disallowedTools/model/
    # permissionMode); map those to the snake_case dataclass fields so a
    # deny-list is never silently dropped (which would leak tools into the
    # scoped registry - a real isolation break).
    ALIASES = {"disallowedTools": "disallowed_tools",
               "permissionMode": "permission_mode"}
    norm: dict = {}
    for k, v in fields.items():
        norm[ALIASES.get(k, k)] = v
    # these keys are always lists in the declaration schema
    for list_key in ("tools", "disallowed_tools", "skills"):
        val = norm.get(list_key)
        if isinstance(val, str):
            val = [v for v in val.split(",") if v.strip()]
        norm[list_key] = val
    return SubagentDef(
        name=norm.get("name", p.stem),
        description=norm.get("description", "") or "",
        tools=norm.get("tools") or None,
        disallowed_tools=norm.get("disallowed_tools") or [],
        model=norm.get("model", "inherit"),
        permission_mode=norm.get("permission_mode", "default"),
        skills=norm.get("skills") or [],
        instructions=body or (norm.get("instructions", "") or ""),
    )


def build_scoped_registry(tools: list[str] | None,
                          disallowed: list[str] | None = None) -> ToolRegistry:
    """Convenience: build a registry from an explicit allow/deny list."""
    d = SubagentDef(name="adhoc", tools=tools,
                    disallowed_tools=disallowed or [])
    return d.registry()
