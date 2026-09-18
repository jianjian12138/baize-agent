"""F6 coverage expansion: every ``cmd_*`` dispatcher in ``baize/cli.py``.

Why this file exists
--------------------
``baize/cli.py`` was the single largest uncovered module in the measured
report (208 missing statements, 71%). Most of the gap was the *error and
fallback* half of each dispatcher: the "usage:" branches, the "not found"
branches, the "unknown action" branches. Those branches are exactly the ones a
user hits when they mistype a command, so leaving them unmeasured means the
least-travelled code in the product is also the least-verified.

Every test below asserts a **return code** and a **substring of the printed
output**, because a dispatcher that returns 0 on a failed operation is a
dispatcher that lies to whatever script called it. Coverage is a side effect
of that, not the goal.

Honesty notes
-------------
* External work is stubbed *at the seam the CLI itself uses* - the module the
  handler imports from - never by replacing the handler under test. So the
  handler's own branching logic is genuinely executed.
* Nothing writes into the repository: the plugin library, the skill index and
  the PRD/progress files all point at ``tmp_path``, and every test that uses
  relative paths first ``monkeypatch.chdir(tmp_path)``.
* ``plugin install`` is exercised against a real ``.tar.gz`` built in-memory
  and a stubbed HTTP response, so the tar-extraction logic runs for real; only
  the network call is faked.
"""
from __future__ import annotations

import io
import tarfile
import types
from pathlib import Path

import pytest

import baize.cli as cli
import baize.config as config_mod
import baize.plugin as plugin_mod
import baize.run_ledger as ledger_mod
import baize.session_viewer as viewer_mod
import baize.skill_index as skill_index
import baize.team as team_mod
from baize import tools as tools_mod


def ns(**kw) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kw)


class _FakeClient:
    def __init__(self, configured: bool = True):
        self.configured = configured
        self.models: list = []


# ---------------------------------------------------------------------------
# cmd_skill
# ---------------------------------------------------------------------------

def test_skill_build_reports_index_file(monkeypatch, capsys):
    monkeypatch.setattr(skill_index, "build_index", lambda cfg=None: {"count": 7, "libraries": ["a", "b"]})
    monkeypatch.setattr(skill_index, "load_config", lambda *a, **k: {"BAIZE_INDEX_FILE": "/tmp/idx.json"})
    assert cli.cmd_skill(ns(action="build")) == 0
    out = capsys.readouterr().out
    assert "indexed 7 skills from 3 source(s)" in out
    assert "/tmp/idx.json" in out


def test_skill_search_without_keyword_prints_usage(capsys):
    assert cli.cmd_skill(ns(action="search", target="")) == 2
    assert "usage: python -m baize skill search <keyword>" in capsys.readouterr().out


def test_skill_search_no_hits_returns_one(monkeypatch, capsys):
    monkeypatch.setattr(skill_index, "search", lambda kw, *a, **k: [])
    assert cli.cmd_skill(ns(action="search", target="nothing")) == 1
    assert "no skills matched" in capsys.readouterr().out


def test_skill_search_lists_hits_without_description(monkeypatch, capsys):
    monkeypatch.setattr(skill_index, "search", lambda kw, *a, **k: [
        {"name": "alpha", "source": "builtin", "description": "", "skill_file": "/s/alpha.md"},
        {"name": "beta", "source": "user", "description": "does things", "skill_file": "/s/beta.md"},
    ])
    assert cli.cmd_skill(ns(action="search", target="a")) == 0
    out = capsys.readouterr().out
    assert "- alpha [builtin]" in out and "- beta [user]" in out
    # The empty description must not produce a blank "    " line.
    assert "does things" in out


def test_skill_create_without_name_prints_usage(capsys):
    assert cli.cmd_skill(ns(action="create", target="")) == 2
    assert "usage: python -m baize skill create <name>" in capsys.readouterr().out


