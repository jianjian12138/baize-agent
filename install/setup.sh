#!/usr/bin/env bash
# Baize Agent — Unix/macOS installer (wraps the cross-platform bootstrap.py).
# Also works under Windows Git Bash.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY=python
fi

exec "$PY" install/bootstrap.py "$@"
