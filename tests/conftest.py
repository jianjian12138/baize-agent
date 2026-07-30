"""Shared pytest fixtures.

The isolated-runtime `env` fixture used to be copy-pasted into three test
modules. Besides the duplication, having several module-level fixtures with
the same name made pytest's finalizer bookkeeping trip over itself when the
coverage plugin altered collection order. One definition, one behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baize.config import load_config  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A fully isolated baize runtime rooted at tmp_path.

    Every path-like setting points inside tmp_path, so tests can never touch
    the developer's real persistence dir, and a scripted (fake) model endpoint
    is configured so `LLMClient.configured` is True without any network.
    """
    persistence = tmp_path / "persistence"
    assets = tmp_path / "assets"
    (assets / "skills").mkdir(parents=True)
    persistence.mkdir()
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(persistence))
    monkeypatch.setenv("BAIZE_ASSETS_DIR", str(assets))
    monkeypatch.setenv("BAIZE_INDEX_FILE", str(persistence / "skill_index.json"))
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(persistence / "sessions"))
    monkeypatch.setenv("SKILL_LIBRARY_PATHS", "")
    monkeypatch.setenv("BAIZE_MODEL_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("BAIZE_MODEL_NAME", "scripted")
    return load_config()
