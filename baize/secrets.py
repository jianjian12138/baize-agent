"""V20 secret backend abstraction.

Provides a small, pluggable backend interface so callers use one stable API:
  - EnvBackend   : reads from environment variables then config (default, real)
  - VaultBackend : reserved integration point for BAIZE_VAULT_URL; currently a
                   stub that records an error and returns the default (honest:
                   it does NOT pretend to fetch from Vault).

When BAIZE_VAULT_URL is unset, get_secret transparently uses EnvBackend.
"""
from __future__ import annotations

import os

from .config import load_config
from .observability import obs


class SecretBackend:
    """Base class for secret backends."""
    def get(self, name: str, default: str | None = None) -> str | None:
        raise NotImplementedError


class EnvBackend(SecretBackend):
    """Reads secrets from environment variables, then config. Real, default."""
    def get(self, name: str, default: str | None = None) -> str | None:
        cfg = load_config()
        val = os.environ.get(name) or cfg.get(name)
        return val or default


class VaultBackend(SecretBackend):
    """Reserved: external Vault/secret-manager integration.

    Not yet implemented - calling get() honestly records an error and returns
    the default instead of faking a fetch. Implement the HTTP transport here
    when BAIZE_VAULT_URL is wired up for real.
    """
    def __init__(self, url: str) -> None:
        self.url = url

    def get(self, name: str, default: str | None = None) -> str | None:
        obs.record_error("vault_not_implemented")
        return default


def _backend(cfg: dict | None = None) -> SecretBackend:
    cfg = cfg or load_config()
    url = cfg.get("BAIZE_VAULT_URL")
    if url:
        return VaultBackend(url)
    return EnvBackend()


def get_secret(name: str, default: str | None = None) -> str | None:
    """Return a secret by name via the configured backend, else ``default``."""
    return _backend().get(name, default)
