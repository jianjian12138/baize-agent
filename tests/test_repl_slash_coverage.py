"""F6 coverage expansion: ``baize/repl.py`` slash-command surface.

``repl.py`` measured 63% with 135 missing statements - the largest single
uncovered *interactive* surface in the package. Everything missing was a slash
command: the ones that are only reached by typing them. A slash command that
crashes is invisible to the test suite unless the test suite types it.

So these tests type them. ``handle_slash`` is driven with the same strings a
user would type, and each test pins the observable effect (the session that was
swapped in, the file that was rewritten, the line that was printed).

Honesty notes
-------------
* ``Session`` / ``Agent`` / ``LLMClient`` are replaced with in-memory doubles so
  no session ledger, no network call and no ``~/.baize_history`` entry is
  created by the suite. The REPL's own logic - argument parsing, branching,
  message bookkeeping - is real.
* ``run()`` is exercised by feeding ``builtins.input`` a scripted sequence,
  including the interruption paths (Ctrl+C twice, EOF) that a human cannot
  reliably reproduce by hand.
* ``_extract_at_files`` is tested against a real temporary workspace, including
  the traversal attempt (``@../outside.py``) that must be refused.
"""
from __future__ import annotations

import builtins
import types
from pathlib import Path

import pytest

import baize.repl as repl_mod
import baize.session_viewer as viewer_mod
import baize.setup_wizard as wizard_mod
import baize.skill_index as skill_index


def ns(**kw) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kw)


class _FakeModel:
    def __init__(self, name="m1", base_url="http://x", provider="deepseek", api_key="sk-1234567890"):
        self.name = name
        self.base_url = base_url
        self.provider = provider
        self.api_key = api_key


class _FakeClient:
    def __init__(self, cfg=None, configured=True, models=()):
        self.cfg = cfg
        self.configured = configured
        self.models = list(models)


class _FakeSession:
    """In-memory stand-in for baize.agent.Session."""

    listing: list = []
    fail_ids: set = set()
    directory: Path | None = None

    def __init__(self, session_id=None, cfg=None):
        if session_id in type(self).fail_ids:
            raise ValueError(f"no session named {session_id}")
        self.id = session_id or "sess-1"
        self.messages: list = []
        self.file = (type(self).directory or Path(".")) / f"{self.id}.jsonl"

    def append(self, message):
        self.messages.append(message)

    @classmethod
    def list_sessions(cls, cfg=None):
        return list(cls.listing)


class _FakeAgent:
    result = None
    last_goal = None

    def __init__(self, role="executor", client=None, session=None, on_event=None):
        self.session = session

    def run(self, goal):
        type(self).last_goal = goal
        if isinstance(type(self).result, BaseException):
            raise type(self).result
        if type(self).result is not None:
            return type(self).result
        return ns(stopped_reason="final", final_text="FINAL-TEXT", steps=1, tool_calls=0)


@pytest.fixture()
def repl(monkeypatch, tmp_path):
    monkeypatch.setattr(repl_mod, "LLMClient", _FakeClient)
    monkeypatch.setattr(repl_mod, "Session", _FakeSession)
    monkeypatch.setattr(repl_mod, "Agent", _FakeAgent)
    _FakeSession.listing = []
    _FakeSession.fail_ids = set()
    _FakeSession.directory = tmp_path
    _FakeAgent.result = None
    _FakeAgent.last_goal = None
    instance = repl_mod.BaizeREPL(no_color=True, quiet=True)
    instance.client = _FakeClient(configured=True, models=[_FakeModel()])
    return instance


# ---------------------------------------------------------------------------
# informational commands
# ---------------------------------------------------------------------------

def test_help_lists_the_slash_commands(repl, capsys):
    repl.handle_slash("/help")
    out = capsys.readouterr().out
    assert "/rewind [N]" in out
    assert "/cost" in out


def test_unknown_command_is_named_in_the_error(repl, capsys):
    repl.handle_slash("/frobnicate")
    assert "Unknown command: /frobnicate" in capsys.readouterr().out


def test_reset_swaps_in_a_brand_new_session(repl, capsys):
    repl.session = _FakeSession(session_id="old")
    repl.handle_slash("/reset")
    assert repl.session.id == "sess-1"
    assert repl.session_id == "sess-1"
    assert repl.agent is not None
    assert "Started new session: sess-1" in capsys.readouterr().out