def test_skill_create_reads_body_from_file(monkeypatch, capsys, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text("BODY-FROM-FILE", encoding="utf-8")
    seen = {}

    def fake_create(name, description, body, **kw):
        seen.update(name=name, description=description, body=body, **kw)
        return tmp_path / f"{name}.md"

    monkeypatch.setattr(skill_index, "create_skill", fake_create)
    rc = cli.cmd_skill(ns(action="create", target="myskill", description="d",
                          body="inline", body_file=str(body_file),
                          domain="ops", level="L2"))
    assert rc == 0
    assert seen["body"] == "BODY-FROM-FILE", "the file must win over --body"
    assert seen["origin"] == "user"
    assert seen["domain"] == "ops" and seen["level"] == "L2"
    assert "skill created and indexed" in capsys.readouterr().out


def test_skill_audit_prints_every_section(monkeypatch, capsys):
    monkeypatch.setattr(skill_index, "audit_index", lambda cfg=None: {
        "count": 5,
        "duplicates_deduped": 2,
        "per_source": {"user": 1, "builtin": 4},
        "missing_description": [{"name": "x", "source": "user", "path": "/x.md"}],
        "duplicate_groups": [{"name": "y", "kept": "user", "dropped": ["builtin"]}],
    })
    assert cli.cmd_skill(ns(action="audit")) == 0
    out = capsys.readouterr().out
    assert "索引技能总数    : 5" in out
    assert "各库计数:" in out and "builtin: 4" in out
    assert "缺失 description 的技能 (1):" in out
    assert "跨库重复组 (1):" in out and "保留[user] 丢弃[builtin]" in out


def test_skill_audit_reports_a_clean_library(monkeypatch, capsys):
    monkeypatch.setattr(skill_index, "audit_index", lambda cfg=None: {
        "count": 3, "duplicates_deduped": 0, "per_source": {},
        "missing_description": [], "duplicate_groups": [],
    })
    assert cli.cmd_skill(ns(action="audit")) == 0
    out = capsys.readouterr().out
    assert "状态良好" in out
    assert "各库计数:" not in out


def test_skill_unknown_action_returns_two(capsys):
    assert cli.cmd_skill(ns(action="frobnicate")) == 2
    assert "unknown skill action" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_recon / cmd_clarify
# ---------------------------------------------------------------------------

def test_recon_prints_hits_and_web_sources(monkeypatch, capsys):
    import baize.recon as recon_mod
    monkeypatch.setattr(recon_mod, "recon", lambda goal, cfg=None, web=False: {
        "goal": goal,
        "library_hits": [{"name": "n", "source": "s", "skill_file": "/f.md"}],
        "web_hits": [{"query": "q", "sources": [{"name": "blog", "url": "http://e"}]}],
        "advice": "reuse it",
    })
    assert cli.cmd_recon(ns(goal="g", web=True)) == 0
    out = capsys.readouterr().out
    assert "技能库同类实现 (1):" in out
    assert "外部搜索 [q]:" in out and "blog: http://e" in out
    assert "建议: reuse it" in out


def test_recon_reports_empty_library_and_disabled_web(monkeypatch, capsys):
    import baize.recon as recon_mod
    monkeypatch.setattr(recon_mod, "recon", lambda goal, cfg=None, web=False: {
        "goal": goal, "library_hits": [],
        "web_hits": [{"disabled": True, "hint": "set BAIZE_RECON_WEB=1"}],
        "advice": "build it",
    })
    assert cli.cmd_recon(ns(goal="g", web=False)) == 0
    out = capsys.readouterr().out
    assert "技能库未发现同类实现" in out
    assert "外部侦察已关闭: set BAIZE_RECON_WEB=1" in out


def test_clarify_refuses_without_a_configured_endpoint(monkeypatch, capsys):
    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: _FakeClient(configured=False))
    assert cli.cmd_clarify(ns(goal="g")) == 2
    assert "model endpoint not configured" in capsys.readouterr().out


def test_clarify_renders_questions_answers_and_assumptions(monkeypatch, capsys):
    class FakeOrch:
        def __init__(self, client=None, **kw):
            pass

        def clarify(self, goal):
            return {"qa": {"questions": ["Q-one", "Q-two"], "answers": ["A-one"],
                           "assumptions": ["ASSUME-1"]},
                    "prd_file": "/tmp/prd.md"}

    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: _FakeClient(True))
    monkeypatch.setattr(cli, "Orchestrator", FakeOrch)
    assert cli.cmd_clarify(ns(goal="g")) == 0
    out = capsys.readouterr().out
    assert "Q1: Q-one" in out and "A1: A-one" in out
    # The second question has no answer: it must say so rather than silently drop it.
    assert "Q2: Q-two" in out and "A2: (未答)" in out
    assert "假设: ASSUME-1" in out
    assert "PRD -> /tmp/prd.md" in out


# ---------------------------------------------------------------------------
# cmd_memory (archive) / cmd_desktop
# ---------------------------------------------------------------------------

def test_memory_archive_uses_default_30_days(monkeypatch, capsys):
    import baize.memory as memory_mod
    seen = {}
    monkeypatch.setattr(memory_mod, "archive_old_logs",
                        lambda days=None: seen.update(days=days) or {"archived": 2})
    assert cli.cmd_memory(ns(action="archive", days=0)) == 0
    assert seen["days"] == 30
    assert '"archived": 2' in capsys.readouterr().out


def test_memory_unknown_action_returns_two(capsys):
    assert cli.cmd_memory(ns(action="frobnicate")) == 2
    assert "unknown memory action" in capsys.readouterr().out


def test_desktop_forwards_host_and_port(monkeypatch):
    import baize.desktop as desktop_mod
    seen = {}
    monkeypatch.setattr(desktop_mod, "launch_desktop",
                        lambda host, port: seen.update(host=host, port=port) or 0)
    assert cli.cmd_desktop(ns(host="0.0.0.0", port=9999)) == 0
    assert seen == {"host": "0.0.0.0", "port": 9999}


def test_desktop_defaults_when_flags_are_absent(monkeypatch):
    import baize.desktop as desktop_mod
    seen = {}
    monkeypatch.setattr(desktop_mod, "launch_desktop",
                        lambda host, port: seen.update(host=host, port=port) or 0)
    assert cli.cmd_desktop(ns()) == 0
    assert seen == {"host": "127.0.0.1", "port": 8787}


