"""F6 coverage expansion: the desktop launcher (``baize/desktop.py``).

``desktop.py`` measured 19% - almost nothing was exercised, because the module's
whole job is to spawn windows and block forever. That is not a reason to leave
it unmeasured: the launcher decides *which* of four fallbacks the user gets, and
a broken fallback chain means ``baize desktop`` appears to do nothing.

The tests below drive each rung of that ladder with the side effects stubbed at
the boundary (``webview``, ``subprocess.Popen``, ``webbrowser.open``,
``urllib.request.urlopen``) and the ladder's own decision logic running for
real. The final "wait forever" loop is entered and then interrupted, which is
exactly what happens when a user closes the window.

Honesty note: nothing here launches a browser, spawns a real window or opens a
socket. What is verified is the *selection logic* and the user-facing message
for each branch - not that a window appears.
"""
from __future__ import annotations

import sys
import types

import pytest

import baize.desktop as desktop_mod


@pytest.fixture()
def cfg(monkeypatch, tmp_path):
    values = {
        "BAIZE_SERVE_HOST": "127.0.0.1",
        "BAIZE_SERVE_PORT": 8787,
        "BAIZE_PERSISTENCE_DIR": str(tmp_path / "persistence"),
    }
    monkeypatch.setattr(desktop_mod, "load_config", lambda *a, **k: dict(values))
    return values


# ---------------------------------------------------------------------------
# _is_server_alive
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_server_is_alive_on_a_200(monkeypatch):
    seen = {}

    def fake_urlopen(url, timeout=None):
        seen["url"] = url
        return _Resp(200)

    monkeypatch.setattr(desktop_mod.urllib.request, "urlopen", fake_urlopen)
    assert desktop_mod._is_server_alive("127.0.0.1", 8787) is True
    assert seen["url"] == "http://127.0.0.1:8787/health"


def test_server_is_not_alive_on_a_non_200(monkeypatch):
    monkeypatch.setattr(desktop_mod.urllib.request, "urlopen", lambda url, timeout=None: _Resp(503))
    assert desktop_mod._is_server_alive("127.0.0.1", 8787) is False


