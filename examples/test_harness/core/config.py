"""Configuration loader with ${ENV_VAR} expansion and path resolution."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def expand_env_vars(value: Any) -> Any:
    """Recursively expand ${VAR} and ${VAR:-default} in strings/dicts/lists."""
    if isinstance(value, str):
        def _repl(m: re.Match) -> str:
            var, default = m.group(1), m.group(2)
            val = os.environ.get(var)
            if val is not None and val != "":
                return val
            return default if default is not None else ""
        return _ENV_PATTERN.sub(_repl, value)
    if isinstance(value, list):
        return [expand_env_vars(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    return value


def load_harness_config(config_path: str | Path) -> tuple[dict[str, Any], Path]:
    p = Path(config_path).resolve()
    raw = json.loads(p.read_text(encoding="utf-8"))
    cfg = expand_env_vars(raw)
    if not isinstance(cfg, dict):
        raise ValueError(f"Harness config must be a JSON object: {p}")
    return cfg, p.parent
