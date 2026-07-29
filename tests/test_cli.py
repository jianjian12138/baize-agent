"""Integration tests for the baize CLI — real subprocess-style calls via main()."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.cli import main  # noqa: E402


def _make_env(tmp_path: Path, monkeypatch) -> None:
    """Set env vars so config.load_config picks up tmp_path-based paths.

    config.py reads ROOT/.env (ROOT = baize package parent), which is fixed
    and not affected by chdir. So we use environment variables, which take
    priority over .env values in load_config().
    """
    persistence = tmp_path / "persistence"
    projects = tmp_path / "projects"
    assets = tmp_path / "assets"
    for d in (persistence, projects, assets):
        d.mkdir(parents=True, exist_ok=True)
    (assets / "skills").mkdir(exist_ok=True)
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(persistence))
    monkeypatch.setenv("BAIZE_PROJECTS_DIR", str(projects))
    monkeypatch.setenv("BAIZE_ASSETS_DIR", str(assets))
    monkeypatch.setenv("BAIZE_INDEX_FILE", str(persistence / "skill_index.json"))
    monkeypatch.setenv("SKILL_LIBRARY_PATHS", "")


def test_cli_version(capsys):
    try:
        main(["--version"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "baize" in out


def test_cli_doctor_passes(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_env(tmp_path, monkeypatch)
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASSED" in out


def test_cli_index_build_and_search(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_env(tmp_path, monkeypatch)
    # create a skill
    skill_dir = tmp_path / "assets" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: a test skill\n---\n# demo\n",
        encoding="utf-8",
    )
    rc = main(["index", "build"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "indexed" in out

    rc = main(["index", "search", "demo"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "demo-skill" in out


def test_cli_manifest_validate(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_env(tmp_path, monkeypatch)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "project": "test", "version": "1.0",
        "phases": [{"id": "P1", "name": "init", "status": "pending"}],
    }), encoding="utf-8")
    rc = main(["manifest", "validate", str(manifest)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "VALID" in out


def test_cli_memory_log_recall_stats(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_env(tmp_path, monkeypatch)
    rc = main(["memory", "log", "test event from cli", "--tags", "unit,integration"])
    assert rc == 0
    capsys.readouterr()

    rc = main(["memory", "remember", "important cli note"])
    assert rc == 0
    capsys.readouterr()

    rc = main(["memory", "recall", "cli"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cli note" in out or "test event" in out

    rc = main(["memory", "recall", "nonexistent-xyz"])
    assert rc == 1

    rc = main(["memory", "stats"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "events" in out


# ---------------------------------------------------------------------------
# V19: run / team / sessions subcommands
# ---------------------------------------------------------------------------

def _make_agent_env(tmp_path: Path, monkeypatch) -> None:
    """Extend _make_env with workspace/sessions/model settings for agent runs."""
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_SESSIONS_DIR",
                       str(tmp_path / "persistence" / "sessions"))
    monkeypatch.setenv("BAIZE_MODEL_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("BAIZE_MODEL_NAME", "scripted")


def _patch_scripted_client(monkeypatch, replies):
    """Replace baize.cli.LLMClient with a factory returning a scripted client.

    The real LLMClient request-building/parsing logic still runs; only the
    HTTP transport is scripted, so the CLI -> agent -> loop path is genuine.
    """
    from baize.config import load_config
    from baize.llm import LLMClient

    queue = list(replies)

    def transport(url, headers, payload):
        return {"choices": [{"message": queue.pop(0)}]}

    def factory(*args, **kwargs):
        return LLMClient(cfg=load_config(), transport=transport)

    monkeypatch.setattr("baize.cli.LLMClient", factory)


def test_cli_run_not_configured(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setenv("BAIZE_MODEL_BASE_URL", "")
    monkeypatch.setenv("BAIZE_MODEL_NAME", "")
    rc = main(["run", "do something"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "not configured" in out


def test_cli_team_not_configured(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setenv("BAIZE_MODEL_BASE_URL", "")
    monkeypatch.setenv("BAIZE_MODEL_NAME", "")
    rc = main(["team", "do something"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "not configured" in out


def test_cli_run_scripted_final(tmp_path, capsys, monkeypatch):
    _make_agent_env(tmp_path, monkeypatch)
    _patch_scripted_client(monkeypatch, [{"content": "goal achieved"}])
    rc = main(["run", "trivial goal"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "goal achieved" in out
    assert "session:" in out
    assert "final" in out


def test_cli_team_scripted_success(tmp_path, capsys, monkeypatch):
    _make_agent_env(tmp_path, monkeypatch)
    plan_json = json.dumps({"plan": [
        {"id": 1, "task": "create file A", "verify": "file A exists"}]})
    _patch_scripted_client(monkeypatch, [
        {"content": plan_json},                                    # director
        {"content": "created A"},                                  # executor
        {"content": json.dumps({"verdict": "pass",
                                "evidence": "A on disk"})},        # verifier
    ])
    rc = main(["team", "make A"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SUCCESS" in out
    assert "[PASS]" in out


def test_cli_sessions_list_and_show(tmp_path, capsys, monkeypatch):
    _make_agent_env(tmp_path, monkeypatch)

    # empty -> friendly message
    rc = main(["sessions"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no sessions yet" in out

    # create a session via a scripted run
    _patch_scripted_client(monkeypatch, [{"content": "hello from agent"}])
    rc = main(["run", "say hello"])
    out = capsys.readouterr().out
    assert rc == 0
    session_id = next(line.split("session: ", 1)[1]
                      for line in out.splitlines()
                      if line.startswith("session: "))

    # list shows the new session
    rc = main(["sessions"])
    out = capsys.readouterr().out
    assert rc == 0
    assert session_id in out

    # transcript shows roles and final text
    rc = main(["sessions", session_id])
    out = capsys.readouterr().out
    assert rc == 0
    assert "assistant" in out
    assert "hello from agent" in out

    # unknown id -> rc 1
    rc = main(["sessions", "no-such-session"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "not found" in out