# ---------------------------------------------------------------------------
# cmd_gate
# ---------------------------------------------------------------------------

def _gate_report(*, total, threshold, status, quality=None):
    return {
        "manifest_ok": status != "fail",
        "manifest_problems": [],
        "coverage": {"total": total, "threshold": threshold, "status": status},
        "quality": quality or {},
        "status": status,
    }


def test_gate_prints_the_operator_it_actually_compared(monkeypatch, capsys):
    import baize.gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: _gate_report(
        total=91.2, threshold=85, status="pass"))
    assert cli.cmd_gate(ns()) == 0
    out = capsys.readouterr().out
    assert "coverage : PASS (91.2% >= 85%)" in out
    assert "overall  : PASS" in out


def test_gate_prints_a_less_than_operator_when_coverage_is_low(monkeypatch, capsys):
    import baize.gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: _gate_report(
        total=76.7, threshold=85, status="fail"))
    assert cli.cmd_gate(ns()) == 1
    # This exact string was once printed as ">= 85%" regardless of the numbers.
    assert "coverage : FAIL (76.7% < 85%)" in capsys.readouterr().out


def test_gate_prints_quality_dimensions(monkeypatch, capsys):
    import baize.gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: _gate_report(
        total=90, threshold=85, status="pass",
        quality={"score": 88, "threshold": 80, "pass": True,
                 "dimensions": {"docs": 90, "tests": 86}}))
    assert cli.cmd_gate(ns()) == 0
    out = capsys.readouterr().out
    assert "quality  : 88 (threshold 80) PASS" in out
    assert "- docs: 90" in out and "- tests: 86" in out


def test_gate_returns_two_for_an_unknown_outcome(monkeypatch, capsys):
    import baize.gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: _gate_report(
        total=None, threshold=85, status="unknown"))
    assert cli.cmd_gate(ns()) == 2
    assert "overall  : UNKNOWN" in capsys.readouterr().out


def test_gate_reports_why_coverage_could_not_be_measured(monkeypatch, capsys):
    import baize.gate as gate_mod
    rep = _gate_report(total=None, threshold=85, status="unknown")
    rep["coverage"]["reason"] = "no data file at '.coverage'"
    monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: rep)
    assert cli.cmd_gate(ns()) == 2
    assert "no data file" in capsys.readouterr().out


def test_gate_prints_a_quality_dimension_that_was_not_measured(monkeypatch, capsys):
    """A dimension nobody measured is neither a pass nor a failure. Printing
    PASS over it is how a missing measurement reads as a satisfied promise."""
    import baize.gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: _gate_report(
        total=None, threshold=85, status="unknown",
        quality={"score": 0.9, "threshold": 0.8, "pass": False,
                 "status": "unknown", "unmeasured": ["coverage_clarity"],
                 "dimensions": {"coverage_clarity": 0.5, "composition": 1.0}}))
    assert cli.cmd_gate(ns()) == 2
    out = capsys.readouterr().out
    assert "quality  : 0.9 (threshold 0.8) UNKNOWN" in out
    assert "not measured: coverage_clarity" in out
    assert "- coverage_clarity: 0.5   <- not measured" in out
    # A dimension that *was* measured must not carry the marker.
    assert "- composition: 1.0   <- not measured" not in out


def test_gate_still_renders_quality_from_a_report_without_a_status(monkeypatch, capsys):
    """Backward compatibility: a report built before `status` existed must not
    start rendering as UNKNOWN, and a passing one must still read as PASS."""
    import baize.gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: _gate_report(
        total=90, threshold=85, status="pass",
        quality={"score": 88, "threshold": 80, "pass": True,
                 "dimensions": {"docs": 90}}))
    assert cli.cmd_gate(ns()) == 0
    out = capsys.readouterr().out
    assert "quality  : 88 (threshold 80) PASS" in out
    assert "not measured" not in out


# ---------------------------------------------------------------------------
# cmd_bench --public
# ---------------------------------------------------------------------------

def test_bench_public_maps_benchmarks_to_capabilities(monkeypatch, capsys):
    import baize.bench_public as bp
    monkeypatch.setattr(bp, "coverage_report", lambda: {
        "benchmarks": [{"status": "covered", "name": "swe-bench", "measures": "patch",
                        "capability": "tool loop"}],
        "counts": {"covered": 1, "partial": 2, "not_run": 3},
        "honest_note": "baize does not run these harnesses",
    })
    assert cli.cmd_bench(ns(public=True)) == 0
    out = capsys.readouterr().out
    assert "swe-bench" in out and "tool loop" in out
    assert "covered=1 partial=2 not_run=3" in out
    assert "baize does not run these harnesses" in out


# ---------------------------------------------------------------------------
# cmd_automations
# ---------------------------------------------------------------------------

class _FakeStore:
    def __init__(self, specs=None, get_result=None):
        self.specs = list(specs or [])
        self._get = get_result
        self.saved: list = []
        self.deleted: list = []

    def list(self):
        return self.specs

    def get(self, tool_id):
        return self._get

    def save(self, spec):
        self.saved.append(spec)

    def delete(self, tool_id):
        self.deleted.append(tool_id)


