#!/usr/bin/env python3
"""Baize Agent — one-command installer (cross-platform, zero dependencies).

Mirrors the one-line install experience of hermes-agent / pi-agent, but runs
locally with no third-party packages (Python standard library only).

Usage (any OS):
    python install/bootstrap.py
    python install/bootstrap.py --test          # also run the test suite
    python install/bootstrap.py --skip-doctor  # skip the environment gate
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
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


def check_python() -> None:
    cur = sys.version_info[:2]
    if cur < MIN_PY:
        print(
            f"ERROR: Python >= {MIN_PY[0]}.{MIN_PY[1]} required, "
            f"found {cur[0]}.{cur[1]}",
            file=sys.stderr,
        )
        sys.exit(1)
    log(f"Python {sys.version.split()[0]} OK")


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
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    print(BANNER)
    print(f"Installing from: {root}\n")

    step(1, "Checking Python")
    check_python()

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
