"""V20 tool SDK — author custom tools and register them with the runtime.

This is the documented extension point for third-party tools. Plugins import
``tool`` and decorate plain functions; the decorated function is registered into
the shared tool registry that the agent loop consumes.

Example
-------
    from baize.tool_sdk import tool

    @tool(name="weather", description="Get current weather for a city",
          args={"city": "string"})
    def weather(city: str) -> str:
        return f"It is sunny in {city}."
"""
from __future__ import annotations

import inspect
from typing import Callable

from .tools import default_registry


def tool(name: str | None = None, description: str = "", args: dict | None = None):
    """Decorator that registers ``fn`` as a baize tool.

    ``args`` maps parameter name -> JSON type string (default "string").
    """

    def deco(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        sig = inspect.signature(fn)
        params = args or {p: "string" for p in sig.parameters}
        schema = {
            "type": "object",
            "properties": {
                k: {"type": v if isinstance(v, str) and v.startswith("string") else "string"}
                for k, v in params.items()
            },
            "required": list(params),
        }

        def _impl(**arguments: str) -> str:
            # The registry's execute() calls every tool as fn(**arguments), so we
            # re-spread the kwargs into the user's function (which may name its
            # params whatever it likes). Failures become observations, never crashes.
            try:
                return str(fn(**arguments))
            except Exception as exc:  # noqa: BLE001 - surface as observation
                return f"tool error: {exc}"

        default_registry().register(
            tool_name, description or (fn.__doc__ or ""), schema, _impl)
        return fn

    return deco