def test_history_reports_an_empty_store(repl, capsys):
    _FakeSession.listing = []
    repl.handle_slash("/history")
    assert "No previous sessions found." in capsys.readouterr().out


def test_history_marks_the_current_session(repl, capsys):
    repl.session = _FakeSession(session_id="s1")
    _FakeSession.listing = [{"id": "s1", "events": 3, "mtime": "2026-09-16"},
                            {"id": "s2", "events": 1, "mtime": "2026-09-15"}]
    repl.handle_slash("/history")
    out = capsys.readouterr().out
    assert "Recent Sessions:" in out
    assert "s1  events=3  2026-09-16 (current)" in out
    assert "s2  events=1  2026-09-15" in out


def test_resume_without_an_id_prints_usage(repl, capsys):
    repl.handle_slash("/resume")
    assert "Usage: /resume <session_id>" in capsys.readouterr().out


def test_resume_switches_to_an_existing_session(repl, capsys):
    repl.handle_slash("/resume sess-42")
    assert repl.session_id == "sess-42"
    assert repl.agent is not None
    assert "Resumed session: sess-42 (0 messages)" in capsys.readouterr().out


def test_resume_reports_a_failure_instead_of_crashing(repl, capsys):
    _FakeSession.fail_ids = {"ghost"}
    repl.handle_slash("/resume ghost")
    out = capsys.readouterr().out
    assert "Failed to resume session 'ghost'" in out
    assert repl.running is True


# ---------------------------------------------------------------------------
# fork / rewind
# ---------------------------------------------------------------------------

def test_fork_without_a_session_says_so(repl, capsys):
    repl.session = None
    repl.handle_slash("/fork")
    assert "No active session to fork." in capsys.readouterr().out


def test_fork_copies_the_transcript_into_a_new_branch(repl, capsys):
    repl.session = _FakeSession(session_id="base")
    repl.session.messages = [{"role": "user", "content": "hi"}]
    repl.handle_slash("/fork branch-a")
    assert repl.session_id == "branch-a"
    assert repl.session.messages == [{"role": "user", "content": "hi"}]
    assert "Parallel session forked: branch-a (1 messages)" in capsys.readouterr().out


def test_rewind_without_messages_says_so(repl, capsys):
    repl.session = _FakeSession(session_id="s1")
    repl.handle_slash("/rewind")
    assert "No messages in active session to rewind." in capsys.readouterr().out


