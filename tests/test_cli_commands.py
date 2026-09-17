"""In-process tests for CLI subcommands that had no coverage.

`tests/test_cli.py` already calls `main()` directly, so these commands were
simply never exercised. Writing the tests found a path-traversal bug in
`baize plugin remove`: the target was joined onto the plugin library and handed
to `shutil.rmtree` with no containment check, so `plugin remove ../../x`
deleted a directory outside the library - recursively and silently.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from baize.cli import build_parser, main  # noqa: E402


def _args(*argv):
    return build_parser().parse_args(list(argv))


def _run(capsys, *argv) -> tuple[int, str]:
    """Run the CLI in-process and return (exit code, stdout+stderr)."""
    code = 0
    try:
        code = main(list(argv))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    out = capsys.readouterr()
    return code, out.out + out.err


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Isolated paths so no test can touch the developer's real directories."""
    for name in ("persistence", "projects", "assets", "user_skills"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "assets" / "skills").mkdir(exist_ok=True)
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path / "persistence"))
    monkeypatch.setenv("BAIZE_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("BAIZE_ASSETS_DIR", str(tmp_path / "assets"))
    monkeypatch.setenv("BAIZE_USER_SKILLS_DIR", str(tmp_path / "user_skills"))
    monkeypatch.setenv("BAIZE_INDEX_FILE",
                       str(tmp_path / "persistence" / "skill_index.json"))
    monkeypatch.setenv("SKILL_LIBRARY_PATHS", "")
    return tmp_path


# ------------------------------------------------------------- status ------


def test_status_with_no_runs_says_so(cli_env, capsys):
    code, out = _run(capsys, "status")
    assert code == 1
    assert "no runs found" in out


def test_status_lists_runs_when_they_exist(cli_env, capsys):
    runs = Path(cli_env / "persistence" / "runs")
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "run-abc.jsonl").write_text(
        json.dumps({"type": "goal", "goal": "do a thing"}) + "\n",
        encoding="utf-8")

    code, out = _run(capsys, "status")
    assert code == 0
    assert "run-abc" in out
    assert "baize status <run-id>" in out


def test_status_for_an_unknown_run_id_is_1(cli_env, capsys):
    code, out = _run(capsys, "status", "no-such-run")
    assert code == 1
    assert "run not found" in out


def test_status_reports_a_real_ledger(cli_env, capsys):
    from baize.run_ledger import RunLedger

    ledger = RunLedger("run-xyz")
    ledger.append("plan_created", {"goal": "refactor the parser"})
    ledger.append("task_verified", {"ok": True}, task_id="t1")

    code, out = _run(capsys, "status", "run-xyz")
    assert code == 0
    assert "run-xyz" in out
    assert "refactor the parser" in out
    assert "t1" in out


# ------------------------------------------------------------ plugins ------


def test_plugin_list_is_zero_or_more_never_an_error(cli_env, capsys):
    code, out = _run(capsys, "plugin", "list")
    assert code == 0
    assert "plugin" in out


def test_plugin_install_without_a_url_is_usage_error(cli_env, capsys):
    code, out = _run(capsys, "plugin", "install")
    assert code == 2
    assert "usage" in out


def test_plugin_install_rejects_a_non_github_url(cli_env, capsys):
    code, out = _run(capsys, "plugin", "install", "https://example.com/x")
    assert code == 1
    assert "invalid GitHub URL" in out


def test_plugin_remove_without_a_name_is_usage_error(cli_env, capsys):
    code, out = _run(capsys, "plugin", "remove")
    assert code == 2
    assert "usage" in out


def test_plugin_remove_missing_plugin_is_1(cli_env, capsys):
    code, out = _run(capsys, "plugin", "remove", "not-installed")
    assert code == 1
    assert "not found" in out


def test_plugin_remove_deletes_a_real_plugin(cli_env, capsys):
    lib = Path(cli_env / "user_skills")
    victim = lib / "my-plugin"
    victim.mkdir()
    (victim / "SKILL.md").write_text("---\nname: my-plugin\n---\n", encoding="utf-8")

    code, out = _run(capsys, "plugin", "remove", "my-plugin")
    assert code == 0
    assert "Removed" in out
    assert not victim.exists()


def test_plugin_remove_cannot_escape_the_plugin_library(cli_env, capsys):
    """`plugin remove ../../outside` must not delete outside the library.

    Before the containment check this resolved to a directory next to the
    library and was passed to shutil.rmtree(ignore_errors=True) - a silent
    recursive delete of an arbitrary directory.
    """
    lib = Path(cli_env / "user_skills")
    outside = Path(cli_env / "outside")
    outside.mkdir()
    (outside / "important.txt").write_text("do not delete", encoding="utf-8")

    code, out = _run(capsys, "plugin", "remove", "../outside")
    assert code == 1
    assert "outside the plugin library" in out
    assert (outside / "important.txt").exists(), "the file was deleted"


def test_plugin_remove_refuses_the_library_root_itself(cli_env, capsys):
    lib = Path(cli_env / "user_skills")
    (lib / "keep.txt").write_text("x", encoding="utf-8")
    code, out = _run(capsys, "plugin", "remove", ".")
    assert code == 1
    assert lib.exists()
    assert (lib / "keep.txt").exists()


def test_plugin_unknown_action_is_rejected(cli_env, capsys):
    """argparse rejects it before dispatch, so the `unknown action` fallback in
    cmd_plugins is unreachable from the CLI. Assert the behaviour that exists."""
    code, out = _run(capsys, "plugin", "frobnicate")
    assert code == 2
    assert "invalid choice" in out


# --------------------------------------------------------------- skill -----


def test_skill_search_without_a_keyword_is_usage_error(cli_env, capsys):
    code, out = _run(capsys, "skill", "search")
    assert code == 2
    assert "usage" in out


def test_skill_create_without_a_name_is_usage_error(cli_env, capsys):
    code, out = _run(capsys, "skill", "create")
    assert code == 2
    assert "usage" in out


def test_skill_create_then_search_finds_it(cli_env, capsys):
    code, out = _run(capsys, "skill", "create", "my-new-skill",
                     "--description", "a distinctive description",
                     "--body", "# body")
    assert code == 0
    assert "skill created" in out

    code, out = _run(capsys, "skill", "search", "my-new-skill")
    assert code == 0
    assert "my-new-skill" in out


def test_skill_create_sanitises_the_name(cli_env, capsys):
    """`safe_name` must keep the write inside the user library."""
    lib = Path(cli_env / "user_skills")
    code, _out = _run(capsys, "skill", "create", "../../escape",
                      "--description", "d")
    assert code == 0
    assert not (Path(cli_env).parent / "escape").exists()
    written = list(lib.glob("*"))
    assert written, "nothing was written into the library"
    assert all(lib in p.parents for p in written)


def test_skill_audit_runs(cli_env, capsys):
    code, out = _run(capsys, "skill", "audit")
    assert code == 0
    assert "audit" in out or "审计" in out


def test_skill_unknown_action_is_rejected(cli_env, capsys):
    code, out = _run(capsys, "skill", "frobnicate")
    assert code == 2
    assert "invalid choice" in out


# ---------------------------------------------------------- speculative ----


def test_speculative_announces_its_fixture(cli_env, capsys):
    """The numbers are hardcoded; the command must say so (see the honesty
    gate, which checks the same phrases)."""
    code, out = _run(capsys, "speculative", "speed up the parser")
    assert code == 0
    assert "hardcoded demo fixture" in out
    assert "preset fixture" in out
