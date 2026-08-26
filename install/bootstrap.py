#!/usr/bin/env python3
"""Baize Agent — one-command installer (cross-platform, zero dependencies).

Mirrors the one-line install experience of hermes-agent / pi-agent, but runs
locally with no third-party packages (Python standard library only).

If a suitable Python (>= 3.10) is not already present, the installer will try
to provision one automatically (winget / Homebrew / apt-dnf-apk / python.org),
then restart itself with the new interpreter — so a bare machine can deploy
with a single command, just like hermes does.

Usage (any OS):
    python install/bootstrap.py
    python install/bootstrap.py --test            # also run the test suite
    python install/bootstrap.py --skip-doctor    # skip the environment gate
    python install/bootstrap.py --no-auto-python # never auto-install Python
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MIN_PY = (3, 10)

BANNER = r"""
   ___    __  __    _    ___  ___
  / __|  |  \/  |  / \  |__ \|__ \   Baize Agent
 | |__   | |\/| | / _ \   / /   / /   autonomous agent runtime — V19
 |___/   |_|  |_|/_/ \_\ |___| |___/   one-command installer
"""


def log(msg: str) -> None:
    print(f"  \033[36m•\033[0m {msg}")


def step(n: int, msg: str) -> None:
    print(f"\n\033[1m[{n}/4] {msg}\033[0m")


def _read_py_version(py: str) -> tuple[int, int] | None:
    """Return (major, minor) for the given interpreter, or None if unusable."""
    try:
        proc = subprocess.run(
            [py, "--version"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    txt = (proc.stdout + proc.stderr).strip()
    m = re.search(r"(\d+)\.(\d+)\.\d+", txt) or re.search(r"(\d+)\.(\d+)", txt)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _locate_python(min_py: tuple[int, int]) -> str | None:
    """Find an interpreter >= min_py already on this machine."""
    if sys.version_info[:2] >= min_py:
        return sys.executable
    candidates: list[str] = []
    if sys.platform == "win32":
        candidates.append("py")
    candidates += ["python3.12", "python3.11", "python3.10", "python3", "python"]
    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        exe = shutil.which(c)
        if not exe:
            continue
        ver = _read_py_version(exe)
        if ver and ver >= min_py:
            return exe
    return None


def _re_exec(py: str) -> None:
    """Replace the current process with the given interpreter running this script."""
    log(f"restarting with {py} …")
    os.execv(py, [py, os.path.abspath(__file__), *sys.argv[1:]])


def _auto_install_python(no_auto: bool) -> str | None:
    """Attempt to install a suitable Python. Returns its path, or None on failure."""
    if no_auto:
        return None
    if sys.platform == "win32":
        return _win_install_python()
    if sys.platform == "darwin":
        return _mac_install_python()
    return _linux_install_python()


def _win_install_python() -> str | None:
    local = os.environ.get("LOCALAPPDATA", "")
    target = Path(local) / "Programs" / "Python" / "Python312" / "python.exe"
    if target.exists():
        return str(target)
    # 1) winget
    if shutil.which("winget"):
        log("installing Python 3.12 via winget … (may take a minute)")
        rc = subprocess.call([
            "winget", "install", "Python.Python.3.12", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
            "--scope", "user",
        ])
        if rc == 0 and target.exists():
            return str(target)
    # 2) official installer
    url = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    tmp = Path(tempfile.gettempdir()) / "python-3.12.7-amd64.exe"
    if not tmp.exists():
        log("downloading Python installer from python.org …")
        try:
            import urllib.request
            urllib.request.urlretrieve(url, tmp)  # noqa: S310
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: download failed ({exc})")
            return None
    log("running Python installer (silent) …")
    rc = subprocess.call(
        [str(tmp), "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_pip=1"]
    )
    if rc == 0 and target.exists():
        return str(target)
    return None


def _mac_install_python() -> str | None:
    if shutil.which("brew"):
        log("installing Python 3.12 via Homebrew …")
        subprocess.call(["brew", "install", "python@3.12"])
        exe = shutil.which("python3.12") or shutil.which("python3")
        if exe and _read_py_version(exe) >= MIN_PY:
            return exe
    # fallback: official pkg
    url = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-macos11.pkg"
    tmp = Path(tempfile.gettempdir()) / "python-3.12.7-macos11.pkg"
    if not tmp.exists():
        log("downloading Python installer from python.org …")
        try:
            import urllib.request
            urllib.request.urlretrieve(url, tmp)  # noqa: S310
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: download failed ({exc})")
            return None
    log("installing Python pkg (may prompt for password) …")
    subprocess.call(["sudo", "installer", "-pkg", str(tmp), "-target", "/"])
    exe = shutil.which("python3.12") or shutil.which("python3")
    if exe and _read_py_version(exe) >= MIN_PY:
        return exe
    return None


def _linux_install_python() -> str | None:
    log("attempting to install Python via system package manager …")
    steps = [
        ("apt-get", [["sudo", "apt-get", "update"],
                     ["sudo", "apt-get", "install", "-y", "python3.12", "python3.12-venv"]]),
        ("dnf", [["sudo", "dnf", "install", "-y", "python3.12"]]),
        ("apk", [["sudo", "apk", "add", "python3"]]),
    ]
    for marker, cmds in steps:
        if shutil.which(marker):
            for c in cmds:
                subprocess.call(c)
            found = shutil.which("python3.12") or shutil.which("python3")
            if found and _read_py_version(found) >= MIN_PY:
                return found
    return None


def ensure_python(no_auto: bool) -> None:
    """Guarantee a usable Python (>= MIN_PY), auto-installing + restarting if needed."""
    if sys.version_info[:2] >= MIN_PY:
        log(f"Python {sys.version.split()[0]} OK")
        return
    found = _locate_python(MIN_PY)
    if found and found != sys.executable:
        _re_exec(found)
    installed = _auto_install_python(no_auto)
    if installed:
        _re_exec(installed)
    print(
        f"ERROR: Python >= {MIN_PY[0]}.{MIN_PY[1]} is required but could not be "
        "installed automatically.\n"
        "  Windows: winget install Python.Python.3.12 --silent\n"
        "  macOS:   brew install python@3.12\n"
        "  Linux:   sudo apt-get install python3.12\n"
        "Then re-run: python install/bootstrap.py",
        file=sys.stderr,
    )
    sys.exit(1)


def ensure_env(root: Path) -> None:
    example = root / ".env.example"
    target = root / ".env"
    if target.exists():
        log(".env already exists — skipped")
        return
    if example.exists():
        shutil.copyfile(example, target)
        log("created .env from .env.example (edit it to set BAIZE_MODEL_*)")
    else:
        log("WARNING: .env.example not found — skipped .env creation")


def run(cmd: list[str], cwd: Path) -> int:
    return subprocess.call(cmd, cwd=str(cwd))


def main() -> int:
    ap = argparse.ArgumentParser(description="Baize Agent installer")
    ap.add_argument("--test", action="store_true", help="run test suite after install")
    ap.add_argument(
        "--skip-doctor", action="store_true", help="skip the environment gate"
    )
    ap.add_argument(
        "--no-auto-python", action="store_true",
        help="never auto-install Python if missing (fail instead)",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    print(BANNER)
    print(f"Installing from: {root}\n")

    step(1, "Ensuring Python >= 3.10")
    ensure_python(args.no_auto_python)

    step(2, "Preparing .env")
    ensure_env(root)

    step(3, "Running environment gate (baize doctor)")
    if args.skip_doctor:
        log("skipped via --skip-doctor")
    else:
        rc = run([sys.executable, "-m", "baize.cli", "doctor"], cwd=root)
        if rc != 0:
            print(
                "\nWARNING: `baize doctor` reported issues. "
                "Resolve them before running agents."
            )

    step(4, "Finalizing")
    if args.test:
        log("running tests…")
        run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=root)
    else:
        log("done (run `make test` or `python -m pytest tests/ -q` to verify)")

    print("\n\033[1m[DONE]\033[0m Baize Agent is ready.")
    print("  Help:        python -m baize --help")
    print("  Environment: python -m baize doctor")
    print('  Run agent:   python -m baize run "<your goal>"')
    print('  Team mode:   python -m baize team "<your goal>"')
    print("  Docs:        cat START-HERE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