def test_rewind_drops_the_requested_number_of_turns(repl, capsys):
    repl.session = _FakeSession(session_id="s1")
    repl.session.messages = [
        {"role": "user", "content": "t1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "t2"},
        {"role": "assistant", "content": "a2"},
    ]
    repl.handle_slash("/rewind 1")
    # One turn = the last user message and everything after it.
    assert [m["content"] for m in repl.session.messages] == ["t1", "a1"]
    assert "Rewound 1 turn(s). Active session now has 2 messages." in capsys.readouterr().out


def test_rewind_rewrites_the_ledger_file_on_disk(repl, capsys, tmp_path):
    repl.session = _FakeSession(session_id="s1")
    repl.session.file.write_text('{"role": "user", "content": "old"}\n', encoding="utf-8")
    repl.session.messages = [
        {"role": "user", "content": "t1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "t2"},
        {"role": "assistant", "content": "a2"},
    ]
    repl.handle_slash("/rewind 1")
    remaining = repl.session.file.read_text(encoding="utf-8").strip().splitlines()
    # One turn was dropped, so the first turn survives on disk as two lines.
    assert len(remaining) == 2
    assert '"t1"' in remaining[0] and '"a1"' in remaining[1]
    assert "Rewound 1 turn(s). Active session now has 2 messages." in capsys.readouterr().out


def test_rewind_clears_a_transcript_with_no_user_turns(repl, capsys):
    repl.session = _FakeSession(session_id="s1")
    repl.session.messages = [{"role": "assistant", "content": "orphan"}]
    repl.handle_slash("/rewind")
    assert repl.session.messages == []
    assert "Rewound 1 turn(s). Active session now has 0 messages." in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cost / trace / model
# ---------------------------------------------------------------------------

def test_cost_without_a_session_says_so(repl, capsys):
    repl.session = None
    repl.handle_slash("/cost")
    assert "No active session." in capsys.readouterr().out


def test_cost_estimates_tokens_and_dollars_from_the_transcript(repl, capsys):
    repl.session = _FakeSession(session_id="s1")
    repl.session.messages = [
        {"role": "user", "content": "x" * 40},
        {"role": "assistant", "content": "y" * 40},
        {"role": "tool", "content": "z" * 20},
    ]
    repl.handle_slash("/cost")
    out = capsys.readouterr().out
    assert "Est. Total Tokens: ~25 tokens (100 chars)" in out
    assert "LLM Responses:     1" in out
    assert "Tool Executions:   1" in out


def test_trace_without_a_session_id_says_so(repl, capsys):
    repl.session = None
    repl.handle_slash("/trace")
    assert "No active session to trace." in capsys.readouterr().out


def test_trace_reports_a_missing_session_file(repl, capsys, monkeypatch):
    repl.session = _FakeSession(session_id="s1")
    monkeypatch.setattr(viewer_mod, "find_session_file", lambda sid, cfg=None: None)
    repl.handle_slash("/trace")
    assert "Session file not found for: s1" in capsys.readouterr().out


def test_trace_renders_the_timeline(repl, capsys, monkeypatch, tmp_path):
    repl.session = _FakeSession(session_id="s1")
    s_file = tmp_path / "s1.jsonl"
    s_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(viewer_mod, "find_session_file", lambda sid, cfg=None: s_file)
    monkeypatch.setattr(viewer_mod, "render_session", lambda p: "TIMELINE")
    repl.handle_slash("/trace")
    assert "TIMELINE" in capsys.readouterr().out


def test_model_switch_reloads_the_client(repl, capsys, monkeypatch):
    monkeypatch.setenv("BAIZE_MODEL_NAME", "before")
    monkeypatch.setattr(repl_mod, "LLMClient", lambda cfg=None: _FakeClient(cfg, True))
    repl.handle_slash("/model gpt-4o")
    assert "Switched active model to: gpt-4o" in capsys.readouterr().out
    assert repl.client.cfg is not None


def test_model_without_argument_lists_configuration(repl, capsys):
    repl.client = _FakeClient(configured=True, models=[_FakeModel(api_key="sk-abcdefghijkl")])
    repl.handle_slash("/model")
    out = capsys.readouterr().out
    assert "Configured: True" in out
    assert "Model: m1 | URL: http://x | Provider: deepseek" in out
    # A long key is masked; only the first 6 and last 4 characters survive.
    assert "sk-abc...ijkl" in out


def test_model_listing_masks_a_short_key(repl, capsys):
    repl.client = _FakeClient(configured=False, models=[_FakeModel(api_key="short")])
    repl.handle_slash("/model")
    assert "Key: (set)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# paste / skills / memory / status / setup / clear / quit
# ---------------------------------------------------------------------------

def test_paste_cancels_on_eof(repl, capsys, monkeypatch):
    def eof(*a, **k):
        raise EOFError

    monkeypatch.setattr(builtins, "input", eof)
    repl.handle_slash("/paste")
    assert "[Paste mode cancelled]" in capsys.readouterr().out


def test_paste_submits_the_collected_lines(repl, capsys, monkeypatch):
    feed = iter(["line one", "line two", "/end"])
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(feed))
    repl.client = _FakeClient(configured=False)
    repl.handle_slash("/paste")
    out = capsys.readouterr().out
    assert "Multi-line Paste Mode" in out
    # Not configured, so the goal is refused - but the refusal proves the paste
    # actually reached _execute_goal with the joined content.
    assert "未配置大模型端点" in out


def test_paste_of_blank_lines_executes_nothing(repl, capsys, monkeypatch):
    feed = iter(["   ", "/end"])
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(feed))
    repl.client = _FakeClient(configured=False)
    repl.handle_slash("/paste")
    out = capsys.readouterr().out
    assert "未配置大模型端点" not in out


def test_skills_reports_an_empty_library(repl, capsys, monkeypatch):
    monkeypatch.setattr(skill_index, "search", lambda kw, limit=10, cfg=None: [])
    repl.handle_slash("/skills")
    assert "No skills indexed." in capsys.readouterr().out


def test_skills_lists_hits_with_source(repl, capsys, monkeypatch):
    monkeypatch.setattr(skill_index, "search", lambda kw, limit=10, cfg=None: [
        {"name": "alpha", "source": "builtin", "description": "d" * 100},
    ])
    repl.handle_slash("/skills alpha")
    out = capsys.readouterr().out
    assert "Available Skills (1 hits):" in out
    assert "alpha [builtin]" in out