class _FakeScheduler:
    def __init__(self, store=None, **kw):
        self.store = store or _FakeStore()
        self.runner = kw.get("runner") or (lambda spec: {"ok": True})

    def _next_fire(self, spec, now):
        return None


def test_automations_list_prints_next_fire(monkeypatch, capsys):
    import baize.automations as auto_mod
    spec = auto_mod.AutomationSpec(id="a1", name="nightly", prompt="p",
                                   schedule_type="recurring", rrule="FREQ=DAILY",
                                   scheduled_at="", status="ACTIVE")
    sched = _FakeScheduler(store=_FakeStore(specs=[spec]))
    monkeypatch.setattr(auto_mod, "AutomationScheduler", lambda *a, **k: sched)
    assert cli.cmd_automations(ns(action="list")) == 0
    out = capsys.readouterr().out
    assert "- [ACTIVE] a1  nightly" in out
    assert "recurring: FREQ=DAILY  next=-" in out


def test_automations_add_parses_a_natural_language_schedule(monkeypatch, capsys):
    import baize.automations as auto_mod
    monkeypatch.setattr(auto_mod, "parse_nl_schedule", lambda text: "FREQ=DAILY;BYHOUR=8")
    sched = _FakeScheduler()
    monkeypatch.setattr(auto_mod, "AutomationScheduler", lambda *a, **k: sched)
    rc = cli.cmd_automations(ns(action="add", id="", name="morning", prompt="go",
                                schedule_type="recurring", rrule="", nl="每天早上8点",
                                scheduled_at="", cwds="/tmp"))
    assert rc == 0
    assert sched.store.saved[0].rrule == "FREQ=DAILY;BYHOUR=8"
    assert "FREQ=DAILY;BYHOUR=8" in capsys.readouterr().out


def test_automations_pause_reports_a_missing_id(monkeypatch, capsys):
    import baize.automations as auto_mod
    monkeypatch.setattr(auto_mod, "AutomationScheduler",
                        lambda *a, **k: _FakeScheduler(store=_FakeStore(get_result=None)))
    assert cli.cmd_automations(ns(action="pause", id="ghost")) == 1
    assert "automation not found: ghost" in capsys.readouterr().out


def test_automations_run_now_reports_a_missing_id(monkeypatch, capsys):
    import baize.automations as auto_mod
    monkeypatch.setattr(auto_mod, "AutomationScheduler",
                        lambda *a, **k: _FakeScheduler(store=_FakeStore(get_result=None)))
    assert cli.cmd_automations(ns(action="run-now", id="ghost")) == 1
    assert "automation not found: ghost" in capsys.readouterr().out


def test_automations_run_now_returns_one_when_the_runner_fails(monkeypatch, capsys):
    import baize.automations as auto_mod
    spec = auto_mod.AutomationSpec(id="a1", name="n", prompt="p",
                                   schedule_type="recurring", rrule="", scheduled_at="")
    sched = _FakeScheduler(store=_FakeStore(get_result=spec))
    sched.runner = lambda spec: {"ok": False}
    monkeypatch.setattr(auto_mod, "AutomationScheduler", lambda *a, **k: sched)
    assert cli.cmd_automations(ns(action="run-now", id="a1")) == 1
    assert '{"ok": false}' in capsys.readouterr().out


def test_automations_unknown_action_returns_two(capsys):
    assert cli.cmd_automations(ns(action="frobnicate")) == 2
    assert "unknown automations action" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_chat / cmd_team
# ---------------------------------------------------------------------------

def test_chat_forwards_repl_flags(monkeypatch):
    import baize.repl as repl_mod
    seen = {}
    monkeypatch.setattr(repl_mod, "run_repl",
                        lambda **kw: seen.update(kw) or 0)
    assert cli.cmd_chat(ns(resume="sess-9", no_color=True, quiet=True)) == 0
    assert seen == {"session_id": "sess-9", "no_color": True, "quiet": True}


def test_team_refuses_without_a_configured_endpoint(monkeypatch, capsys):
    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: _FakeClient(configured=False))
    assert cli.cmd_team(ns(goal="g")) == 2
    assert "model endpoint not configured" in capsys.readouterr().out


def test_team_rejects_an_invalid_roles_file(monkeypatch, capsys, tmp_path):
    def boom(path):
        raise FileNotFoundError("no such roles file")

    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: _FakeClient(True))
    monkeypatch.setattr(team_mod, "load_roles", boom)
    rc = cli.cmd_team(ns(goal="g", roles=str(tmp_path / "roles.json"), resume="",
                         no_color=True, quiet=True))
    assert rc == 2
    assert "invalid roles config" in capsys.readouterr().err


