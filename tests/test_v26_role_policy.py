"""V26-B1: RolePolicy enforcement tests (written before implementation).

All tests MUST fail until team.py and orchestrator.py are updated.
Coverage maps to openspec/specs/baize-agent/v26-role-policy.md §7.
"""
import pytest


# ---------------------------------------------------------------------------
# B1-1: allow_tools filters agent registry
# ---------------------------------------------------------------------------

def test_allow_tools_filters_registry(tmp_path, monkeypatch):
    """When a Role has allow_tools=['read_file'], spawned agent must only have that tool."""
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    from baize.team import Role, TeamConfig
    from baize.orchestrator import Orchestrator
    from baize.llm import LLMClient

    role = Role(name="executor", allow_tools=["read_file"])
    config = TeamConfig(roles=[role])

    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_AGENT_MAX_STEPS": "2",
                "BAIZE_MODEL_BASE_URL": "",
                "BAIZE_MODEL_NAME": ""}
    from baize.tools import default_registry
    from baize.hooks import HookRegistry
    orch.registry = default_registry()
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch._ledger = None
    orch.team_config = config

    agent = orch._spawn("executor")

    # The spawned agent's registry must be restricted to allow_tools only
    names = set(agent.registry.names())
    assert "read_file" in names, f"read_file not in registry: {names}"
    # Tools NOT in allow_tools must be absent
    all_names = set(default_registry().names())
    excluded = all_names - {"read_file"}
    for tool in excluded:
        assert tool not in names, f"tool '{tool}' should have been filtered out"


# ---------------------------------------------------------------------------
# B1-2: empty allow_tools = no restriction
# ---------------------------------------------------------------------------

def test_empty_allow_tools_no_restriction(tmp_path, monkeypatch):
    """allow_tools=[] means no restriction (all tools available)."""
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    from baize.team import Role, TeamConfig
    from baize.orchestrator import Orchestrator
    from baize.tools import default_registry
    from baize.hooks import HookRegistry

    role = Role(name="executor", allow_tools=[])
    config = TeamConfig(roles=[role])

    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_AGENT_MAX_STEPS": "2",
                "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    orch.registry = default_registry()
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch._ledger = None
    orch.team_config = config

    agent = orch._spawn("executor")
    # Should have the same tools as the full registry
    assert set(agent.registry.names()) == set(default_registry().names())


# ---------------------------------------------------------------------------
# B1-3: unknown role name → no restriction (fail-open but documented)
# ---------------------------------------------------------------------------

def test_unknown_role_no_restriction(tmp_path, monkeypatch):
    """If no Role matches the name, spawn proceeds without tool restriction."""
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    from baize.team import Role, TeamConfig
    from baize.orchestrator import Orchestrator
    from baize.tools import default_registry
    from baize.hooks import HookRegistry

    role = Role(name="director", allow_tools=["read_file"])  # executor NOT defined
    config = TeamConfig(roles=[role])

    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_AGENT_MAX_STEPS": "2",
                "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    orch.registry = default_registry()
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch._ledger = None
    orch.team_config = config

    # Should not raise, should return agent with full registry
    agent = orch._spawn("executor")
    assert set(agent.registry.names()) == set(default_registry().names())


# ---------------------------------------------------------------------------
# B1-4: workspace_scope injected into agent extra_system / spawn
# ---------------------------------------------------------------------------

def test_workspace_scope_injected(tmp_path, monkeypatch):
    """workspace_scope must be visible to the spawned agent (extra_system)."""
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    from baize.team import Role, TeamConfig
    from baize.orchestrator import Orchestrator
    from baize.tools import default_registry
    from baize.hooks import HookRegistry

    role = Role(name="executor", allow_tools=[], workspace_scope="src/")
    config = TeamConfig(roles=[role])

    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_AGENT_MAX_STEPS": "2",
                "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    orch.registry = default_registry()
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch._ledger = None
    orch.team_config = config

    agent = orch._spawn("executor")
    # workspace_scope must be accessible on the spawned agent
    assert hasattr(agent, "_workspace_scope")
    assert agent._workspace_scope == "src/"


# ---------------------------------------------------------------------------
# B1-5: memory_visibility=none → _no_memory set on agent
# ---------------------------------------------------------------------------

