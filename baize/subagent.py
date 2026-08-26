"""V21 P1-3 Sub-agent definition format + isolation.

Defines a declarative sub-agent format (Claude Code-style frontmatter, but
expressed with stdlib-only primitives - no PyYAML dependency). A sub-agent is
an *isolated* ``Agent`` instance: its own ``Session`` (its context never
leaks into the parent run) and a *scoped* tool registry (only the tools named
in ``tools`` minus ``disallowed_tools`` are reachable - it physically cannot
call a tool it was not granted).

Declarative formats supported (zero third-party deps):
  * ``.agent`` markdown: a leading ``---\\n<key>: <value>\\n---`` block, body =
    free-text instructions. Values that look like lists (comma/space separated)
    become lists; booleans/ints are coerced.
  * ``.json``: a plain JSON object with the same keys.

Fields:
  name, description, tools (allow-list; empty/None = all tools),
  disallowed_tools, model, permission_mode, skills, instructions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .agent import Agent, Session
from .tools import ToolRegistry, default_registry

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
