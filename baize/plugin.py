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
from .observability import obs

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

    def discover(self) -> int:
        cfg = load_config()
        if str(cfg.get("BAIZE_PLUGINS_ENABLED", "1")).lower() in ("0", "false"):
            return 0
        roots = [Path(__file__).resolve().parent / "plugins"]
        extra = cfg.get("BAIZE_PLUGINS_DIR", "")
        if extra:
            roots.append(Path(extra))
        found = 0
        for root in roots:
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
                    print(f"[plugin] failed to load {path.name}: {e}")
        if found:
            obs.inc("plugins_loaded", found)
        return found

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
                print(f"[plugin] {p.name}.{hook} failed: {e}")


# Global default registry. Call registry.discover() once at startup.
registry = PluginRegistry()
