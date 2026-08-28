#!/usr/bin/env bash
# Baize Agent — One-Command Remote/Local Installer (Linux / macOS / WSL)
# Usage: curl -fsSL https://raw.githubusercontent.com/jianjian12138/baize-agent/main/install/install.sh | bash
set -euo pipefail

echo -e "\033[36m"
echo "  ██████╗  █████╗ ██╗███████╗███████╗"
echo "  ██╔══██╗██╔══██╗██║╚══███╔╝██╔════╝"
echo "  ██████╔╝███████║██║  ███╔╝ █████╗  "
echo "  ██╔══██╗██╔══██╗██║ ███╔╝  ██╔══╝  "
echo "  ██████╔╝██║  ██║██║███████╗███████╗"
echo "  ╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝"
echo "  Baize Agent Autonomous Engine — Installer"
echo -e "\033[0m"

# Locate Python 3.10+
PY_BIN=""
for cmd in python3 python py; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; then
            PY_BIN="$cmd"
            break
        fi
    fi
done

if [ -z "$PY_BIN" ]; then
    echo -e "\033[31m[ERROR] Python 3.10 or newer is required.\033[0m"
    echo "Please install Python 3.10+ (via apt/brew/dnf) and retry."
    exit 1
fi

echo -e "\033[32m✓ Found compatible Python: $("$PY_BIN" --version)\033[0m"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/bootstrap.py" ]; then
    ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
    cd "$ROOT_DIR"
    "$PY_BIN" install/bootstrap.py "$@"
else
    TARGET_DIR="${BAIZE_HOME:-$HOME/.baize-agent}"
    echo "Deploying Baize Agent to $TARGET_DIR..."
    if command -v git >/dev/null 2>&1; then
        if [ -d "$TARGET_DIR" ]; then
            cd "$TARGET_DIR" && git pull --ff-only
        else
            git clone --depth=1 https://github.com/jianjian12138/baize-agent.git "$TARGET_DIR"
        fi
    else
        mkdir -p "$TARGET_DIR"
        curl -fsSL https://github.com/jianjian12138/baize-agent/archive/refs/heads/main.tar.gz | tar -xz -C "$TARGET_DIR" --strip-components=1
    fi
    cd "$TARGET_DIR"
    "$PY_BIN" install/bootstrap.py "$@"
fi
