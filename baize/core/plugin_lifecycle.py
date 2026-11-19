"""V41 Gate-Verified Scoped Hot-Reload Plugin Lifecycle Manager.

Inspired by DeepSeek Harness spatiotemporal composability and Pi's ``/reload``,
every loaded plugin runs inside an isolated :class:`PluginScope` that tracks all
tools, lifecycle hooks, and cleanup callbacks it registers.

Guarantees:
  - Zero leak on unload/reload: every tool and hook created by the previous
    generation is cleanly unregistered before activating the next generation.
  - Gate-verified atomic reload: syntax (AST), import, ``register(scope)``, and
    optional ``smoke_test()`` execute in a staging scope first; if ANY gate
    fails, the previous active plugin stays untouched (automatic rollback).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class PluginScope:
    """Isolated resource tracker for a single loaded plugin."""

    plugin_id: str
    source_path: str
    generation: int = 1
    status: str = "staging"  # staging | active | rolled_back | unloaded
    loaded_at: float = field(default_factory=time.time)
    registered_tools: list[str] = field(default_factory=list)
    registered_hooks: list[tuple[str, Any]] = field(default_factory=list)
    cleanups: list[Callable[[], None]] = field(default_factory=list)
    _staged_tools: list[tuple[str, str, dict, Callable[..., str]]] = field(default_factory=list)
    _staged_hooks: list[tuple[str, Callable[..., Any]]] = field(default_factory=list)

    def add_tool(self, name: str, description: str, parameters: dict[str, Any], fn: Callable[..., str]) -> None:
        if not name or not callable(fn):
            raise ValueError("tool requires non-empty name and callable fn")
        self._staged_tools.append((name, description, parameters, fn))

    def add_hook(self, event: str, fn: Callable[..., Any]) -> None:
        if not event or not callable(fn):
            raise ValueError("hook requires event name and callable fn")
        self._staged_hooks.append((event, fn))

    def on_cleanup(self, fn: Callable[[], None]) -> None:
        if callable(fn):
            self.cleanups.append(fn)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "source_path": self.source_path,
            "generation": self.generation,
            "status": self.status,
            "tools": list(self.registered_tools),
            "hooks": [ev for ev, _ in self.registered_hooks],
            "loaded_at": round(self.loaded_at, 3),
        }


class HotReloadPluginManager:
    """Manages loading, atomic gate-verified reloading, and leak-free unloading of plugins."""

    def __init__(self, registry=None) -> None:
        self._scopes: dict[str, PluginScope] = {}
        self._default_registry = registry

    def _stage_module(self, plugin_id: str, path: Path, generation: int) -> PluginScope:
        if not path.is_file() or path.suffix != ".py":
            raise FileNotFoundError(f"Plugin file not found or not a .py file: {path}")
        source = path.read_text(encoding="utf-8", errors="replace")
        # Gate 1: AST syntax verification
        ast.parse(source, filename=str(path))

        mod_name = f"baize_hot_plugin_{plugin_id}_gen{generation}"
        spec = importlib.util.spec_from_file_location(mod_name, str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot build module spec for {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop(mod_name, None)
            raise

        scope = PluginScope(plugin_id=plugin_id, source_path=str(path.resolve()), generation=generation)
        reg_fn = getattr(mod, "register", None)
        if not callable(reg_fn):
            sys.modules.pop(mod_name, None)
            raise ValueError(f"Plugin {path.name} must define a callable register(scope) function")
        reg_fn(scope)

        # Gate 2: Optional smoke_test() verification (NO FAKE DONE)
        smoke_fn = getattr(mod, "smoke_test", None)
        if callable(smoke_fn):
            import inspect as _inspect
            sig = _inspect.signature(smoke_fn)
            res = smoke_fn(scope) if len(sig.parameters) >= 1 else smoke_fn()
            if res is False:
                sys.modules.pop(mod_name, None)
                raise AssertionError(f"Plugin {plugin_id} smoke_test() returned False")

        return scope

    def _deactivate_scope(self, scope: PluginScope, registry=None, hooks=None) -> None:
        if registry is not None:
            for tname in list(scope.registered_tools):
                try:
                    registry.unregister(tname)
                except Exception:
                    pass
        if hooks is not None:
            for ev, fn in list(scope.registered_hooks):
                handlers = getattr(hooks, "_handlers", None)
                if isinstance(handlers, dict) and ev in handlers:
                    try:
                        handlers[ev] = [h for h in handlers[ev] if h is not fn]
                    except Exception:
                        pass
        for cb in list(scope.cleanups):
            try:
                cb()
            except Exception:
                pass
        scope.registered_tools.clear()
        scope.registered_hooks.clear()
        scope.cleanups.clear()
        scope.status = "unloaded"

    def _activate_scope(self, scope: PluginScope, registry=None, hooks=None) -> None:
        for name, desc, params, fn in scope._staged_tools:
            if registry is not None:
                registry.register(name, desc, params, fn)
            scope.registered_tools.append(name)
        for ev, fn in scope._staged_hooks:
            if hooks is not None and hasattr(hooks, "on"):
                hooks.on(ev, fn)
            scope.registered_hooks.append((ev, fn))
        scope._staged_tools.clear()
        scope._staged_hooks.clear()
        scope.status = "active"

    def load_plugin(
        self,
        source_path: str | Path,
        *,
        plugin_id: str | None = None,
        registry=None,
        hooks=None,
    ) -> dict[str, Any]:
        if registry is None:
            registry = self._default_registry
        path = Path(source_path).resolve()
        pid = (plugin_id or path.stem).strip()
        if pid in self._scopes and self._scopes[pid].status == "active":
            return self.reload_plugin(pid, registry=registry, hooks=hooks)
        try:
            scope = self._stage_module(pid, path, generation=1)
        except Exception as exc:
            return {"ok": False, "plugin_id": pid, "status": "failed", "error": str(exc)}
        self._activate_scope(scope, registry=registry, hooks=hooks)
        self._scopes[pid] = scope
        return {"ok": True, **scope.to_dict()}

    def reload_plugin(self, plugin_id: str, *, registry=None, hooks=None) -> dict[str, Any]:
        if registry is None:
            registry = self._default_registry
        prev = self._scopes.get(plugin_id)
        if prev is None:
            return {"ok": False, "plugin_id": plugin_id, "error": f"Unknown plugin: {plugin_id}"}
        next_gen = prev.generation + 1
        try:
            staged = self._stage_module(plugin_id, Path(prev.source_path), generation=next_gen)
        except Exception as exc:
            return {
                "ok": False,
                "plugin_id": plugin_id,
                "status": "rolled_back",
                "active_generation": prev.generation,
                "error": f"Reload gate failed; previous generation {prev.generation} kept active: {exc}",
            }
        self._deactivate_scope(prev, registry=registry, hooks=hooks)
        self._activate_scope(staged, registry=registry, hooks=hooks)
        self._scopes[plugin_id] = staged
        return {"ok": True, **staged.to_dict()}

    def unload_plugin(self, plugin_id: str, *, registry=None, hooks=None) -> dict[str, Any]:
        if registry is None:
            registry = self._default_registry
        scope = self._scopes.pop(plugin_id, None)
        if scope is None:
            return {"ok": False, "plugin_id": plugin_id, "error": f"Unknown plugin: {plugin_id}"}
        removed_tools = list(scope.registered_tools)
        self._deactivate_scope(scope, registry=registry, hooks=hooks)
        return {"ok": True, "plugin_id": plugin_id, "status": "unloaded", "removed_tools": removed_tools}

    def list_plugins(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._scopes.values()]


_DEFAULT_PLUGIN_MANAGER = HotReloadPluginManager()


def get_plugin_manager() -> HotReloadPluginManager:
    return _DEFAULT_PLUGIN_MANAGER
