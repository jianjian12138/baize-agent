# ⚡ Baize Agent — 60-Second Quickstart Guide

Welcome to **Baize Agent (V36.0.0 Titan)** — The zero-dependency, white-box autonomous AI software engineer built in pure Python standard library.

---

## 🎯 Get Up & Running in 3 Steps

### Step 1: Health Diagnostic Gate
Run the built-in system doctor to verify environment readiness:
```bash
python -m baize doctor
```
> **Note**: Doctor automatically verifies Python runtime (>=3.10), PowerShell execution policy, and UTF-8 pipeline encoding.

---

### Step 2: Run Autonomous Tasks (CLI & REPL)
Dispatch an autonomous coding or refactoring task:
```bash
# Autonomous one-shot task execution
python -m baize run "write robust unit tests for authentication logic and ensure 100% pass"

# Continuous interactive REPL session (supports @file injection, /fork, /rewind)
python -m baize repl
```

---

### Step 3: Launch Dark-Mode Universal Desktop Studio
```bash
# Start local API & Studio Web interface (Port 8787)
python -m baize serve --port 8787
```
Open **`http://127.0.0.1:8787`** in your browser, or double click `install/baize-desktop.bat` on Windows to launch the native standalone Studio app with all 11 core modules!

---

## ⚙️ Model Provider Setup (`.env`)

Create a `.env` file in repository root (or copy `.env.example`):
```ini
# Model Configuration (DeepSeek / OpenAI / Claude / Local Ollama)
BAIZE_MODEL_PROVIDER=openai_compatible
BAIZE_MODEL_BASE_URL=https://api.deepseek.com
BAIZE_MODEL_NAME=deepseek-chat
BAIZE_MODEL_API_KEY=sk-your-api-key-here

# Windows Native PowerShell Optimization (Active by default)
BAIZE_WINDOWS_POWERSHELL_FIRST=true
```

---

## 🔌 Advanced IDE & Ecosystem Integrations

### 1. VS Code & Cursor Sidecar Extension
- Load `extensions/vscode` into VS Code / Cursor;
- Press **`Ctrl+Shift+B`** to open Baize Studio sidecar;
- Select any code snippet and press **`Ctrl+K`** for inline AST-guided refactoring!

### 2. Anthropic MCP Protocol Client
- Exposes standard JSON-RPC 2.0 MCP tools for SQLite, GitHub, and custom tools via `/api/mcp/tools`.
