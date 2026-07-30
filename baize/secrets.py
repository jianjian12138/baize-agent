"""V20 secret backend abstraction.

Defaults to environment variables. A Vault endpoint can be configured via
BAIZE_VAULT_URL — the integration point is reserved (not yet implemented); when
unset or unconfigured it transparently falls back to env vars so callers can
rely on a single stable API.
"""
from __future__ import annotations

import os

from .config import load_config
from .observability import obs


def get_secret(name: str, default: str | None = None) -> str | None:
    """Return a secret by name (env first, then config), else ``default``."""
    cfg = load_config()
    val = os.environ.get(name) or cfg.get(name)
    if val:
        return val
    if cfg.get("BAIZE_VAULT_URL"):
        # reserved integration point for a real Vault/secret-manager backend
        obs.record_error("vault_not_implemented")
    return default