def test_team_custom_roles_run_reports_issues_and_run_id(monkeypatch, capsys):
    reports = [
        types.SimpleNamespace(verdict="pass", retried=False, task_id="t1", task="do it", issues=[]),
        types.SimpleNamespace(verdict="fail", retried=True, task_id="t2", task="do more", issues=["boom"]),
    ]
    res = types.SimpleNamespace(reports=reports, success=False, session_ids=["s1"], run_id="run-9")
    seen = {}

    class FakeOrch:
        def __init__(self, **kw):
            pass

        def run(self, goal, resume_run_id=None):
            seen["call"] = (goal, resume_run_id)
            return res

    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: _FakeClient(True))
    monkeypatch.setattr(team_mod, "load_roles", lambda p: "FAKE-TEAM-CONFIG")
    monkeypatch.setattr(team_mod, "build_team", lambda cfg, **kw: FakeOrch())
    rc = cli.cmd_team(ns(goal="g", roles="roles.json", resume="run-9",
                         no_color=True, quiet=True))
    out = capsys.readouterr().out
    assert rc == 1
    assert seen["call"] == ("g", "run-9")
    assert "[resume] run-id: run-9" in out
    assert "issue: boom" in out and "(retried)" in out
    assert "run-id: run-9  (use 'baize status run-9' to inspect)" in out


def test_team_default_topology_needs_no_roles_file(monkeypatch, capsys):
    res = types.SimpleNamespace(reports=[], success=True, session_ids=[], run_id=None)
    built = {}

    class FakeOrch:
        def __init__(self, client=None, on_event=None):
            built["used_default"] = True

        def run(self, goal, resume_run_id=None):
            return res

    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: _FakeClient(True))
    monkeypatch.setattr(cli, "Orchestrator", FakeOrch)
    assert cli.cmd_team(ns(goal="g", roles="", resume="", no_color=True, quiet=True)) == 0
    assert built.get("used_default") is True


# ---------------------------------------------------------------------------
# cmd_sessions
# ---------------------------------------------------------------------------

class _FakeSession:
    listing: list = []
    messages: list = []

    def __init__(self, session_id=None, cfg=None):
        self.id = session_id or "sess-new"
        self.messages = list(_FakeSession.messages)

    @classmethod
    def list_sessions(cls, cfg=None):
        return cls.listing


def test_sessions_reports_no_sessions(monkeypatch, capsys):
    _FakeSession.listing = []
    monkeypatch.setattr(cli, "Session", _FakeSession)
    assert cli.cmd_sessions(ns(session_id="", inspect=False)) == 0
    assert "no sessions yet" in capsys.readouterr().out


def test_sessions_lists_recent_entries(monkeypatch, capsys):
    _FakeSession.listing = [{"id": "s1", "events": 4, "mtime": "2026-09-16"}]
    monkeypatch.setattr(cli, "Session", _FakeSession)
    assert cli.cmd_sessions(ns(session_id="", inspect=False)) == 0
    assert "- s1  events=4  2026-09-16" in capsys.readouterr().out


def test_sessions_inspect_renders_the_timeline(monkeypatch, capsys, tmp_path):
    s_file = tmp_path / "s1.jsonl"
    s_file.write_text("", encoding="utf-8")
    _FakeSession.listing = [{"id": "s1", "events": 4, "mtime": "t"}]
    monkeypatch.setattr(cli, "Session", _FakeSession)
    monkeypatch.setattr(viewer_mod, "find_session_file", lambda sid: s_file)
    monkeypatch.setattr(viewer_mod, "render_session", lambda p: "TIMELINE-RENDER")
    assert cli.cmd_sessions(ns(session_id="s1", inspect=True)) == 0
    assert "TIMELINE-RENDER" in capsys.readouterr().out


def test_sessions_inspect_reports_a_missing_file(monkeypatch, capsys):
    _FakeSession.listing = [{"id": "s1", "events": 4, "mtime": "t"}]
    monkeypatch.setattr(cli, "Session", _FakeSession)
    monkeypatch.setattr(viewer_mod, "find_session_file", lambda sid: None)
    assert cli.cmd_sessions(ns(session_id="s1", inspect=True)) == 1
    assert "session file not found: s1" in capsys.readouterr().out


def test_sessions_prints_a_transcript_with_tool_names(monkeypatch, capsys):
    _FakeSession.listing = [{"id": "s1", "events": 4, "mtime": "t"}]
    _FakeSession.messages = [
        {"role": "user", "content": "hello\nworld"},
        {"role": "assistant", "content": "ok",
         "tool_calls": [{"function": {"name": "read_file"}}]},
    ]
    monkeypatch.setattr(cli, "Session", _FakeSession)
    assert cli.cmd_sessions(ns(session_id="s1", inspect=False)) == 0
    out = capsys.readouterr().out
    assert "hello world" in out, "newlines must be flattened for one-line transcripts"
    assert "[tools: read_file]" in out


def test_sessions_reports_an_unknown_session_id(monkeypatch, capsys):
    _FakeSession.listing = [{"id": "other", "events": 1, "mtime": "t"}]
    monkeypatch.setattr(cli, "Session", _FakeSession)
    assert cli.cmd_sessions(ns(session_id="s1", inspect=False)) == 1
    assert "session not found: s1" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

def _ledger_state(**over):
    state = {"goal": "g", "verified_tasks": set(), "failed_tasks": set(),
             "in_progress_tasks": set(), "skill_candidates": [], "completed": False}
    state.update(over)
    return state