def test_memory_visibility_none_skips_recall(tmp_path, monkeypatch):
    """memory_visibility='none' must set _no_memory=True on spawned agent."""
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    from baize.team import Role, TeamConfig
    from baize.orchestrator import Orchestrator
    from baize.tools import default_registry
    from baize.hooks import HookRegistry

    role = Role(name="verifier", allow_tools=[], memory_visibility="none")
    config = TeamConfig(roles=[role])

    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_AGENT_MAX_STEPS": "2",
                "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    orch.registry = default_registry()
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch._ledger = None
    orch.team_config = config

    agent = orch._spawn("verifier")
    assert getattr(agent, "_no_memory", False) is True


# ---------------------------------------------------------------------------
# B1-6: invalid memory_visibility → treated as "none" (fail-closed)
# ---------------------------------------------------------------------------

def test_invalid_memory_visibility_fallback(tmp_path, monkeypatch):
    """An invalid memory_visibility value must be treated as 'none' (fail-closed)."""
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    from baize.team import Role, TeamConfig
    from baize.orchestrator import Orchestrator
    from baize.tools import default_registry
    from baize.hooks import HookRegistry

    role = Role(name="executor", allow_tools=[], memory_visibility="full_access")  # invalid
    config = TeamConfig(roles=[role])

    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_AGENT_MAX_STEPS": "2",
                "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    orch.registry = default_registry()
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch._ledger = None
    orch.team_config = config

    # Should not raise - invalid value treated as none
    agent = orch._spawn("executor")
    # Invalid → fail-closed = no memory
    assert getattr(agent, "_no_memory", False) is True


# ---------------------------------------------------------------------------
# B1-7: allow_tools takes priority over tools (V25 compat field)
# ---------------------------------------------------------------------------

def test_allow_tools_takes_priority_over_tools(tmp_path, monkeypatch):
    """When both allow_tools and tools are set, allow_tools wins."""
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    from baize.team import Role, TeamConfig
    from baize.orchestrator import Orchestrator
    from baize.tools import default_registry
    from baize.hooks import HookRegistry

    role = Role(name="executor",
                tools=["bash", "read_file"],         # V25 compat field
                allow_tools=["write_file"])            # V26 field — must win
    config = TeamConfig(roles=[role])

    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_AGENT_MAX_STEPS": "2",
                "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    orch.registry = default_registry()
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch._ledger = None
    orch.team_config = config

    agent = orch._spawn("executor")
    names = set(agent.registry.names())
    assert "write_file" in names
    # bash and read_file should be excluded since allow_tools took priority
    assert "bash" not in names
    assert "read_file" not in names


# ---------------------------------------------------------------------------
# B1-8: Role.from_dict reads new V26 fields
# ---------------------------------------------------------------------------

def test_role_from_dict_new_fields():
    """Role.from_dict must correctly parse allow_tools, workspace_scope, memory_visibility."""
    from baize.team import Role

    d = {
        "name": "executor",
        "allow_tools": ["bash", "read_file"],
        "workspace_scope": "src/backend/",
        "memory_visibility": "none",
    }
    role = Role.from_dict(d)
    assert role.allow_tools == ["bash", "read_file"]
    assert role.workspace_scope == "src/backend/"
    assert role.memory_visibility == "none"


def test_role_from_dict_defaults_for_new_fields():
    """Role.from_dict must supply sensible defaults for missing V26 fields."""
    from baize.team import Role

    role = Role.from_dict({"name": "director"})
    assert role.allow_tools == []
    assert role.workspace_scope == ""
    assert role.memory_visibility == "read"


# ---------------------------------------------------------------------------
# B1-9: no team_config (original path) → no restriction
# ---------------------------------------------------------------------------

def test_no_team_config_no_restriction(tmp_path, monkeypatch):
    """When orchestrator has no team_config, _spawn must use full registry."""
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    from baize.orchestrator import Orchestrator
    from baize.tools import default_registry
    from baize.hooks import HookRegistry

    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_AGENT_MAX_STEPS": "2",
                "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    orch.registry = default_registry()
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch._ledger = None
    # No team_config set

    agent = orch._spawn("executor")
    assert set(agent.registry.names()) == set(default_registry().names())
