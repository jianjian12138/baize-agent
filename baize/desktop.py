"""Baize Agent Native Desktop Launcher (V33.0.0).

Launches the Baize Desktop Studio in a dedicated standalone application window.
Zero third-party dependencies required.

Execution Hierarchy:
1. If `pywebview` is installed -> launches native PyWebView window.
2. If Edge/Chrome is available -> launches Edge/Chrome in standalone App Mode (`--app=http://127.0.0.1:8787`).
3. Fallback -> launches in default browser.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from .config import load_config
from .serve import serve

__all__ = ["launch_desktop"]


def _is_server_alive(host: str, port: int) -> bool:
    try:
        url = f"http://{host}:{port}/health"
        with urllib.request.urlopen(url, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def _find_browser_app_binary() -> str | None:
    """Find Microsoft Edge or Google Chrome for standalone app mode."""
    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    elif sys.platform.startswith("linux"):
        for name in ("google-chrome", "microsoft-edge", "chromium-browser", "chromium"):
            import shutil
            found = shutil.which(name)
            if found:
                return found
    return None


def launch_desktop(host: str = "127.0.0.1", port: int = 8787) -> int:
    """Launch the Baize Desktop Studio."""
    cfg = load_config()
    host = cfg.get("BAIZE_SERVE_HOST", host)
    port = int(cfg.get("BAIZE_SERVE_PORT", port))
    target_url = f"http://{host}:{port}"

    # 1. Start App Server in background if not already active
    if not _is_server_alive(host, port):
        print(f"[Desktop] 启动白泽后端微服务: {target_url} ...")
        t = threading.Thread(target=serve, kwargs={"host": host, "port": port}, daemon=True)
        t.start()
        for _ in range(30):
            if _is_server_alive(host, port):
                break
            time.sleep(0.1)

    print(f"[Desktop] 白泽桌面工作台就绪: {target_url}")

    # 2. Try pywebview
    try:
        import webview
        print("[Desktop] 唤起原生 PyWebView 桌面窗口...")
        webview.create_window(
            title=f"Baize Agent Studio · 白泽桌面工作台",
            url=target_url,
            width=1280,
            height=820,
            min_size=(960, 600),
            background_color="#090a0f",
        )
        webview.start()
        return 0
    except ImportError:
        pass

    # 3. Try Chrome/Edge Standalone App Window Mode
    app_bin = _find_browser_app_binary()
    if app_bin:
        print(f"[Desktop] 唤起独立沉浸式桌面客户端窗口 (App Mode)...")
        app_flags = [
            app_bin,
            f"--app={target_url}",
            "--window-size=1280,820",
            f"--user-data-dir={Path(cfg['BAIZE_PERSISTENCE_DIR']) / 'desktop_profile'}",
        ]
        try:
            proc = subprocess.Popen(app_flags)
            proc.wait()
            return 0
        except Exception as exc:
            print(f"[Desktop] App Mode 启动异常: {exc}")

    # 4. Fallback to default browser
    print(f"[Desktop] 在默认浏览器中开启桌面工作台: {target_url}")
    webbrowser.open(target_url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Desktop] 桌面服务已退出。")
    return 0


if __name__ == "__main__":
    sys.exit(launch_desktop())