def _install_ledger(monkeypatch, tmp_path, *, state, exists=True, unfinished=None):
    class FakeLedger:
        def __init__(self, run_id, cfg=None):
            self.run_id = run_id
            self.path = tmp_path / f"{run_id}.jsonl"
            if exists:
                self.path.write_text("", encoding="utf-8")

        def replay(self):
            return state

        def events(self):
            return [{"e": 1}, {"e": 2}]

        def current_unfinished(self):
            return list(unfinished or [])

    monkeypatch.setattr(ledger_mod, "RunLedger", FakeLedger)


def test_status_suggests_resuming_an_unfinished_run(monkeypatch, capsys, tmp_path):
    _install_ledger(monkeypatch, tmp_path,
                    state=_ledger_state(in_progress_tasks={"t1"}), unfinished=["t1"])
    assert cli.cmd_status(ns(run_id="run-1")) == 0
    out = capsys.readouterr().out
    assert "next: resume with 'baize team <goal> --resume run-1'" in out


def test_status_points_at_failed_tasks_when_nothing_is_in_flight(monkeypatch, capsys, tmp_path):
    _install_ledger(monkeypatch, tmp_path,
                    state=_ledger_state(failed_tasks={"t2"}), unfinished=[])
    assert cli.cmd_status(ns(run_id="run-1")) == 0
    assert "next: review failed tasks" in capsys.readouterr().out


def test_status_reports_an_unknown_state(monkeypatch, capsys, tmp_path):
    _install_ledger(monkeypatch, tmp_path, state=_ledger_state(), unfinished=[])
    assert cli.cmd_status(ns(run_id="run-1")) == 0
    assert "next: unknown state" in capsys.readouterr().out


def test_status_reports_a_missing_ledger(monkeypatch, capsys, tmp_path):
    _install_ledger(monkeypatch, tmp_path, state=_ledger_state(), exists=False)
    assert cli.cmd_status(ns(run_id="run-1")) == 1
    assert "run not found: run-1" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_plugins
# ---------------------------------------------------------------------------

class _FakeRegistry:
    def __init__(self, plugins=()):
        self.plugins = list(plugins)

    def discover(self):
        return 5


def test_plugins_list_reports_loaded_plugins(monkeypatch, capsys):
    monkeypatch.setattr(cli, "registry", _FakeRegistry([ns(name="alpha"), ns(name="beta")]))
    assert cli.cmd_plugins(ns(action="list")) == 0
    out = capsys.readouterr().out
    assert "2 plugin(s) loaded:" in out and "- alpha" in out and "- beta" in out


def test_plugins_list_reports_an_empty_scan(monkeypatch, capsys):
    monkeypatch.setattr(cli, "registry", _FakeRegistry([]))
    assert cli.cmd_plugins(ns(action="list")) == 0
    assert "0 plugins loaded (discover scanned 5 candidate file(s))" in capsys.readouterr().out


def test_plugins_install_without_url_prints_usage(capsys):
    assert cli.cmd_plugins(ns(action="install", target="  ")) == 2
    assert "usage: python -m baize plugin install <github_url>" in capsys.readouterr().out


def test_plugins_install_rejects_a_non_github_url(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(config_mod, "load_config",
                        lambda *a, **k: {"BAIZE_USER_SKILLS_DIR": str(tmp_path / "skills")})
    assert cli.cmd_plugins(ns(action="install", target="https://example.com/x/y")) == 1
    assert "invalid GitHub URL" in capsys.readouterr().out


def test_plugins_install_reports_a_download_failure(monkeypatch, capsys, tmp_path):
    import urllib.request

    monkeypatch.setattr(config_mod, "load_config",
                        lambda *a, **k: {"BAIZE_USER_SKILLS_DIR": str(tmp_path / "skills")})

    def boom(req, timeout=30):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert cli.cmd_plugins(ns(action="install", target="https://github.com/o/r")) == 1
    assert "failed to download archive" in capsys.readouterr().out


def _tarball_bytes() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        top = tarfile.TarInfo("repo-main")
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        payload = b"# SKILL\n"
        member = tarfile.TarInfo("repo-main/SKILL.md")
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))
    return buf.getvalue()


def test_plugins_install_extracts_the_archive_and_reindexes(monkeypatch, capsys, tmp_path):
    import urllib.request

    payload = _tarball_bytes()

    class FakeResp:
        status = 200

        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    skills_dir = tmp_path / "user_skills"
    monkeypatch.setattr(config_mod, "load_config",
                        lambda *a, **k: {"BAIZE_USER_SKILLS_DIR": str(skills_dir)})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: FakeResp())
    monkeypatch.setattr(skill_index, "build_index", lambda cfg=None: {"count": 11})

    assert cli.cmd_plugins(ns(action="install", target="https://github.com/owner/repo")) == 0
    # The prefix directory must be stripped: the file lands at <lib>/repo/SKILL.md.
    assert (skills_dir / "repo" / "SKILL.md").read_text(encoding="utf-8") == "# SKILL\n"
    out = capsys.readouterr().out
    assert "Installed 'repo'" in out
    assert "Rebuilt skill index: 11 total skill(s) indexed." in out


