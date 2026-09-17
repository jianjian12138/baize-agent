"""F6 coverage expansion: the first-run setup wizard (``baize/setup_wizard.py``).

The wizard measured 32% - the lowest of any user-facing module. It is also the
module a brand-new user meets first, and the only one that writes ``.env``. A
wizard that silently mangles ``.env`` or hangs on bad input is the worst
possible first impression, so the input-handling paths are worth pinning.

Every test drives ``run_setup_wizard`` through a scripted ``builtins.input``,
which is how a real user drives it - including the paths a human cannot
reliably reproduce by hand: interrupt at each individual prompt, non-numeric
menu choices, out-of-range numbers.

Honesty notes
-------------
* ``ENV_FILE`` is redirected to ``tmp_path`` in every test, and the three
  ``BAIZE_MODEL_*`` variables are snapshotted before the wizard runs (it writes
  them into ``os.environ``). The suite never touches the repository's real
  ``.env`` nor leaves the process environment modified.
* The connectivity probe is stubbed at ``urllib.request.urlopen``, so the
  probe's own error classification (401 / 404 / 5xx / network) is exercised for
  real rather than asserted from a comment.
* ``update_env_file`` is the real function, not a stub: it is the code that
  rewrites the user's ``.env``, so it is the last thing worth faking.
"""
from __future__ import annotations

import builtins
import urllib.error

import pytest

import baize.setup_wizard as wizard

_MODEL_VARS = ("BAIZE_MODEL_BASE_URL", "BAIZE_MODEL_API_KEY", "BAIZE_MODEL_NAME")


class _Feed:
    """Scripted ``builtins.input``; exhaustion raises EOFError."""

    def __init__(self, items):
        self.items = list(items)
        self.prompts: list[str] = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        if not self.items:
            raise EOFError
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Keep the wizard away from the repository's real .env and environment."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(wizard, "ENV_FILE", env_file)
    for name in _MODEL_VARS:
        monkeypatch.setenv(name, "")
    return env_file


