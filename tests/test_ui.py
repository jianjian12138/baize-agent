"""Real tests for the V20 interaction layer: TUI, dashboard, team memory."""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize import __version__  # noqa: E402
from baize import dashboard  # noqa: E402
from baize.team_memory import TeamMemory  # noqa: E402
from baize.ui import Palette, ProgressUI, supports_color  # noqa: E402


def cfg_for(tmp_path: Path) -> dict:
    return {"BAIZE_PERSISTENCE_DIR": str(tmp_path / "persistence"),
            "BAIZE_TEAM_MEMORY_BACKEND": "local"}


# --- TUI ---------------------------------------------------------------------

def test_palette_monochrome_when_disabled():
    p = Palette(enabled=False)
    assert p.red == "" and p.reset == ""
    assert p.paint("red", "x") == "x"


def test_palette_emits_ansi_when_enabled():
    p = Palette(enabled=True)
    assert p.paint("green", "ok") == "\033[32mok\033[0m"


def test_supports_color_false_for_non_tty():
    assert supports_color(io.StringIO()) is False


def test_progress_ui_renders_events_without_color():
    buf = io.StringIO()
    ui = ProgressUI(stream=buf, color=False)
    ui.event("phase", "planning")
    ui.event("tool", "read_file(x.py)")
    ui.event("final", "done")
    out = buf.getvalue()
    assert "phase" in out and "planning" in out
    assert "read_file(x.py)" in out
    assert "\033[" not in out          # no ANSI leaked


def test_progress_ui_truncates_long_detail():
    buf = io.StringIO()
    ui = ProgressUI(stream=buf, color=False, max_detail=20)
    ui.event("tool", "x" * 500)
    line = buf.getvalue()
    assert len(line) < 100 and "…" in line


def test_progress_ui_quiet_mode_records_but_prints_nothing():
    buf = io.StringIO()
    ui = ProgressUI(stream=buf, color=False, verbose=False)
    ui.event("tool", "silent")
    assert buf.getvalue() == ""
    assert ui.counts["tool"] == 1      # still counted for the summary


def test_progress_ui_event_never_raises():
    ui = ProgressUI(stream=io.StringIO(), color=False)
    ui.event("tool", None)             # bad payload must not crash a run
    ui.event(None, "x")


def test_summary_reports_agent_result_shape():
    class R:
        stopped_reason = "final"
        steps = 4
        tool_calls = 3
    buf = io.StringIO()
    ui = ProgressUI(stream=buf, color=False)
    ui.event("tool", "a")
    text = ui.summary(R())
    assert "run finished" in text and "tool=1" in text
    assert "final" in text and "steps=4" in text


def test_summary_reports_team_verdict():
    class Failed:
        success = False

    class Passed:
        success = True
    ui = ProgressUI(stream=io.StringIO(), color=False)
    assert "FAILED" in ui.summary(Failed())
    assert "SUCCESS" in ui.summary(Passed())


def test_progress_bar_shape():
    ui = ProgressUI(stream=io.StringIO(), color=False)
    assert ui.bar(0, 4, width=8) == "[........] 0/4"
    assert ui.bar(2, 4, width=8) == "[####....] 2/4"
    assert ui.bar(9, 4, width=8) == "[########] 9/4"   # clamped, no crash


# --- dashboard ---------------------------------------------------------------

def test_dashboard_renders_self_contained_html():
    html = dashboard.render(__version__)
    assert html.startswith("<!DOCTYPE html>")
    assert f"V{__version__}" in html
    assert "__VER__" not in html            # placeholder fully substituted
    for external in ("http://", "https://", "cdn."):
        assert external not in html         # zero external assets
    for endpoint in ("/health", "/metrics", "/sessions", "/run"):
        assert endpoint in html


# --- team memory -------------------------------------------------------------

def test_team_memory_post_and_context(tmp_path):
    tm = TeamMemory("run-1", cfg=cfg_for(tmp_path))
    tm.post("executor", "auth uses JWT", tags=["finding"])
    tm.post("verifier", "test_login fails", tags=["blocker"])
    ctx = tm.context()
    assert "Shared team findings" in ctx
    assert "[executor] auth uses JWT" in ctx
    assert "[verifier] test_login fails" in ctx


def test_team_memory_filters_by_tag_and_role(tmp_path):
    tm = TeamMemory("run-2", cfg=cfg_for(tmp_path))
    tm.post("executor", "found A", tags=["finding"])
    tm.post("verifier", "blocked B", tags=["blocker"])
    assert len(tm.read(tags=["blocker"])) == 1
    assert tm.read(tags=["blocker"])[0]["text"] == "blocked B"
    assert len(tm.read(role="executor")) == 1


def test_team_memory_rejects_empty_post(tmp_path):
    tm = TeamMemory("run-3", cfg=cfg_for(tmp_path))
    try:
        tm.post("executor", "   ")
        assert False, "should have raised"
    except ValueError:
        pass


def test_team_memory_claim_prevents_duplicate_work(tmp_path):
    tm = TeamMemory("run-4", cfg=cfg_for(tmp_path))
    assert tm.claim("task-1", "executor") is True
    assert tm.claim("task-1", "verifier") is False    # already owned
    assert tm.claim("task-1", "executor") is True     # idempotent for owner
    assert tm.owner_of("task-1") == "executor"
    assert tm.owner_of("task-99") is None


def test_team_memory_survives_corrupt_lines(tmp_path):
    tm = TeamMemory("run-5", cfg=cfg_for(tmp_path))
    tm.post("executor", "good note")
    with tm.file.open("a", encoding="utf-8") as f:
        f.write("{ not json\n")
    assert len(tm.read()) == 1


def test_team_memory_stats_and_clear(tmp_path):
    tm = TeamMemory("run-6", cfg=cfg_for(tmp_path))
    tm.post("executor", "a")
    tm.post("verifier", "b")
    tm.claim("t1", "executor")
    s = tm.stats()
    assert s["notes"] == 2 and s["claims"] == 1
    assert s["roles"] == ["executor", "verifier"]
    tm.clear()
    assert tm.read() == [] and tm.context() == ""


def test_team_memory_sanitizes_team_id(tmp_path):
    tm = TeamMemory("../../evil id!", cfg=cfg_for(tmp_path))
    assert "/" not in tm.team_id and ".." not in tm.team_id
    tm.post("x", "y")
    assert tm.file.parent.name == "team_memory"


def test_shared_backend_fails_closed(tmp_path):
    cfg = cfg_for(tmp_path)
    cfg["BAIZE_TEAM_MEMORY_BACKEND"] = "shared"
    try:
        TeamMemory("run-7", cfg=cfg)
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "reserved" in str(exc)


def test_unknown_backend_rejected(tmp_path):
    cfg = cfg_for(tmp_path)
    cfg["BAIZE_TEAM_MEMORY_BACKEND"] = "bogus"
    try:
        TeamMemory("run-8", cfg=cfg)
        assert False, "should have raised"
    except ValueError:
        pass