def test_memory_without_query_prints_stats(repl, capsys):
    repl.handle_slash("/memory")
    out = capsys.readouterr().out
    assert "Memory Stats:" in out
    assert "Notes size:" in out


def test_memory_query_with_no_records(repl, capsys, monkeypatch):
    import baize.memory as memory_mod
    monkeypatch.setattr(memory_mod, "recall", lambda *a, **k: [])
    repl.handle_slash("/memory nothing")
    assert "No memory records found for 'nothing'." in capsys.readouterr().out


def test_memory_query_lists_records(repl, capsys, monkeypatch):
    import baize.memory as memory_mod
    monkeypatch.setattr(memory_mod, "recall", lambda *a, **k: [
        {"timestamp": "2026-09-16T10:00:00Z", "tags": ["a", "b"], "text": "remembered"},
    ])
    repl.handle_slash("/memory something")
    out = capsys.readouterr().out
    assert "Memory Recall (1 matches):" in out
    assert "[a,b]" in out and "remembered" in out


def test_status_without_a_session_says_so(repl, capsys):
    repl.session = None
    repl.handle_slash("/status")
    assert "No active session." in capsys.readouterr().out


def test_status_counts_tool_observations(repl, capsys):
    repl.session = _FakeSession(session_id="s1")
    repl.session.messages = [{"role": "tool", "content": "o"}, {"role": "user", "content": "u"}]
    repl.handle_slash("/status")
    out = capsys.readouterr().out
    assert "Current Session: s1" in out
    assert "Tool observations recorded: 1" in out


def test_setup_hot_reloads_the_configuration_on_success(repl, capsys, monkeypatch):
    monkeypatch.setattr(wizard_mod, "run_setup_wizard", lambda: True)
    monkeypatch.setattr(repl_mod, "LLMClient", lambda cfg=None: _FakeClient(cfg, True))
    repl.handle_slash("/setup")
    assert "LLM 配置已热更新并重新加载" in capsys.readouterr().out


def test_setup_does_not_reload_when_the_wizard_is_cancelled(repl, capsys, monkeypatch):
    monkeypatch.setattr(wizard_mod, "run_setup_wizard", lambda: False)
    repl.handle_slash("/setup")
    assert "LLM 配置已热更新并重新加载" not in capsys.readouterr().out


def test_clear_repaints_the_banner(repl, capsys):
    repl.handle_slash("/clear")
    out = capsys.readouterr().out
    assert "\033[2J\033[H" in out
    assert "Baize Agent Autonomous Engine" in out


def test_quit_stops_the_loop(repl, capsys):
    repl.handle_slash("/exit")
    assert repl.running is False
    assert "Goodbye!" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _extract_at_files
# ---------------------------------------------------------------------------

def test_at_file_returns_text_unchanged_when_nothing_is_referenced(tmp_path):
    text, attached = repl_mod._extract_at_files("plain goal", tmp_path)
    assert text == "plain goal"
    assert attached == []


def test_at_file_ingests_a_whole_file(tmp_path):
    (tmp_path / "a.py").write_text("line1\nline2\n", encoding="utf-8")
    _, attached = repl_mod._extract_at_files("see @a.py", tmp_path)
    # splitlines() on "line1\nline2\n" yields two lines, not three.
    assert attached[0]["header"] == "a.py (2 lines)"
    assert "line1" in attached[0]["snippet"]


def test_at_file_ingests_a_line_range(tmp_path):
    (tmp_path / "a.py").write_text("\n".join(f"L{i}" for i in range(1, 11)), encoding="utf-8")
    _, attached = repl_mod._extract_at_files("see @a.py:3-5", tmp_path)
    assert attached[0]["header"] == "a.py (lines 3-5)"
    assert attached[0]["snippet"] == "L3\nL4\nL5"


def test_at_file_ingests_a_single_line(tmp_path):
    (tmp_path / "a.py").write_text("\n".join(f"L{i}" for i in range(1, 6)), encoding="utf-8")
    _, attached = repl_mod._extract_at_files("see @a.py:2", tmp_path)
    assert attached[0]["header"] == "a.py (line 2)"
    assert attached[0]["snippet"] == "L2"


