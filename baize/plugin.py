"""V20 plugin / extension system.

Provides lifecycle hooks so third parties can extend baize without touching the
core. Plugins are discovered from the built-in ``baize/plugins/`` package and any
directory set via ``BAIZE_PLUGINS_DIR``. Defensive isolation: a failing plugin is
logged and skipped — never allowed to crash the host runtime.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .config import load_config
from .logging_setup import get_logger
from .observability import obs

log = get_logger("plugin")

__all__ = ["Plugin", "PluginRegistry", "registry"]


class Plugin:
    """Base class for baize plugins. Override the hooks you need."""

    name = "unnamed"
    hooks: list[str] = []

    def on_load(self) -> None: ...
    def on_agent_start(self, goal: str) -> None: ...
    def on_tool_call(self, tool: str, args: dict) -> None: ...
    def on_error(self, exc: Exception) -> None: ...
    def on_unload(self) -> None: ...


class PluginRegistry:
    def __init__(self) -> None:
        self.plugins: list[Plugin] = []

    @staticmethod
    def _roots() -> list[Path]:
        cfg = load_config()
        roots = [Path(__file__).resolve().parent / "plugins"]
        extra = cfg.get("BAIZE_PLUGINS_DIR", "")
        if extra:
            roots.append(Path(extra))
        return roots

    def discover(self) -> int:
        cfg = load_config()
        if str(cfg.get("BAIZE_PLUGINS_ENABLED", "1")).lower() in ("0", "false"):
            return 0
        found = 0
        for root in self._roots():
            if not root.exists():
                continue
            for path in sorted(root.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                try:
                    mod = self._import(path)
                    for attr in vars(mod).values():
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, Plugin)
                            and attr is not Plugin
                        ):
                            inst = attr()
                            inst.on_load()
                            self.plugins.append(inst)
                            found += 1
                except Exception as e:  # defensive isolation
                    obs.record_error("plugin_load_errors")
                    log.warning("[plugin] failed to load %s: %s", path.name, e)
        # V22 #99: also discover components (auto-discovered, log + skip). Never
        # trusted by default - a failing/bad component is isolated, not crashed.
        try:
            from .component import get_kernel
            self._discover_components(get_kernel())
        except Exception as e:  # isolation: component discovery must not break host
            obs.record_error("plugin_component_discovery_errors")
            log.warning("[plugin] component discovery failed: %s", e)
        if found:
            obs.inc("plugins_loaded", found)
        return found

    def _discover_components(self, kernel) -> None:
        """Auto-discover component classes from the same plugin roots.

        A plugin component is any class with a ``KIND`` attribute and a
        ``build(cfg)`` callable. Auto-discovered components are registered with
        ``explicit=False`` so the kernel isolates them (log + skip on failure)
        rather than trusting them the way ``BAIZE_COMPONENTS`` overrides are.
        """
        from .component import Component, Kind
        for root in self._roots():
            if not root.exists():
                continue
            for path in sorted(root.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                try:
                    mod = self._import(path)
                except Exception as e:  # defensive isolation
                    obs.record_error("plugin_component_load_errors")
                    log.warning("[plugin] failed to import %s: %s", path.name, e)
                    continue
                for attr in vars(mod).values():
                    if (isinstance(attr, type) and attr is not Component
                            and hasattr(attr, "KIND")
                            and hasattr(attr, "build")):
                        try:
                            kind_val = getattr(attr, "KIND")
                            kind = kind_val if isinstance(kind_val, Kind) \
                                else Kind(kind_val)
                            build = getattr(attr, "build")
                            comp = Component(
                                kind, f"{path.stem}:{attr.__name__}",
                                lambda cfg, b=build: b(cfg),
                                provides=[kind.value], explicit=False)
                            kernel.add_component(comp)
                            obs.inc("plugin_components_loaded")
                        except Exception as e:  # isolation
                            obs.record_error("plugin_component_errors")
                            log.warning("[plugin] failed to register component %s: %s",
                                        attr.__name__, e)

    @staticmethod
    def _import(path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot import {path}")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = "baize.plugins"
        sys.modules[path.stem] = mod
        spec.loader.exec_module(mod)
        return mod

    def fire(self, hook: str, *args) -> None:
        for p in self.plugins:
            try:
                getattr(p, hook)(*args)
            except Exception as e:
                obs.record_error("plugin_hook_errors")
                log.warning("[plugin] %s.%s failed: %s", p.name, hook, e)


# Global default registry. Call registry.discover() once at startup.
registry = PluginRegistry()