def test_server_is_not_alive_when_the_connection_fails(monkeypatch):
    def boom(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(desktop_mod.urllib.request, "urlopen", boom)
    assert desktop_mod._is_server_alive("127.0.0.1", 8787) is False


# ---------------------------------------------------------------------------
# _find_browser_app_binary
# ---------------------------------------------------------------------------

def test_no_browser_is_found_on_windows_when_none_of_the_paths_exist(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop_mod.os.path, "isfile", lambda path: False)
    assert desktop_mod._find_browser_app_binary() is None


def test_a_windows_browser_is_found(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop_mod.os.path, "isfile", lambda path: path.endswith("msedge.exe"))
    found = desktop_mod._find_browser_app_binary()
    assert found is not None and found.endswith("msedge.exe")


def test_no_browser_is_found_on_macos_when_none_of_the_paths_exist(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(desktop_mod.os.path, "isfile", lambda path: False)
    assert desktop_mod._find_browser_app_binary() is None


def test_a_macos_browser_is_found(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(desktop_mod.os.path, "isfile", lambda path: "Chrome" in path)
    assert desktop_mod._find_browser_app_binary().endswith("Google Chrome")


def test_no_browser_is_found_on_linux_when_which_returns_nothing(monkeypatch):
    import shutil
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert desktop_mod._find_browser_app_binary() is None


def test_a_linux_browser_is_found_via_which(monkeypatch):
    import shutil

    def which(name):
        return "/usr/bin/chromium-browser" if name == "chromium-browser" else None

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", which)
    assert desktop_mod._find_browser_app_binary() == "/usr/bin/chromium-browser"


def test_an_unknown_platform_yields_no_browser(monkeypatch):
    monkeypatch.setattr(sys, "platform", "aix")
    assert desktop_mod._find_browser_app_binary() is None


# ---------------------------------------------------------------------------
# launch_desktop - rung 1: an already-running server
# ---------------------------------------------------------------------------

def test_launch_uses_pywebview_when_it_is_installed(monkeypatch, cfg, capsys):
    calls = {}
    fake = types.ModuleType("webview")
    fake.create_window = lambda **kw: calls.update(kw)
    fake.start = lambda: calls.update(started=True)
    monkeypatch.setitem(sys.modules, "webview", fake)

    monkeypatch.setattr(desktop_mod, "_is_server_alive", lambda host, port: True)

    assert desktop_mod.launch_desktop() == 0
    assert calls["started"] is True
    assert calls["url"] == "http://127.0.0.1:8787"
    assert calls["width"] == 1280
    assert "PyWebView" in capsys.readouterr().out


def test_launch_prefers_the_configured_host_and_port(monkeypatch, cfg):
    cfg["BAIZE_SERVE_HOST"] = "0.0.0.0"
    cfg["BAIZE_SERVE_PORT"] = 9999
    calls = {}
    fake = types.ModuleType("webview")
    fake.create_window = lambda **kw: calls.update(kw)
    fake.start = lambda: None
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(desktop_mod, "_is_server_alive", lambda host, port: True)

    desktop_mod.launch_desktop()
    assert calls["url"] == "http://0.0.0.0:9999"


# ---------------------------------------------------------------------------
# launch_desktop - rung 2: start the backend ourselves
# ---------------------------------------------------------------------------

def test_launch_starts_the_backend_when_nothing_is_listening(monkeypatch, cfg, capsys):
    # `webview` present but the child raises ImportError is not reachable; force
    # the ImportError branch the way a machine without pywebview would.
    monkeypatch.setitem(sys.modules, "webview", None)

    states = iter([False, True])
    monkeypatch.setattr(desktop_mod, "_is_server_alive",
                        lambda host, port: next(states, True))
    started = {}
    monkeypatch.setattr(desktop_mod, "serve", lambda **kw: started.update(kw))
    monkeypatch.setattr(desktop_mod, "_find_browser_app_binary", lambda: None)
    monkeypatch.setattr(desktop_mod.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(desktop_mod.time, "sleep", _sleep_then_interrupt(1))

    assert desktop_mod.launch_desktop(port=8123) == 0
    assert started == {"host": "127.0.0.1", "port": 8787}
    out = capsys.readouterr().out
    assert "启动白泽后端微服务" in out
    assert "桌面工作台就绪" in out
    assert "桌面服务已退出" in out


def _sleep_then_interrupt(allow: int):
    """Stub for ``time.sleep`` that only interrupts the final keep-open loop.

    ``launch_desktop`` sleeps in two places: a short readiness poll while the
    backend boots, and the unbounded ``while True`` that keeps the process
    alive. Interrupting the first one would abort the launch instead of testing
    it, so the first ``allow`` calls are accepted and the next one raises -
    which is what a user closing the window does.
    """
    state = {"calls": 0}

    def sleep(_seconds=0):
        state["calls"] += 1
        if state["calls"] > allow:
            raise KeyboardInterrupt

    return sleep


# ---------------------------------------------------------------------------
# launch_desktop - rung 3: standalone app window
# ---------------------------------------------------------------------------

def test_launch_uses_app_mode_when_a_browser_is_available(monkeypatch, cfg, capsys):
    monkeypatch.setitem(sys.modules, "webview", None)
    monkeypatch.setattr(desktop_mod, "_is_server_alive", lambda host, port: True)
    monkeypatch.setattr(desktop_mod, "_find_browser_app_binary", lambda: "/bin/edge")

    spawned = {}

    class _Proc:
        def wait(self):
            spawned["waited"] = True
            return 0

    def fake_popen(flags):
        spawned["flags"] = flags
        return _Proc()

    monkeypatch.setattr(desktop_mod.subprocess, "Popen", fake_popen)
    opened = []
    monkeypatch.setattr(desktop_mod.webbrowser, "open", lambda url: opened.append(url))

    assert desktop_mod.launch_desktop() == 0
    assert spawned["waited"] is True
    assert spawned["flags"][0] == "/bin/edge"
    assert "--app=http://127.0.0.1:8787" in spawned["flags"]
    assert any(flag.startswith("--user-data-dir=") for flag in spawned["flags"])
    assert opened == [], "app mode must not also open a browser tab"
    assert "App Mode" in capsys.readouterr().out


def test_launch_falls_back_to_the_browser_when_app_mode_fails(monkeypatch, cfg, capsys):
    monkeypatch.setitem(sys.modules, "webview", None)
    monkeypatch.setattr(desktop_mod, "_is_server_alive", lambda host, port: True)
    monkeypatch.setattr(desktop_mod, "_find_browser_app_binary", lambda: "/bin/edge")

    def boom(flags):
        raise OSError("cannot spawn")

    monkeypatch.setattr(desktop_mod.subprocess, "Popen", boom)
    opened = []
    monkeypatch.setattr(desktop_mod.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(desktop_mod.time, "sleep", _sleep_then_interrupt(0))

    assert desktop_mod.launch_desktop() == 0
    assert opened == ["http://127.0.0.1:8787"]
    out = capsys.readouterr().out
    assert "App Mode 启动异常" in out
    assert "在默认浏览器中开启" in out


def test_launch_falls_back_to_the_browser_without_any_app_binary(monkeypatch, cfg, capsys):
    monkeypatch.setitem(sys.modules, "webview", None)
    monkeypatch.setattr(desktop_mod, "_is_server_alive", lambda host, port: True)
    monkeypatch.setattr(desktop_mod, "_find_browser_app_binary", lambda: None)
    opened = []
    monkeypatch.setattr(desktop_mod.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(desktop_mod.time, "sleep", _sleep_then_interrupt(0))

    assert desktop_mod.launch_desktop() == 0
    assert opened == ["http://127.0.0.1:8787"]
