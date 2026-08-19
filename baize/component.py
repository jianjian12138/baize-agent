"""V22 unified component contract + composition kernel (Cordis-inspired, hardened).

Pure stdlib, zero third-party dependencies. This module is the honest localisation
of deepseek-harness's "everything is a plugin" idea: every core unit of baize
(model / tool / skill / session / sandbox / loop / scheduler / ui / storage) is
described by a uniform ``Component`` contract and assembled by a
``CompositionKernel`` from configuration.

Unlike Cordis, baize keeps its fail-closed posture (this is the deliberate
non-copy from the V22 review):
  * **Explicit overrides** (a user-specified component via ``BAIZE_COMPONENTS``)
    that fail to build or fail type validation BLOCK startup (``ComponentError``,
    exit non-zero) - never silently fall back to a built-in.
  * **Auto-discovered** third-party components (loaded by ``plugin.py``) are
    isolated: a build/type failure is logged and the component is *skipped* -
    never trusted by default. For the security-critical kinds (sandbox / tool
    / session - the execution + persistence edge) an auto-discovered component
    is rejected *even on the success path*: it can never silently replace the
    trusted built-in default. Only an explicit ``BAIZE_COMPONENTS`` override may
    replace a security-critical kind. This is the deliberate, honest correction
    to deepseek-harness's "third-party plugins trusted by default" weakness
    (#2) which the V22 review flagged and we refused to copy.

This module must NEVER import concrete core types at top level (that would
create circular imports with ``agent.py`` / ``serve.py`` / ``llm.py``). Each
default component's ``build`` lazily imports exactly what it needs, and
``Component.build`` is typed ``Any`` so callers resolve instances without the
kernel knowing their concrete classes.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

from .config import load_config
from .logging_setup import get_logger
from .observability import obs

log = get_logger("component")


class ComponentError(Exception):
    """Raised when component assembly fails (fail-closed)."""


# ---------------------------------------------------------------------------
# Closed set of component kinds. New kinds require a code change on purpose:
# an open kind registry would let a third party invent a kind baize never
# validates (a Cordis-style mistake we explicitly avoid).
# ---------------------------------------------------------------------------


class Kind(str, Enum):
    MODEL = "model"
    TOOL = "tool"
    SKILL = "skill"
    SESSION = "session"
    SANDBOX = "sandbox"
    LOOP = "loop"
    SCHEDULER = "scheduler"
    UI = "ui"
    STORAGE = "storage"


# ---------------------------------------------------------------------------
# Trust boundary: the security-critical kinds (the execution + persistence
# edge). A third-party component auto-discovered from a plugin root is NEVER
# allowed to silently replace one of these - even if it builds and passes the
# structural Protocol check - because a behaviorally-malicious but
# structurally-valid component would otherwise be trusted on the *success*
# path. Only an explicit ``BAIZE_COMPONENTS`` override may replace a
# security-critical kind. (F1 - closes deepseek-harness weakness #2.)
# ---------------------------------------------------------------------------

SECURITY_CRITICAL_KINDS = frozenset(
    {Kind.SANDBOX, Kind.TOOL, Kind.SESSION})


# ---------------------------------------------------------------------------
# Per-kind Protocol contracts (V22 review fix #2).
# runtime_checkable => structural type validation at assembly, so a component
# with the wrong shape is rejected instead of silently misbehaving.
# ---------------------------------------------------------------------------


@runtime_checkable
class ModelAdapterProto(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...
    @property
    def configured(self) -> bool: ...


@runtime_checkable
class ToolProviderProto(Protocol):
    def schemas(self) -> list[dict]: ...
    def execute(self, name: str, arguments: dict) -> str: ...


@runtime_checkable
class SkillProviderProto(Protocol):
    def search(self, keyword: str) -> list[dict]: ...
    def build_index(self, cfg: dict | None = None) -> None: ...


@runtime_checkable
class SessionStoreProto(Protocol):
    def append(self, message: dict, kind: str = "message") -> None: ...
    @classmethod
    def list_sessions(cls, cfg: dict | None = None) -> list[dict]: ...


@runtime_checkable
class SandboxProto(Protocol):
    def run(self, command: str, cwd: str | None = None, timeout: int = 60,
            cfg: dict | None = None) -> Any: ...


@runtime_checkable
class LoopStrategyProto(Protocol):
    def run(self, agent: Any, goal: str, extra_system: str = "") -> Any: ...


@runtime_checkable
class SchedulerProto(Protocol):
    def tick(self) -> list[str]: ...
    def next_due(self) -> float | None: ...
    def start(self) -> None: ...


@runtime_checkable
class UIProto(Protocol):
    def event(self, kind: str, detail: str = "") -> None: ...


@runtime_checkable
class StorageProto(Protocol):
    def read_records(self, session_id: str) -> list[dict]: ...
    def list_sessions(self, cfg: dict | None = None) -> list[dict]: ...
    def fork_session(self, parent: str, at_index: int | None = None) -> str: ...
    def compress_session(self, session_id: str) -> dict: ...
    def list_lineage(self) -> dict: ...


_KIND_PROTOCOLS: dict[Kind, type] = {
    Kind.MODEL: ModelAdapterProto,
    Kind.TOOL: ToolProviderProto,
    Kind.SKILL: SkillProviderProto,
    Kind.SESSION: SessionStoreProto,
    Kind.SANDBOX: SandboxProto,
    Kind.LOOP: LoopStrategyProto,
    Kind.SCHEDULER: SchedulerProto,
    Kind.UI: UIProto,
    Kind.STORAGE: StorageProto,
}


# ---------------------------------------------------------------------------
# Default component adapters (method-shaped wrappers for module-level helpers).
# These keep the per-kind Protocols method-based even when the underlying unit
# is a module function (sandbox.run) or a module (sessions persistence).
# ---------------------------------------------------------------------------


class _SandboxAdapter:
    """Adapter exposing ``sandbox.run`` as a Protocol-satisfying method."""

    def run(self, command: str, cwd: str | None = None, timeout: int = 60,
            cfg: dict | None = None) -> Any:
        from . import sandbox  # lazy: avoid import cost / cycles
        return sandbox.run(command, cwd=cwd, timeout=timeout, cfg=cfg)


class _StorageAdapter:
    """Adapter over the ``sessions`` persistence module (transcript store)."""

    def __init__(self) -> None:
        from . import sessions as _s
        self._s = _s

    def read_records(self, session_id: str) -> list[dict]:
        return self._s._read_records(session_id)

    def list_sessions(self, cfg: dict | None = None) -> list[dict]:
        return self._s.Session.list_sessions(cfg)

    def fork_session(self, parent: str, at_index: int | None = None) -> str:
        return self._s.fork_session(parent, at_index)

    def compress_session(self, session_id: str) -> dict:
        return self._s.compress_session(session_id)

    def list_lineage(self) -> dict:
        return self._s.list_lineage()


# ---------------------------------------------------------------------------
# Component contract
# ---------------------------------------------------------------------------


@dataclass
class Component:
    """Uniform description of a replaceable core unit.

    ``build`` returns ``Any`` (lazy) on purpose - it may close over concrete
    core types without this module importing them, preventing circular imports.
    ``requires`` / ``provides`` drive topological assembly (fail-closed).
    ``explicit`` distinguishes user overrides (fail-closed) from auto-discovered
    components (log + skip).
    """

    kind: Kind
    name: str
    build: Callable[[dict], Any]
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    explicit: bool = False


# ---------------------------------------------------------------------------
# Default component builders (each lazily imports its concrete unit)
# ---------------------------------------------------------------------------


def _build_model(cfg: dict) -> Any:
    from .llm import LLMClient
    return LLMClient(cfg)


def _build_tool(cfg: dict) -> Any:
    from .tools import default_registry
    return default_registry()


def _build_skill(cfg: dict) -> Any:
    from . import skill_index
    return skill_index


def _build_session(cfg: dict) -> Any:
    from .agent import Session
    return Session


def _build_sandbox(cfg: dict) -> Any:
    return _SandboxAdapter()


def _build_loop(cfg: dict) -> Any:
    from .agent import DefaultLoop
    return DefaultLoop()


def _build_scheduler(cfg: dict) -> Any:
    from .automations import AutomationScheduler
    return AutomationScheduler(cfg)


def _build_ui(cfg: dict) -> Any:
    from .ui import ProgressUI
    return ProgressUI()


def _build_storage(cfg: dict) -> Any:
    return _StorageAdapter()


_DEFAULT_COMPONENTS: list[Component] = [
    Component(Kind.MODEL, "default-llm", _build_model, provides=["model"]),
    Component(Kind.TOOL, "default-tools", _build_tool, provides=["tool"]),
    Component(Kind.SKILL, "default-skills", _build_skill, provides=["skill"]),
    Component(Kind.SESSION, "default-session", _build_session,
              provides=["session"]),
    Component(Kind.SANDBOX, "default-sandbox", _build_sandbox,
              provides=["sandbox"]),
    Component(Kind.LOOP, "default-loop", _build_loop, provides=["loop"]),
    Component(Kind.SCHEDULER, "default-scheduler", _build_scheduler,
              provides=["scheduler"]),
    Component(Kind.UI, "default-ui", _build_ui, provides=["ui"]),
    Component(Kind.STORAGE, "default-storage", _build_storage,
              provides=["storage"]),
]

# Tokens without a ":" are kept-only references; they must name a known kind.
_BUILTIN_REF_NAMES = {k.value for k in Kind}


# ---------------------------------------------------------------------------
# Runtime: the assembled, addressable set of resolved component instances.
# ---------------------------------------------------------------------------


@dataclass
class Runtime:
    components: dict[Kind, Any] = field(default_factory=dict)
    # kind -> component name, for introspection / diagnostics.
    source: dict[Kind, str] = field(default_factory=dict)

    def get(self, kind: Kind) -> Any:
        return self.components.get(kind)

    def __getitem__(self, kind: Kind) -> Any:
        return self.components[kind]

    def names(self) -> dict[str, str]:
        return {k.value: v for k, v in self.source.items()}


# ---------------------------------------------------------------------------
# Composition kernel
# ---------------------------------------------------------------------------


def _split_components(raw: str) -> list[str]:
    return [t.strip() for t in str(raw or "").split(",") if t.strip()]


class CompositionKernel:
    """Assembles the runtime from built-in defaults + user overrides.

    Two isolation semantics are enforced strictly:
      * explicit override (``BAIZE_COMPONENTS``) - build/type failure => raise
        ``ComponentError`` (startup blocked, fail-closed).
      * auto-discovered component (added via ``add_component`` from plugin
        discovery) - build/type failure => log + skip (defensive isolation).
    """

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or load_config()
        self.components: dict[Kind, Component] = {}
        for c in _DEFAULT_COMPONENTS:
            self.components[c.kind] = c
        # Snapshot of the built-in defaults so an auto-discovered component that
        # is skipped (build/type/dependency failure) can fall back to the
        # built-in rather than leaving a gap (never trust auto by default).
        self._defaults: dict[Kind, Component] = {
            c.kind: c for c in _DEFAULT_COMPONENTS}

    # -- discovery hooks ----------------------------------------------------

    def add_component(self, comp: Component) -> None:
        """Register an auto-discovered component (explicit=False by contract).

        Used by ``plugin.py`` discovery. Defensive isolation: a build/type
        failure is logged and the component is *skipped* - never trusted by
        default. Additionally, for SECURITY_CRITICAL_KINDS (sandbox / tool /
        session - the execution + persistence edge) an auto-discovered
        component is rejected *even on the success path*: it can never silently
        replace the trusted built-in default. Only an explicit
        ``BAIZE_COMPONENTS`` override may replace a security-critical kind.
        """
        comp.explicit = False
        if comp.kind in SECURITY_CRITICAL_KINDS:
            # Trust boundary (F1): a third party must not take over command
            # execution (sandbox/tool) or persisted memory (session) by default.
            obs.record_error("component_security_rejected")
            log.warning(
                "[component] REJECTED auto-discovered %r for security-critical "
                "kind %s: keeping trusted built-in default (set BAIZE_COMPONENTS "
                "to override explicitly)", comp.name, comp.kind.value)
            return
        self.components[comp.kind] = comp

    def _restore_default(self, kind: Kind) -> None:
        """Restore the built-in default for ``kind`` if one exists.

        Used during dependency resolution (before the main build loop), so the
        restored default is still picked up by ``assemble``.
        """
        if kind in self._defaults:
            self.components[kind] = self._defaults[kind]

    def _add_default_to_runtime(self, kind: Kind, runtime: "Runtime") -> None:
        """Build the built-in default for ``kind`` and add it to the runtime.

        Used when an auto-discovered component fails *during* the main build
        loop (the iteration has already passed that kind), so the default must
        be added to the runtime directly rather than re-queued.
        """
        default = self._defaults.get(kind)
        if default is None:
            return
        try:
            inst = default.build(self.cfg)
        except Exception:
            return
        if isinstance(inst, _KIND_PROTOCOLS[kind]):
            runtime.components[kind] = inst
            runtime.source[kind] = default.name

    # -- overrides ----------------------------------------------------------

    def _load_override(self, token: str) -> Component | None:
        """Return an explicit override Component, or ``None`` for a keep-ref.

        Raises ``ComponentError`` for any malformed / unresolvable token -
        explicit user input is fail-closed.
        """
        token = token.strip()
        if ":" not in token:
            if token not in _BUILTIN_REF_NAMES:
                raise ComponentError(
                    f"unknown builtin component reference: {token!r} "
                    f"(allowed: {sorted(_BUILTIN_REF_NAMES)})")
            return None  # keep the built-in default for that kind
        module_path, _, class_name = token.partition(":")
        if not module_path or not class_name:
            raise ComponentError(f"malformed component token: {token!r}")
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
        except Exception as e:  # import / attribute error
            raise ComponentError(
                f"cannot load component {token!r}: {e}") from e
        kind_val = getattr(cls, "KIND", None)
        if kind_val is None:
            raise ComponentError(
                f"component {token!r} is missing a KIND attribute")
        kind = kind_val if isinstance(kind_val, Kind) else Kind(kind_val)
        build = getattr(cls, "build", None)
        if build is None:
            raise ComponentError(f"component {token!r} is missing build()")
        return Component(kind, token, lambda cfg: build(cfg),
                         provides=[kind.value], explicit=True)

    def apply_overrides(self) -> None:
        raw = self.cfg.get("BAIZE_COMPONENTS", "")
        for token in _split_components(raw):
            comp = self._load_override(token)
            if comp is None:
                continue  # keep default
            self.components[comp.kind] = comp  # explicit override (fail-closed)

    # -- dependency resolution (topological, fail-closed) -------------------

    def _resolve_dependencies(self) -> None:
        def providers() -> dict[str, list[Component]]:
            p: dict[str, list[Component]] = {}
            for c in self.components.values():
                for cap in c.provides:
                    p.setdefault(cap, []).append(c)
            return p

        # Pass 1: drop auto-discovered components with unmet requirements
        # (defensive isolation); explicit ones fail-closed.
        changed = True
        while changed:
            changed = False
            prov = providers()
            for name, comp in list(self.components.items()):
                missing = [r for r in comp.requires if r not in prov]
                if not missing:
                    continue
                if comp.explicit:
                    raise ComponentError(
                        f"component {comp.name} requires {missing} but nothing "
                        f"provides it")
                obs.record_error("component_dep_missing")
                log.warning("[component] %s requires %s (unmet); skipping "
                            "(auto-discovered)", comp.name, missing)
                del self.components[name]
                self._restore_default(comp.kind)
                changed = True

        # Pass 2: cycle detection. A cycle touching any explicit component
        # fails closed; an auto-only cycle is broken by skipping one auto node.
        prov = providers()
        graph: dict[str, list[str]] = {c.name: [] for c in self.components.values()}
        for comp in self.components.values():
            for req in comp.requires:
                for pc in prov.get(req, []):
                    if pc.name != comp.name:
                        graph[comp.name].append(pc.name)
        comps_by_name = {c.name: c for c in self.components.values()}
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in graph}

        def visit(node: str, stack: list[str]) -> None:
            color[node] = GRAY
            for nxt in graph[node]:
                if color.get(nxt, WHITE) == GRAY:
                    cyc = stack + [node, nxt]
                    if any(comps_by_name[n].explicit for n in cyc if n in comps_by_name):
                        raise ComponentError(
                            "circular component dependency: " + " -> ".join(cyc))
                    for n in cyc:  # break an auto-only cycle
                        if n in comps_by_name and not comps_by_name[n].explicit:
                            log.warning("[component] breaking auto cycle at %s; "
                                        "skipping (auto-discovered)", n)
                            del self.components[n]
                            self._restore_default(comps_by_name[n].kind)
                            return
                if color.get(nxt, WHITE) == WHITE:
                    visit(nxt, stack + [node])
            color[node] = BLACK

        for n in graph:
            if color[n] == WHITE:
                visit(n, [])

    # -- assembly -----------------------------------------------------------

    def assemble(self) -> Runtime:
        self.apply_overrides()
        self._resolve_dependencies()
        runtime = Runtime()
        for kind, comp in self.components.items():
            proto = _KIND_PROTOCOLS[kind]
            try:
                inst = comp.build(self.cfg)
            except Exception as e:  # build failure
                if comp.explicit:
                    raise ComponentError(
                        f"explicit component {comp.name} ({kind.value}) failed "
                        f"to build: {e}") from e
                obs.record_error("component_build_errors")
                log.warning("[component] %s (%s) failed to build: %s; skipping "
                            "(auto-discovered)", comp.name, kind.value, e)
                self._add_default_to_runtime(kind, runtime)
                continue
            if not isinstance(inst, proto):
                if comp.explicit:
                    raise ComponentError(
                        f"explicit component {comp.name} ({kind.value}) does "
                        f"not satisfy {proto.__name__}")
                obs.record_error("component_type_errors")
                log.warning("[component] %s (%s) rejected by type check (%s); "
                            "skipping (auto-discovered)",
                            comp.name, kind.value, proto.__name__)
                self._add_default_to_runtime(kind, runtime)
                continue
            runtime.components[kind] = inst
            runtime.source[kind] = comp.name
        # Fail-closed (F4): every kind must be present after assembly. If a
        # built-in default itself failed to build, _add_default_to_runtime
        # already tried to restore it; if that also failed we must NOT return a
        # runtime with a None hole (previously an implicit fail-open). Surface
        # it instead so the gate / caller sees an honest error.
        missing = [k.value for k in Kind if k not in runtime.components]
        if missing:
            raise ComponentError(
                f"runtime incomplete after assembly, missing: {missing}")
        return runtime


# ---------------------------------------------------------------------------
# Process-wide singleton + helper used by tools / serve.
# Assembled ONCE; serve and tools consult it instead of hardcoding units.
# ---------------------------------------------------------------------------


_runtime: Runtime | None = None
_kernel: "CompositionKernel | None" = None


def get_kernel() -> "CompositionKernel":
    """Return the process-wide kernel singleton.

    ``plugin.discover()`` populates this with auto-discovered components; the
    runtime assembled by :func:`get_runtime` then includes them (explicit
    ``BAIZE_COMPONENTS`` overrides are applied last, so they win).
    """
    global _kernel
    if _kernel is None:
        _kernel = CompositionKernel()
    return _kernel


def get_runtime() -> Runtime:
    """Return the assembled runtime singleton (built lazily, exactly once)."""
    global _runtime
    if _runtime is None:
        _runtime = get_kernel().assemble()
    return _runtime


def reset_runtime() -> None:
    """Drop the cached singleton (used by tests to re-assemble with new cfg)."""
    global _runtime, _kernel
    _runtime = None
    _kernel = None


def resolve_sandbox(command: str, cwd: str | None = None, timeout: int = 60,
                    cfg: dict | None = None, runtime: Runtime | None = None) -> Any:
    """Resolve the active sandbox via the kernel so a custom ``BAIZE_COMPONENTS``
    sandbox is honored without editing ``agent.py`` / ``tools.py`` call sites.

    Default path returns the same ``sandbox.run`` result as before (regression
    safe); an explicit override swaps it in.
    """
    rt = runtime or get_runtime()
    sb = rt.get(Kind.SANDBOX)
    if sb is not None and hasattr(sb, "run"):
        return sb.run(command, cwd=cwd, timeout=timeout, cfg=cfg)
    from . import sandbox
    return sandbox.run(command, cwd=cwd, timeout=timeout, cfg=cfg)