def _read_env(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"')
    return out


def _feed(monkeypatch, items):
    feed = _Feed(items)
    monkeypatch.setattr(builtins, "input", feed)
    return feed


# ---------------------------------------------------------------------------
# _test_connection
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_probe_accepts_a_200(monkeypatch):
    monkeypatch.setattr(wizard.urllib.request, "urlopen", lambda req, timeout=8: _Resp(200))
    ok, msg = wizard._test_connection("https://api.example.com", "sk", "m")
    assert ok is True
    assert "verified successfully" in msg


def test_probe_sends_the_bearer_token_to_the_models_endpoint(monkeypatch):
    seen = {}

    def capture(req, timeout=8):
        seen["headers"] = dict(req.headers)
        seen["url"] = req.full_url
        return _Resp(200)

    monkeypatch.setattr(wizard.urllib.request, "urlopen", capture)
    wizard._test_connection("https://api.example.com/", "sk-secret", "m")
    assert seen["url"] == "https://api.example.com/models"
    assert seen["headers"].get("Authorization") == "Bearer sk-secret"


def test_probe_rejects_a_401(monkeypatch):
    def unauthorized(req, timeout=8):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(wizard.urllib.request, "urlopen", unauthorized)
    ok, msg = wizard._test_connection("https://api.example.com", "bad", "m")
    assert ok is False
    assert "401" in msg and "Invalid API Key" in msg


@pytest.mark.parametrize("code", [404, 405])
def test_probe_treats_404_and_405_as_reachable(monkeypatch, code):
    """Many OpenAI-compatible proxies do not implement /models.

    Reporting that as unreachable would send users chasing a non-problem, so
    the probe says "host reached" and tells them to check the model name.
    """
    def missing(req, timeout=8):
        raise urllib.error.HTTPError("u", code, "Not Found", {}, None)

    monkeypatch.setattr(wizard.urllib.request, "urlopen", missing)
    ok, msg = wizard._test_connection("https://api.example.com", "sk", "my-model")
    assert ok is True
    assert f"HTTP {code}" in msg and "my-model" in msg


def test_probe_reports_other_http_errors(monkeypatch):
    def boom(req, timeout=8):
        raise urllib.error.HTTPError("u", 500, "Server Error", {}, None)

    monkeypatch.setattr(wizard.urllib.request, "urlopen", boom)
    ok, msg = wizard._test_connection("https://api.example.com", "sk", "m")
    assert ok is False
    assert "HTTP Error 500" in msg


def test_probe_reports_a_network_failure(monkeypatch):
    def boom(req, timeout=8):
        raise OSError("no route to host")

    monkeypatch.setattr(wizard.urllib.request, "urlopen", boom)
    ok, msg = wizard._test_connection("https://api.example.com", "sk", "m")
    assert ok is False
    assert "no route to host" in msg


# ---------------------------------------------------------------------------
# update_env_file
# ---------------------------------------------------------------------------

def test_update_env_file_creates_the_file_and_its_parents(tmp_path):
    target = tmp_path / "nested" / ".env"
    wizard.update_env_file({"A": "1"}, env_path=target)
    assert target.read_text(encoding="utf-8") == 'A="1"\n'


def test_update_env_file_rewrites_known_keys_and_appends_new_ones(tmp_path):
    target = tmp_path / ".env"
    target.write_text("# a comment\nA=old\nB=keep\n\n", encoding="utf-8")
    wizard.update_env_file({"A": "new", "C": "added"}, env_path=target)
    text = target.read_text(encoding="utf-8")
    assert "# a comment" in text, "comments must survive an update"
    assert 'A="new"' in text and "A=old" not in text
    assert "B=keep" in text, "unrelated keys must be preserved verbatim"
    assert 'C="added"' in text


def test_update_env_file_falls_back_to_the_module_env_file(isolated_env):
    wizard.update_env_file({"ONLY": "here"})
    assert _read_env(isolated_env) == {"ONLY": "here"}


# ---------------------------------------------------------------------------
# non-interactive mode
# ---------------------------------------------------------------------------

def test_non_interactive_writes_the_first_preset(isolated_env):
    assert wizard.run_setup_wizard(non_interactive=True, api_key="sk-abc") is True
    env = _read_env(isolated_env)
    assert env["BAIZE_MODEL_BASE_URL"] == wizard.PROVIDERS[0].base_url
    assert env["BAIZE_MODEL_NAME"] == wizard.PROVIDERS[0].default_model
    assert env["BAIZE_MODEL_API_KEY"] == "sk-abc"


def test_non_interactive_honours_explicit_overrides(isolated_env):
    assert wizard.run_setup_wizard(non_interactive=True, preset_idx=2,
                                   api_key="k", model="custom-model",
                                   base_url="https://custom") is True
    env = _read_env(isolated_env)
    assert env["BAIZE_MODEL_BASE_URL"] == "https://custom"
    assert env["BAIZE_MODEL_NAME"] == "custom-model"


# ---------------------------------------------------------------------------
# interactive mode
# ---------------------------------------------------------------------------

def test_interactive_defaults_to_deepseek(monkeypatch, isolated_env):
    feed = _feed(monkeypatch, ["", "", "sk-test", ""])
    monkeypatch.setattr(wizard, "_test_connection", lambda *a: (True, "ok"))
    assert wizard.run_setup_wizard() is True
    env = _read_env(isolated_env)
    assert env["BAIZE_MODEL_BASE_URL"] == "https://api.deepseek.com"
    assert env["BAIZE_MODEL_NAME"] == "deepseek-chat"
    assert env["BAIZE_MODEL_API_KEY"] == "sk-test"
    # A bare Enter on the menu must not need a second attempt.
    assert len(feed.prompts) == 4


def test_interactive_custom_provider_prefixes_https(monkeypatch, isolated_env):
    _feed(monkeypatch, ["7", "api.custom.cn", "sk-x", ""])
    monkeypatch.setattr(wizard, "_test_connection", lambda *a: (True, "ok"))
    assert wizard.run_setup_wizard() is True
    env = _read_env(isolated_env)
    assert env["BAIZE_MODEL_BASE_URL"] == "https://api.custom.cn"
    # The Custom preset has no default model, so the wizard must fall back
    # rather than write an empty model name into .env.
    assert env["BAIZE_MODEL_NAME"] == "deepseek-chat"


def test_interactive_rejects_bad_menu_input_then_accepts_a_valid_one(monkeypatch, isolated_env):
    feed = _feed(monkeypatch, ["abc", "99", "2", "", "sk", ""])
    monkeypatch.setattr(wizard, "_test_connection", lambda *a: (True, "ok"))
    assert wizard.run_setup_wizard() is True
    env = _read_env(isolated_env)
    assert env["BAIZE_MODEL_BASE_URL"] == wizard.PROVIDERS[1].base_url
    # Two rejected attempts plus the accepted one.
    assert len(feed.prompts) == 6


def test_interactive_ollama_needs_no_key(monkeypatch, isolated_env):
    _feed(monkeypatch, ["6", "", "", ""])
    monkeypatch.setattr(wizard, "_test_connection", lambda *a: (True, "ok"))
    assert wizard.run_setup_wizard() is True
    assert _read_env(isolated_env)["BAIZE_MODEL_API_KEY"] == "ollama-local"


def test_interactive_reports_a_failed_probe_but_still_saves(monkeypatch, isolated_env, capsys):
    _feed(monkeypatch, ["", "", "sk", ""])
    monkeypatch.setattr(wizard, "_test_connection", lambda *a: (False, "nope"))
    assert wizard.run_setup_wizard() is True
    out = capsys.readouterr().out
    assert "nope" in out and "仍将保存配置" in out
    assert isolated_env.exists()


def test_interactive_honours_a_custom_base_url_and_model(monkeypatch, isolated_env):
    _feed(monkeypatch, ["1", "https://my.gateway/v1", "sk", "my-model"])
    monkeypatch.setattr(wizard, "_test_connection", lambda *a: (True, "ok"))
    assert wizard.run_setup_wizard() is True
    env = _read_env(isolated_env)
    assert env["BAIZE_MODEL_BASE_URL"] == "https://my.gateway/v1"
    assert env["BAIZE_MODEL_NAME"] == "my-model"


def test_interactive_reprompts_when_the_api_key_is_blank(monkeypatch, isolated_env):
    feed = _feed(monkeypatch, ["", "", "", "sk-second", ""])
    monkeypatch.setattr(wizard, "_test_connection", lambda *a: (True, "ok"))
    assert wizard.run_setup_wizard() is True
    assert _read_env(isolated_env)["BAIZE_MODEL_API_KEY"] == "sk-second"
    assert len(feed.prompts) == 5


@pytest.mark.parametrize("feed", [
    [KeyboardInterrupt()],                 # at the provider menu
    ["1", KeyboardInterrupt()],            # at the base-url prompt
    ["7", KeyboardInterrupt()],            # at the custom base-url prompt
    ["1", "", KeyboardInterrupt()],        # at the API-key prompt
    ["1", "", "sk", KeyboardInterrupt()],  # at the model prompt
    ["6", "", KeyboardInterrupt()],        # at the keyless (Ollama) prompt
])
def test_interactive_interrupts_are_reported_not_crashed(monkeypatch, feed, capsys):
    _feed(monkeypatch, feed)
    assert wizard.run_setup_wizard() is False
    assert "取消" in capsys.readouterr().out


def test_interactive_eof_cancels_cleanly(monkeypatch, capsys):
    _feed(monkeypatch, [])
    assert wizard.run_setup_wizard() is False
    assert "已取消" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the preset table itself
# ---------------------------------------------------------------------------

def test_every_preset_declares_what_the_menu_needs():
    """The wizard offers these as one-keypress choices; a blank one is a trap."""
    for idx, preset in enumerate(wizard.PROVIDERS):
        assert preset.name, f"preset {idx} has no display name"
        assert preset.notes, f"preset {idx} has no explanation for the user"
        if idx != len(wizard.PROVIDERS) - 1:   # Custom is intentionally blank
            assert preset.base_url.startswith("http"), f"preset {idx} has a bad base_url"
            assert preset.default_model, f"preset {idx} has no default model"


def test_only_ollama_is_keyless():
    keyless = [p.name for p in wizard.PROVIDERS if not p.needs_key]
    assert len(keyless) == 1
    assert "Ollama" in keyless[0]
