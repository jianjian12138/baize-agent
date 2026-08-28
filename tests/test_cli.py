"""Integration tests for the baize CLI — real subprocess-style calls via main()."""
import json
import subprocess
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


def test_module_entrypoint_version():
    """The CI and Docker smoke checks use ``python -m baize`` directly."""
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "baize", "--version"], cwd=root,
        capture_output=True, text=True, check=False,
    )
    from baize import __version__
    assert f"baize {__version__}" in result.stdout


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


# ---------------------------------------------------------------------------
# Coverage expansion: index / memory / rag / team-memory / bench / serve /
# plugins edge paths + defensive "unknown action" branches (argparse-guarded,
# so they are exercised by calling the cmd_* handler directly).
# ---------------------------------------------------------------------------
from dataclasses import dataclass  # noqa: E402

from baize.cli import (cmd_index, cmd_memory, cmd_rag,  # noqa: E402
                       cmd_team_memory)
from baize.team_memory import TeamMemory  # noqa: E402


def test_cli_index_search_no_keyword(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    rc = main(["index", "search"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "usage" in out


def test_cli_index_search_no_hits(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    rc = main(["index", "search", "zzz-no-such-skill"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no skills matched" in out


def test_cli_index_unknown_action(capsys):
    class A:
        action = "frobnicate"
    rc = cmd_index(A())
    out = capsys.readouterr().out
    assert rc == 2
    assert "unknown index action" in out


def test_cli_memory_compress(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    rc = main(["memory", "compress", "--days", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "days" in out or "compressed" in out or "kept" in out


def test_cli_memory_unknown_action(capsys):
    class A:
        action = "bogus"
        text = ""
        tags = ""
        days = 0
    rc = cmd_memory(A())
    assert rc == 2


def test_cli_rag_search_no_query(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    rc = main(["rag", "search"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "usage" in out


def test_cli_rag_search_no_hits(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setattr("baize.rag.retrieve", lambda q, top_k=5: [])
    rc = main(["rag", "search", "anything"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no context matched" in out


def test_cli_rag_search_hits(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setattr("baize.rag.retrieve", lambda q, top_k=5: [
        {"score": 0.91, "meta": {"name": "skill-x", "kind": "skill"}}])
    rc = main(["rag", "search", "anything"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "skill-x" in out


def test_cli_rag_scores(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setattr("baize.rag.skill_scores", lambda: {"demo": 0.5})
    rc = main(["rag", "scores"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "demo" in out


def test_cli_rag_unknown_action(capsys):
    class A:
        action = "bogus"
        query = ""
        top_k = 5
    rc = cmd_rag(A())
    assert rc == 2


def test_cli_team_memory_show_empty(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    rc = main(["team-memory", "show"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "empty" in out


def test_cli_team_memory_lifecycle(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    tm = TeamMemory(team_id="cli-test")
    tm.post("executor", "found a bug", tags=["finding"])
    rc = main(["team-memory", "show", "cli-test"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "found a bug" in out

    rc = main(["team-memory", "stats", "cli-test"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "notes" in out

    rc = main(["team-memory", "clear", "cli-test"])
    out = capsys.readouterr().out
    assert rc == 0

    rc = main(["team-memory", "show", "cli-test"])
    out = capsys.readouterr().out
    assert rc == 1


def test_cli_team_memory_unavailable(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setenv("BAIZE_TEAM_MEMORY_BACKEND", "shared")
    rc = main(["team-memory", "show"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "unavailable" in out


def test_cli_team_memory_unknown_action(capsys):
    class A:
        action = "bogus"
        team_id = "default"
    rc = cmd_team_memory(A())
    assert rc == 2


def test_cli_bench(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    rc = main(["bench"])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "benchmarks passed" in out


def test_cli_serve(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    called = {}

    def fake_serve(host=None, port=None):
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr("baize.cli.serve_mod.serve", fake_serve)
    rc = main(["serve", "--host", "127.0.0.1", "--port", "9999"])
    assert rc == 0
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 9999


class _FakePlugin:
    def __init__(self, name):
        self.name = name


def test_cli_plugins_empty(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setattr("baize.cli.registry.plugins", [])
    monkeypatch.setattr("baize.cli.registry.discover", lambda: 0)
    rc = main(["plugins"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 plugins" in out


def test_cli_plugins_loaded(tmp_path, capsys, monkeypatch):
    _make_env(tmp_path, monkeypatch)
    monkeypatch.setattr("baize.cli.registry.plugins", [_FakePlugin("demo")])
    monkeypatch.setattr("baize.cli.registry.discover", lambda: 3)
    rc = main(["plugins"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "demo" in out


@dataclass
class _FakeSubtaskReport:
    task_id: int = 1
    task: str = "do X"
    verdict: str = "fail"
    issues: list = None
    retried: bool = True


@dataclass
class _FakeOrchResult:
    success: bool = False
    session_ids: list = None
    reports: list = None


def test_cli_team_with_issues(tmp_path, capsys, monkeypatch):
    _make_agent_env(tmp_path, monkeypatch)

    class FakeOrch:
        def __init__(self, *a, **k):
            pass

        def run(self, goal, **kwargs):  # accept resume_run_id and future args
            return _FakeOrchResult(
                success=False, session_ids=["s1"],
                reports=[_FakeSubtaskReport(issues=["issue-a", "issue-b"])])

    monkeypatch.setattr("baize.cli.Orchestrator", FakeOrch)
    rc = main(["team", "goal with failure"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "issue-a" in out
    assert "issue-b" in out
    assert "(retried)" in out