def test_at_file_deduplicates_repeated_references(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    _, attached = repl_mod._extract_at_files("@a.py and again @a.py", tmp_path)
    assert len(attached) == 1


def test_at_file_refuses_to_escape_the_workspace(tmp_path):
    outside = tmp_path.parent / "outside_secret.py"
    outside.write_text("SECRET", encoding="utf-8")
    try:
        _, attached = repl_mod._extract_at_files("see @../outside_secret.py", tmp_path)
        assert attached == [], "a traversal path must not be ingested"
    finally:
        outside.unlink(missing_ok=True)


def test_at_file_skips_a_path_that_does_not_exist(tmp_path):
    _, attached = repl_mod._extract_at_files("see @nope.py", tmp_path)
    assert attached == []


def test_at_file_skips_a_file_that_cannot_be_read(tmp_path, monkeypatch):
    target = tmp_path / "locked.py"
    target.write_text("x", encoding="utf-8")
    original = Path.read_text

    def boom(self, *a, **k):
        if self.name == "locked.py":
            raise OSError("denied")
        return original(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", boom)
    _, attached = repl_mod._extract_at_files("see @locked.py", tmp_path)
    assert attached == []


# ---------------------------------------------------------------------------
# _format_user_friendly_error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,needle", [
    ("unknown url type: 'foo'", "Base URL 格式无效"),
    ("HTTP 401 Unauthorized", "API Key 无效或未授权"),
    ("HTTP 404 not found", "模型名称或端点路径不存在"),
    ("HTTP 429 rate limit exceeded", "请求频次超限或账户余额不足"),
    ("[WinError 10061] connection refused", "连接被拒绝"),
    ("request timed out", "请求超时"),
])
def test_friendly_errors_are_mapped(raw, needle):
    assert needle in repl_mod._format_user_friendly_error(raw)


def test_friendly_error_falls_back_and_redacts_the_endpoint():
    msg = repl_mod._format_user_friendly_error("boom calling https://api.secret.example/v1/chat")
    assert "https://api.secret.example/v1/chat" not in msg
    assert "<api-endpoint>" in msg
    assert msg.endswith("（可输入 /setup 重新设置）")


# ---------------------------------------------------------------------------
# _execute_goal
# ---------------------------------------------------------------------------

def test_execute_goal_refuses_without_a_configured_endpoint(repl, capsys):
    repl.client = _FakeClient(configured=False)
    repl._execute_goal("do something")
    assert "未配置大模型端点" in capsys.readouterr().out


def test_execute_goal_attaches_referenced_files(repl, capsys, monkeypatch, tmp_path):
    (tmp_path / "ctx.py").write_text("CTX", encoding="utf-8")
    monkeypatch.setattr(repl_mod, "ROOT", tmp_path)
    repl.agent = _FakeAgent()
    repl._execute_goal("fix @ctx.py")
    out = capsys.readouterr().out
    assert "[Context Ingested] ctx.py (1 lines)" in out
    assert "### Context File: `ctx.py`" in _FakeAgent.last_goal
    assert "FINAL-TEXT" in out


def test_execute_goal_translates_an_error_result(repl, capsys):
    repl.agent = _FakeAgent()
    _FakeAgent.result = ns(stopped_reason="error", final_text="HTTP 401 Unauthorized",
                           steps=0, tool_calls=0)
    repl._execute_goal("go")
    assert "API Key 无效或未授权" in capsys.readouterr().out


def test_execute_goal_survives_a_keyboard_interrupt(repl, capsys):
    repl.agent = _FakeAgent()
    _FakeAgent.result = KeyboardInterrupt()
    repl._execute_goal("go")
    assert "[Interrupted by user]" in capsys.readouterr().out


def test_execute_goal_reports_an_unexpected_exception(repl, capsys):
    repl.agent = _FakeAgent()
    _FakeAgent.result = RuntimeError("kaboom")
    repl._execute_goal("go")
    assert "Execution error: kaboom" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run() - the loop itself
# ---------------------------------------------------------------------------

