"""``sandbox.plan_argv`` - OS isolation for argv-based exec, and its honesty.

WHY THIS EXISTS
    ``sandbox.run`` takes a command *string* and runs it through a shell.
    ``run_python`` cannot use it: it executes ``[python, -I, -c, <code>]``, an
    argv with no shell, because the snippet is arbitrary Python and quoting it
    into a command line would be an injection surface.

    The consequence was that ``BAIZE_SANDBOX_ENABLED=1`` confined ``bash`` and
    silently left ``run_python`` unconfined - one flag, two meanings. These
    tests pin the decision logic, the argv it produces, and the fact that a
    platform without a mechanism degrades *visibly* instead of claiming a
    boundary it does not have.

WHAT IS NOT VERIFIED HERE
    The kernel-level effect of the Landlock and Seatbelt paths. Landlock needs
    Linux; Seatbelt needs macOS. Both are exercised only down to "the plan is
    built correctly" (``preexec_fn`` is a callable / ``sandbox-exec`` is
    prefixed); that the kernel then refuses the write is untested on this
    machine and must not be reported as verified.
"""
from __future__ import annotations

import logging

from baize import sandbox, tools


# --------------------------------------------------------------------------- #
# Decision logic
# --------------------------------------------------------------------------- #

def test_plan_argv_is_a_passthrough_when_the_sandbox_is_disabled():
    plan = sandbox.plan_argv(["python", "-c", "print(1)"], "/ws",
                             cfg={"BAIZE_SANDBOX_ENABLED": "0"})

    assert plan.argv == ["python", "-c", "print(1)"]
    assert plan.mechanism == "none"
    assert plan.preexec_fn is None
    assert plan.degraded is False


def test_plan_argv_degrades_visibly_when_the_platform_has_no_mechanism(
        monkeypatch, caplog):
    """Enabled on a platform with no OS boundary must warn, not imply one."""
    monkeypatch.setattr(sandbox, "platform_mechanism", lambda: "logical-only")

    with caplog.at_level(logging.WARNING, logger="baize.sandbox"):
        plan = sandbox.plan_argv(["python", "-c", "print(1)"], "/ws",
                                 cfg={"BAIZE_SANDBOX_ENABLED": "1"})

    assert plan.mechanism == "logical-only"
    assert plan.degraded is True
    assert plan.preexec_fn is None
    assert plan.argv == ["python", "-c", "print(1)"]
    assert any("logical-only" in r.getMessage() for r in caplog.records)


def test_plan_argv_installs_a_preexec_when_landlock_is_available(monkeypatch):
    """The restriction rides in the child, so no shell quoting is involved."""
    monkeypatch.setattr(sandbox, "platform_mechanism", lambda: "landlock")

    plan = sandbox.plan_argv(["python", "-c", "print(1)"], "/ws",
                             cfg={"BAIZE_SANDBOX_ENABLED": "1"})

    assert plan.mechanism == "landlock"
    assert callable(plan.preexec_fn)
    assert plan.degraded is False
    # The argv itself is untouched: the boundary is the child, not the command.
    assert plan.argv == ["python", "-c", "print(1)"]


def test_plan_argv_prefixes_sandbox_exec_when_seatbelt_is_available(monkeypatch):
    monkeypatch.setattr(sandbox, "platform_mechanism", lambda: "seatbelt")

    plan = sandbox.plan_argv(["python", "-c", "print(1)"], "/ws",
                             cfg={"BAIZE_SANDBOX_ENABLED": "1"})

    assert plan.mechanism == "seatbelt"
    assert plan.preexec_fn is None
    assert plan.argv[:2] == ["sandbox-exec", "-p"]
    assert plan.argv[3:] == ["python", "-c", "print(1)"]
    # The profile has to name the workspace, or the sandbox confines nothing.
    assert "/ws" in plan.argv[2]
    assert plan.degraded is False


def test_plan_argv_coerces_every_element_to_str():
    """Popen wants str; a Path slipped in must not become a TypeError later."""
    from pathlib import Path
    given = Path("/usr/bin/python")
    plan = sandbox.plan_argv([given, "-c", "x"], "/ws",
                             cfg={"BAIZE_SANDBOX_ENABLED": "0"})

    # str(Path) is platform-dependent on Windows (backslash separators), so
    # compare against str(given) rather than a hardcoded POSIX spelling.
    assert plan.argv == [str(given), "-c", "x"]
    assert all(isinstance(a, str) for a in plan.argv)


def test_seatbelt_profile_denies_by_default_and_opens_writes_only_for_the_workspace():
    profile = sandbox._seatbelt_profile("/ws")

    assert "(deny default)" in profile
    assert '(allow file-write* (subpath "/ws"))' in profile
    assert "(allow file-read*)" in profile


# --------------------------------------------------------------------------- #
# The wiring: run_python must actually honour the switch
# --------------------------------------------------------------------------- #

def test_run_python_still_executes_when_the_sandbox_is_enabled(monkeypatch):
    """Wiring the switch must not break the tool on a platform that degrades."""
    monkeypatch.setenv("BAIZE_SANDBOX_ENABLED", "1")

    out = tools._tool_run_python("print(6 * 7)")

    assert "42" in out


def test_run_python_passes_the_snippet_as_an_argv_not_a_shell_string(monkeypatch):
    """Shell metacharacters in the snippet must reach Python verbatim.

    If the snippet were ever routed through ``sandbox.run``'s command *string*,
    this is the test that would catch the resulting quoting and injection bugs.
    """
    monkeypatch.setenv("BAIZE_SANDBOX_ENABLED", "1")

    out = tools._tool_run_python('print("a;b & c|d > e")')

    assert "a;b & c|d > e" in out


def test_run_python_still_reports_the_ast_guard_before_planning(monkeypatch):
    """The guardrail must stay the first gate, sandbox or not."""
    monkeypatch.setenv("BAIZE_SANDBOX_ENABLED", "1")

    out = tools._tool_run_python("import os\nprint(os.getcwd())")

    assert "blocked" in out
