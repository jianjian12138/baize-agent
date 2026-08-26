"""Built-in metrics plugin: feeds observability counters from lifecycle hooks.

Demonstrates the V20 extension point. Drop additional *.py files in this package
(or BAIZE_PLUGINS_DIR) subclassing baize.plugin.Plugin to extend the runtime.
"""
from __future__ import annotations

from baize.observability import obs
from baize.plugin import Plugin


class MetricsPlugin(Plugin):
    name = "metrics"

    def on_agent_start(self, goal: str) -> None:
        obs.inc("agent_runs")

    def on_tool_call(self, tool: str, args: dict) -> None:
        obs.inc("tool_calls")

    def on_error(self, exc: Exception) -> None:
        obs.inc("agent_errors")