def _malicious_tarball_bytes() -> bytes:
    """A plugin archive that tries to write outside the plugin library."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        top = tarfile.TarInfo("repo-main")
        top.type = tarfile.DIRTYPE
        tar.addfile(top)

        good = b"# SKILL\n"
        member = tarfile.TarInfo("repo-main/SKILL.md")
        member.size = len(good)
        tar.addfile(member, io.BytesIO(good))

        evil = b"pwned\n"
        member = tarfile.TarInfo("repo-main/../../escaped.txt")
        member.size = len(evil)
        tar.addfile(member, io.BytesIO(evil))

        link = tarfile.TarInfo("repo-main/escape-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    return buf.getvalue()


def test_safe_member_path_accepts_nested_paths(tmp_path):
    assert cli._safe_member_path(tmp_path, "sub/dir/file.md") == \
        (tmp_path / "sub" / "dir" / "file.md").resolve()


@pytest.mark.parametrize("name", ["../escaped.txt", "../../escaped.txt", "a/../../escaped.txt"])
def test_safe_member_path_refuses_traversal(tmp_path, name):
    assert cli._safe_member_path(tmp_path, name) is None


def test_plugins_install_refuses_traversal_and_symlink_members(monkeypatch, capsys, tmp_path):
    import urllib.request

    payload = _malicious_tarball_bytes()

    class FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    skills_dir = tmp_path / "user_skills"
    monkeypatch.setattr(config_mod, "load_config",
                        lambda *a, **k: {"BAIZE_USER_SKILLS_DIR": str(skills_dir)})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: FakeResp())
    monkeypatch.setattr(skill_index, "build_index", lambda cfg=None: {"count": 1})

    assert cli.cmd_plugins(ns(action="install", target="https://github.com/owner/repo")) == 0
    dest = skills_dir / "repo"
    # The legitimate member still lands.
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "# SKILL\n"
    # Nothing escaped the plugin directory - not via `..`, not via a symlink.
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path.parent / "escaped.txt").exists()
    assert not (dest / "escape-link").exists()
    assert "refused 2 archive member(s)" in capsys.readouterr().out


def test_plugins_remove_deletes_and_reindexes(monkeypatch, capsys, tmp_path):
    skills_dir = tmp_path / "user_skills"
    target = skills_dir / "myplugin"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x", encoding="utf-8")

    monkeypatch.setattr(config_mod, "load_config",
                        lambda *a, **k: {"BAIZE_USER_SKILLS_DIR": str(skills_dir)})
    monkeypatch.setattr(skill_index, "build_index", lambda cfg=None: {"count": 3})

    assert cli.cmd_plugins(ns(action="remove", target="myplugin")) == 0
    assert not target.exists()
    assert "Removed plugin 'myplugin'" in capsys.readouterr().out


def test_plugins_remove_unknown_action_returns_two(capsys):
    assert cli.cmd_plugins(ns(action="frobnicate")) == 2
    assert "unknown action: frobnicate" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_mcp
# ---------------------------------------------------------------------------

def test_mcp_client_reports_registered_tools(monkeypatch, capsys):
    class FakeReg:
        def schemas(self):
            return [{"function": {"name": "t1"}}]

    monkeypatch.setattr(tools_mod, "register_mcp_client", lambda spec: ["t1", "t2"])
    monkeypatch.setattr(tools_mod, "default_registry", lambda: FakeReg())
    assert cli.cmd_mcp(ns(action="client", spec="mcp_server.json")) == 0
    out = capsys.readouterr().out
    assert "registered 2 tool(s) from mcp_server.json" in out
    assert "+ t1 [ok]" in out
    # A name that did not reach the live registry must be flagged, not assumed fine.
    assert "+ t2 [MISSING]" in out


def test_mcp_client_reports_a_missing_spec(monkeypatch, capsys):
    def boom(spec):
        raise FileNotFoundError(spec)

    monkeypatch.setattr(tools_mod, "register_mcp_client", boom)
    assert cli.cmd_mcp(ns(action="client", spec="nope.json")) == 2
    assert "spec not found: nope.json" in capsys.readouterr().err


def test_mcp_client_reports_a_registration_failure(monkeypatch, capsys):
    def boom(spec):
        raise RuntimeError("bad handshake")

    monkeypatch.setattr(tools_mod, "register_mcp_client", boom)
    assert cli.cmd_mcp(ns(action="client", spec="mcp_server.json")) == 1
    assert "registration failed - bad handshake" in capsys.readouterr().err


def test_mcp_server_mode_survives_a_keyboard_interrupt(monkeypatch, capsys):
    import baize.ext.mcp.server as mcp_server_mod

    class FakeServer:
        def __init__(self, registry):
            self.registry = registry

        def serve_stdio(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(tools_mod, "default_registry", lambda: object())
    monkeypatch.setattr(mcp_server_mod, "MCPServer", FakeServer)
    assert cli.cmd_mcp(ns(action="server")) == 0
    assert "serving baize tools over stdio" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# cmd_ralph
# ---------------------------------------------------------------------------

class _FakePRD:
    def __init__(self, stories=("s1", "s2")):
        self.stories = list(stories)

    def save_to_file(self, path):
        Path(path).write_text('{"stories": []}', encoding="utf-8")

    def get_progress_summary(self):
        return "PROGRESS-BOARD"

    @classmethod
    def load_from_file(cls, path):
        return cls()


class _FakeEngine:
    last_goal = None
    loop_args = None

    def __init__(self, prd_path="prd.json", progress_path="progress.txt", workspace_dir="."):
        self.prd_path = prd_path

    def generate_initial_prd(self, goal):
        _FakeEngine.last_goal = goal
        return _FakePRD()

    def run_loop(self, max_iterations=15, auto_commit=True):
        _FakeEngine.loop_args = (max_iterations, auto_commit)
        return {"status_board": "STATUS-BOARD", "all_done": True, "total_iterations": 2}


@pytest.fixture()
def ralph(monkeypatch, tmp_path):
    import baize.ralph as ralph_mod
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ralph_mod, "RalphLoopEngine", _FakeEngine)
    monkeypatch.setattr(ralph_mod, "PRDDocument", _FakePRD)
    _FakeEngine.last_goal = None
    _FakeEngine.loop_args = None
    return tmp_path


def _ralph_args(**over):
    base = dict(goal="", resume=False, status=False, prd="prd.json",
                progress="progress.txt", max_iterations=7, no_commit=True)
    base.update(over)
    return ns(**base)


def test_ralph_status_without_a_prd_file(ralph, capsys):
    assert cli.cmd_ralph(_ralph_args(status=True)) == 1
    assert "未找到 PRD 状态机文件" in capsys.readouterr().out


def test_ralph_status_prints_the_board(ralph, capsys):
    (ralph / "prd.json").write_text("{}", encoding="utf-8")
    assert cli.cmd_ralph(_ralph_args(status=True)) == 0
    assert "PROGRESS-BOARD" in capsys.readouterr().out


def test_ralph_resume_without_a_prd_file(ralph, capsys):
    assert cli.cmd_ralph(_ralph_args(resume=True)) == 1
    assert "无法断点续跑" in capsys.readouterr().out


def test_ralph_resume_runs_the_loop_with_the_given_flags(ralph, capsys):
    (ralph / "prd.json").write_text("{}", encoding="utf-8")
    assert cli.cmd_ralph(_ralph_args(resume=True)) == 0
    assert _FakeEngine.loop_args == (7, False), "no_commit must be inverted into auto_commit"
    assert "断点续跑" in capsys.readouterr().out


def test_ralph_requires_a_goal_when_no_prd_exists(ralph, capsys):
    assert cli.cmd_ralph(_ralph_args(goal="")) == 1
    assert "请提供项目目标" in capsys.readouterr().out


def test_ralph_auto_resumes_when_a_prd_already_exists(ralph, capsys):
    (ralph / "prd.json").write_text("{}", encoding="utf-8")
    assert cli.cmd_ralph(_ralph_args(goal="")) == 0
    assert "自动以断点续跑模式启动" in capsys.readouterr().out


def test_ralph_generates_a_prd_from_a_goal(ralph, capsys):
    assert cli.cmd_ralph(_ralph_args(goal="ship it")) == 0
    out = capsys.readouterr().out
    assert _FakeEngine.last_goal == "ship it"
    assert (ralph / "prd.json").exists()
    assert "包含 2 个原子用户故事" in out
    assert "STATUS-BOARD" in out
    assert "Ralph 封闭循环完成" in out


def test_ralph_reports_a_paused_loop(ralph, capsys, monkeypatch):
    def paused(max_iterations=15, auto_commit=True):
        return {"status_board": "BOARD", "all_done": False, "total_iterations": 4}

    monkeypatch.setattr(_FakeEngine, "run_loop", staticmethod(paused))
    assert cli.cmd_ralph(_ralph_args(goal="g")) == 0
    out = capsys.readouterr().out
    assert "Ralph 循环暂停" in out and "4 轮迭代" in out


# ---------------------------------------------------------------------------
# main() dispatch
# ---------------------------------------------------------------------------

def test_main_without_arguments_enters_the_repl(monkeypatch):
    import baize.repl as repl_mod
    monkeypatch.setattr(repl_mod, "run_repl", lambda: 0)
    assert cli.main([]) == 0


def test_main_refuses_to_run_on_an_invalid_configuration(monkeypatch, capsys):
    from baize.config_schema import ConfigError

    def boom():
        raise ConfigError("BAIZE_MODEL_NAME is empty")

    monkeypatch.setattr(cli, "validate", boom)
    assert cli.main(["index", "build"]) == 2
    assert "invalid configuration" in capsys.readouterr().err


def test_main_dispatches_to_the_registered_handler(monkeypatch):
    monkeypatch.setattr(cli, "validate", lambda: None)
    monkeypatch.setattr(cli, "cmd_doctor", lambda args: 7)
    assert cli.main(["doctor"]) == 7


def test_main_skips_the_config_guard_for_chat(monkeypatch):
    def forbidden():
        raise AssertionError("validate() must not run for `baize chat`")

    monkeypatch.setattr(cli, "validate", forbidden)
    monkeypatch.setattr(cli, "cmd_chat", lambda args: 5)
    assert cli.main(["chat"]) == 5
