"""Tests for V21 P0-4: secret management + audit (5-surface redaction + Vault stub)."""
from __future__ import annotations

import json

import pytest

from baize import secrets
from baize.logging_setup import redact
from baize import memory as memory_mod
from baize import rag
from baize.agent import Session
from baize.tools import default_registry, _tool_bash, _tool_git


SECRET_TEXT = "deploy key api_key=sk-ABCDEFGHIJ1234567890 token=abcdefghijklmnop"


# -- Vault interface layer ------------------------------------------------

def test_env_backend_returns_value(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "v1")
    assert secrets.get_secret("MY_SECRET") == "v1"


def test_vault_backend_is_honest_stub(monkeypatch):
    monkeypatch.setenv("BAIZE_VAULT_URL", "https://vault.example")
    # Vault is not implemented -> returns default and records an error,
    # never fakes a fetch.
    assert secrets.get_secret("ANY", default="fallback") == "fallback"


# -- redact primitive ------------------------------------------------------

def test_redact_masks_credential_patterns():
    out = redact(SECRET_TEXT)
    assert "sk-ABCDEFGHIJ1234567890" not in out
    assert "abcdefghijklmnop" not in out
    assert "***REDACTED***" in out


# -- sink 1: memory --------------------------------------------------------

def test_memory_log_redacts(monkeypatch, tmp_path):
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    f = memory_mod.log_event(SECRET_TEXT, tags=["x"])
    raw = f.read_text(encoding="utf-8")
    assert "sk-ABCDEFGHIJ1234567890" not in raw
    assert "***REDACTED***" in raw


# -- sink 2: session JSONL -------------------------------------------------

def test_session_append_redacts_content(monkeypatch, tmp_path):
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    s = Session(cfg={"BAIZE_SESSIONS_DIR": str(tmp_path),
                     "BAIZE_PERSISTENCE_DIR": str(tmp_path)})
    s.append({"role": "user", "content": SECRET_TEXT})
    line = s.file.read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert "sk-ABCDEFGHIJ1234567890" not in rec["message"]["content"]
    assert "***REDACTED***" in rec["message"]["content"]


# -- sink 3: bash output ---------------------------------------------------

def test_bash_output_redacted(monkeypatch, tmp_path):
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    out = _tool_bash(f"echo \"{SECRET_TEXT}\"")
    assert "sk-ABCDEFGHIJ1234567890" not in out


def test_git_output_redacted(monkeypatch, tmp_path):
    # Stage a file whose diff would contain the secret, then git diff.
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    (tmp_path / "f.txt").write_text(SECRET_TEXT, encoding="utf-8")
    # git may be absent; only assert redaction when git ran.
    res = _tool_git("add f.txt")
    if res.startswith("exit=0"):
        diff = _tool_git("diff --cached")
        assert "sk-ABCDEFGHIJ1234567890" not in diff


# -- sink 4: RAG corpus ----------------------------------------------------

def test_rag_corpus_redacts_memory(monkeypatch, tmp_path):
    (tmp_path / "skills").mkdir()
    cfg = {
        "BAIZE_PERSISTENCE_DIR": str(tmp_path),
        "BAIZE_INDEX_FILE": str(tmp_path / "skill_index.json"),
        "BAIZE_ASSETS_DIR": str(tmp_path),
        "SKILL_LIBRARY_PATHS": "",
    }
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_INDEX_FILE", str(tmp_path / "skill_index.json"))
    # Force recall to return a secret-bearing memory record.
    secret_record = {"source": "logs/2026.jsonl", "text": SECRET_TEXT}
    monkeypatch.setattr(rag.memory_mod, "recall",
                        lambda *a, **k: [secret_record])
    index = rag.build_corpus(cfg=cfg)
    for meta in index._meta.values():
        assert "sk-ABCDEFGHIJ1234567890" not in meta.get("text", "")
