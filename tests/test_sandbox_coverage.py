"""Coverage expansion for baize.sandbox - platform mechanism selection, the
Seatbelt command builder (pure), the disabled / degraded run paths, and the
plain-run timeout branch.

The Landlock / Seatbelt *execution* branches are ``# pragma: no cover``
(Linux / macOS only) and cannot run on this Windows host, but we still cover
``platform_mechanism()`` returning those names via monkeypatched platform +
injected fake modules, and we unit-test the Seatbelt profile builder directly.
"""
from __future__ import annotations

import sys
import types

from baize import sandbox
from baize.sandbox import SandboxResult, platform_mechanism, run, _seatbelt_command


def test_platform_mechanism_windows_is_logical_only(monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Windows")
    assert platform_mechanism() == "logical-only"


def test_platform_mechanism_linux_landlock_unavailable(monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Linux")
    # Ensure no real landlock is importable here; the guarded import fails.
    monkeypatch.setitem(sys.modules, "landlock", None)
    assert platform_mechanism() == "logical-only"


def test_platform_mechanism_linux_landlock_available(monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Linux")
    fake = types.ModuleType("landlock")
    fake.create_ruleset = lambda: None
    monkeypatch.setitem(sys.modules, "landlock", fake)
    assert platform_mechanism() == "landlock"


def test_platform_mechanism_darwin_seatbelt_present(monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(sandbox, "which",
                        lambda x: "/usr/bin/sandbox-exec" if x == "sandbox-exec"
                        else None)
    assert platform_mechanism() == "seatbelt"


def test_platform_mechanism_darwin_seatbelt_absent(monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(sandbox, "which", lambda x: None)
    assert platform_mechanism() == "logical-only"


def test_seatbelt_command_builds_profile():
    wrapped = _seatbelt_command("echo hi", "/tmp/ws")
    assert wrapped.startswith("sandbox-exec -p")
    assert "sandbox-exec" in wrapped
    assert '(subpath "/tmp/ws")' in wrapped
    assert "echo hi" in wrapped
    # The profile denies by default but allows reading + writing the workspace.
    assert "(deny default)" in wrapped
    assert "(allow file-read*)" in wrapped


def test_run_disabled_is_plain(tmp_path):
    cfg = {"BAIZE_SANDBOX_ENABLED": "0", "BAIZE_WORKSPACE_DIR": str(tmp_path)}
    res = run("echo ok", cwd=str(tmp_path), timeout=30, cfg=cfg)
    assert isinstance(res, SandboxResult)
    assert res.mechanism == "none"
    assert res.degraded is False
    assert "ok" in res.stdout
    assert res.returncode == 0


def test_run_enabled_degrades_to_logical_only(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Windows")
    cfg = {"BAIZE_SANDBOX_ENABLED": "1", "BAIZE_WORKSPACE_DIR": str(tmp_path)}
    res = run("echo ok", cwd=str(tmp_path), timeout=30, cfg=cfg)
    assert res.degraded is True
    assert res.mechanism == "logical-only"
    assert "ok" in res.stdout
    assert res.returncode == 0


def test_plain_run_times_out(tmp_path):
    # A command that outlives the timeout -> TimeoutExpired -> rc -1.
    res = sandbox._plain(
        'python -c "import time; time.sleep(3)"',
        cwd=str(tmp_path), timeout=1)
    assert res.returncode == -1
    assert "timed out" in res.stderr
    assert res.mechanism == "none"


def _install_fake_landlock(monkeypatch):
    """Inject a no-op landlock stdlib stand-in so the helper functions can be
    exercised on a non-Linux host without actually restricting this process."""
    fake = types.ModuleType("landlock")

    class _Ruleset:
        def add_rule(self, *a, **k):
            pass

        def restrict_self(self):
            pass

    fake.create_ruleset = lambda: _Ruleset()
    access = types.ModuleType("landlock.access")
    access.FS_ROUGHLY_READ = 1
    access.FS_ROUGHLY_EXECUTE = 2
    access.FS_ROUGHLY_WRITE = 4
    monkeypatch.setitem(sys.modules, "landlock", fake)
    monkeypatch.setitem(sys.modules, "landlock.access", access)
    return fake


def test_apply_landlock_runs_with_fake_module(monkeypatch):
    _install_fake_landlock(monkeypatch)
    # Should build the ruleset and call restrict_self without raising.
    sandbox._apply_landlock("/tmp/ws")


def test_landlock_preexec_child_invokes_apply(monkeypatch):
    _install_fake_landlock(monkeypatch)
    child = sandbox._landlock_preexec("/tmp/ws")
    # The returned closure applies landlock in the (would-be) child process.
    child()


def test_run_unreachable_fallback_is_honest(monkeypatch, tmp_path):
    """If platform_mechanism returns an unknown value, run() must degrade
    honestly rather than crash or pretend to shield."""
    monkeypatch.setattr(sandbox, "platform_mechanism", lambda: "bogus")
    cfg = {"BAIZE_SANDBOX_ENABLED": "1", "BAIZE_WORKSPACE_DIR": str(tmp_path)}
    res = run("echo ok", cwd=str(tmp_path), timeout=30, cfg=cfg)
    assert res.degraded is True
    assert res.mechanism == "logical-only"
    assert "ok" in res.stdout
