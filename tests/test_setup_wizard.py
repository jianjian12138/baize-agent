"""Unit tests for Interactive Setup Wizard (Hermes/Codex onboarding flow)."""
import pytest
from pathlib import Path
from unittest.mock import patch

from baize.setup_wizard import PROVIDERS, update_env_file, run_setup_wizard, _test_connection
from baize.cli import main


def test_providers_presets():
    assert len(PROVIDERS) >= 6
    names = [p.name for p in PROVIDERS]
    assert any("DeepSeek" in n for n in names)
    assert any("OpenAI" in n for n in names)
    assert any("Anthropic" in n for n in names)
    assert any("Ollama" in n for n in names)


def test_update_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# Initial comment\nBAIZE_MODEL_NAME=old_model\n", encoding="utf-8")

    updates = {
        "BAIZE_MODEL_BASE_URL": "https://api.deepseek.com",
        "BAIZE_MODEL_API_KEY": "sk-test123456",
        "BAIZE_MODEL_NAME": "deepseek-chat",
    }
    update_env_file(updates, env_path=env_file)

    content = env_file.read_text(encoding="utf-8")
    assert "# Initial comment" in content
    assert 'BAIZE_MODEL_BASE_URL="https://api.deepseek.com"' in content
    assert 'BAIZE_MODEL_API_KEY="sk-test123456"' in content
    assert 'BAIZE_MODEL_NAME="deepseek-chat"' in content


def test_run_setup_wizard_non_interactive(tmp_path):
    env_file = tmp_path / ".env"
    with patch("baize.setup_wizard.ENV_FILE", env_file):
        ok = run_setup_wizard(
            non_interactive=True,
            preset_idx=0,
            api_key="sk-deepseek-key",
            model="deepseek-chat",
        )
        assert ok is True
        assert env_file.exists()
        content = env_file.read_text(encoding="utf-8")
        assert "sk-deepseek-key" in content


def test_cli_setup_command(monkeypatch):
    monkeypatch.setattr("baize.setup_wizard.run_setup_wizard", lambda **kw: True)
    rc = main(["setup"])
    assert rc == 0