class _Feed:
    """Scripted stand-in for builtins.input; exhaustion raises EOFError."""

    def __init__(self, items):
        self.items = list(items)
        self.seen: list = []

    def __call__(self, prompt=""):
        self.seen.append(prompt)
        if not self.items:
            raise EOFError
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture()
def headless(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(repl_mod, "sys", types.SimpleNamespace(
        stdin=types.SimpleNamespace(isatty=lambda: False)))
    return tmp_path


def test_run_exits_cleanly_on_eof(repl, headless, capsys, monkeypatch):
    monkeypatch.setattr(builtins, "input", _Feed([]))
    assert repl.run() == 0
    assert "Goodbye!" in capsys.readouterr().out


def test_run_skips_blank_lines_and_handles_slash_commands(repl, headless, capsys, monkeypatch):
    monkeypatch.setattr(builtins, "input", _Feed(["   ", "/quit"]))
    assert repl.run() == 0
    assert repl.running is False


def test_run_double_ctrl_c_breaks_out(repl, headless, capsys, monkeypatch):
    monkeypatch.setattr(builtins, "input",
                        _Feed([KeyboardInterrupt(), KeyboardInterrupt()]))
    assert repl.run() == 0
    out = capsys.readouterr().out
    assert "再次按 Ctrl+C 或输入 /quit 退出" in out
    assert "Goodbye!" in out


def test_run_collects_a_triple_quoted_block(repl, headless, capsys, monkeypatch):
    repl.client = _FakeClient(configured=False)
    monkeypatch.setattr(builtins, "input",
                        _Feed(['"""start', "body", 'end"""', "/quit"]))
    assert repl.run() == 0
    out = capsys.readouterr().out
    assert "multiline input, end with closing quotes" in out
    # The block was assembled and handed to _execute_goal, which refused it
    # because no endpoint is configured - proof it was not silently dropped.
    assert "未配置大模型端点" in out


def test_run_discards_an_empty_multiline_block(repl, headless, capsys, monkeypatch):
    repl.client = _FakeClient(configured=False)
    monkeypatch.setattr(builtins, "input", _Feed(['"""', '"""', "/quit"]))
    assert repl.run() == 0
    assert "未配置大模型端点" not in capsys.readouterr().out


def test_run_abandons_a_multiline_block_on_eof(repl, headless, capsys, monkeypatch):
    repl.client = _FakeClient(configured=False)
    monkeypatch.setattr(builtins, "input",
                        _Feed(['"""start', "body", EOFError(), "/quit"]))
    assert repl.run() == 0
    assert "未配置大模型端点" not in capsys.readouterr().out


def test_run_offers_the_setup_wizard_on_a_tty_without_config(repl, headless, monkeypatch, capsys):
    monkeypatch.setattr(repl_mod, "sys", types.SimpleNamespace(
        stdin=types.SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(wizard_mod, "run_setup_wizard", lambda: True)
    repl.client = _FakeClient(configured=False)
    monkeypatch.setattr(builtins, "input", _Feed(["y", EOFError()]))
    assert repl.run() == 0
    assert "配置成功，已连接大模型" in capsys.readouterr().out


def test_run_declines_the_setup_wizard_when_the_user_says_no(repl, headless, monkeypatch, capsys):
    monkeypatch.setattr(repl_mod, "sys", types.SimpleNamespace(
        stdin=types.SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(wizard_mod, "run_setup_wizard", lambda: True)
    repl.client = _FakeClient(configured=False)
    monkeypatch.setattr(builtins, "input", _Feed(["n", EOFError()]))
    assert repl.run() == 0
    assert "配置成功，已连接大模型" not in capsys.readouterr().out


def test_run_survives_a_keyboard_interrupt_during_first_run_setup(repl, headless, monkeypatch):
    monkeypatch.setattr(repl_mod, "sys", types.SimpleNamespace(
        stdin=types.SimpleNamespace(isatty=lambda: True)))
    repl.client = _FakeClient(configured=False)
    monkeypatch.setattr(builtins, "input", _Feed([KeyboardInterrupt(), EOFError()]))
    assert repl.run() == 0


def test_run_reaches_the_agent_for_a_plain_goal(repl, headless, monkeypatch, capsys):
    repl.client = _FakeClient(configured=True)
    repl.agent = _FakeAgent()
    monkeypatch.setattr(builtins, "input", _Feed(["ship the feature", "/quit"]))
    assert repl.run() == 0
    assert _FakeAgent.last_goal == "ship the feature"
    assert "FINAL-TEXT" in capsys.readouterr().out


def test_run_repl_builds_and_runs_a_repl(repl, monkeypatch):
    monkeypatch.setattr(repl_mod, "LLMClient", _FakeClient)
    monkeypatch.setattr(repl_mod, "Session", _FakeSession)
    monkeypatch.setattr(repl_mod, "Agent", _FakeAgent)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(".")))
    monkeypatch.setattr(repl_mod, "sys", types.SimpleNamespace(
        stdin=types.SimpleNamespace(isatty=lambda: False)))
    monkeypatch.setattr(builtins, "input", _Feed([]))
    assert repl_mod.run_repl(no_color=True, quiet=True) == 0
