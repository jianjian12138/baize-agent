<div align="center">

# 🏛️ Baize Agent — V39.0.0 Aegis

**Zero Runtime Dependencies · Physical Verification Gates (`NO FAKE DONE`) · 8-Domain, 53-Module Pure-Python Autonomous Engineering Runtime**

[![Version](https://img.shields.io/badge/version-V39.0.0--Aegis-orange?style=flat-square)](baize/__init__.py)
[![Tests](https://img.shields.io/badge/tests-1265%2F1268%20passed%20(99%25)-yellow?style=flat-square)](tests/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20third--party%20(stdlib%20only)-blue?style=flat-square)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

[**中文文档**](README.md) · [**5-Min Start**](docs/START-HERE.md) · [**Architecture**](docs/architecture.md) · [**Usage Guide**](docs/USAGE_GUIDE.md) · [**Benchmarks**](docs/benchmarks.md)

</div>

---

## Why Baize Agent?

Most agent frameworks pull in dozens of third-party packages and accept an LLM's claim of completion at face value.

**Baize Agent V39 Aegis** is built as a lean, verifiable engineering runtime distilled into **8 domain packages and 53 production modules**:

- **Zero Third-Party Runtime Dependencies (`dependencies = []`)**: 100% Python 3.10+ standard library (pooled HTTP client, SQLite incremental cache, AST symbol graph, TF-IDF vector index, JSON-RPC 2.0 MCP, SSE server), enforced by `scripts/gates/check_zero_deps.py`.
- **NO FAKE DONE Physical Gates**: Every completion claim must be backed by real execution evidence (syntax, tests, manifest hashes, contract checks) recorded in an append-only JSONL `RunLedger`.
- **Fail-Closed Security Posture**: HTTP write endpoints refuse unauthenticated requests by default (`BAIZE_AUTH_TOKEN`), CORS uses an explicit allowlist, shell guardrails block destructive patterns, and unimplemented endpoints return honest `501 Not Implemented`.
- **Static Codebase Intelligence (6 Orthogonal Modules)**: Polyglot AST/regex symbol graph (Python / TS / JS / Go / Rust / Java), PageRank ranking, mtime/size-keyed SQLite cache, L0/L1/L2 repo maps, and blast-radius / test-impact analysis.
- **Controlled Multi-Role Orchestration**: Director → Executor → Verifier DAG with per-role tool/workspace scopes, long-horizon invariants anchoring, session forking, and Hermes trajectory skill distillation.
- **Cross-Platform & Native Windows Execution**: Persistent PowerShell process pool, interactive prompt detection, optional Docker sandbox, and static frontend verification.

---

## Quick Start

### 1. Clone and verify (no `pip install` needed for runtime)

```bash
git clone https://github.com/jianjian12138/baize-agent.git
cd baize-agent
cp .env.example .env            # configure an OpenAI / Anthropic / DeepSeek / Ollama API key
python -m baize doctor          # inspect runtime, config, and workspace health
```

### 2. Core CLI Workflows

```bash
python -m baize                 # launch interactive terminal REPL
python -m baize run "add edge-case unit tests for auth and verify"
python -m baize team "refactor payment state machine and run regression tests"
python -m baize impact baize/core/agent.py --run   # compute impacted tests and run them
python -m baize blast run_gate                      # inspect symbol call blast radius
python -m baize serve --port 8765                   # start HTTP/SSE server & web dashboard
python -m baize mcp                                 # run standard JSON-RPC 2.0 MCP server (stdio)
```

> Optionally install the `baize` console entry point with `pip install -e .`. See [`docs/START-HERE.md`](docs/START-HERE.md) for a 5-minute walkthrough.

---

## Architecture (8 Domains · 53 Modules)

```text
  CLI / REPL / HTTP+SSE / Desktop / MCP          <- baize/interfaces/ & baize/ext/
                      │
                      ▼
  System-1 Guard ──▶ Director -> Executor -> Verifier DAG   <- baize/orchestration/
                      │                    │
         ┌────────────┴───────────┐        └───────────┐
         ▼                        ▼                    ▼
  Core Runtime              Codebase Intel        Execution & Sandbox
  (agent, llm, config,      (symbol_graph,        (tools, sandbox, proc,
   sessions, autonomy)       repo_map, impact,     powershell, docker)
                             arch_cache, search)
         │                        │                    │
         └────────────┬───────────┴────────────────────┘
                      ▼
       Knowledge (memory, graph, rag, skills)  +  Governance (gate, bench, mutation, doctor, obs)
```

| Package | Modules | Responsibility |
| :--- | :---: | :--- |
| **`baize/core/`** | 7 | Agent loop, multi-provider LLM client (HTTP keep-alive pool + prompt cache), config/schema/logging, session persistence, autonomy/modes, plugin & component protocols |
| **`baize/orchestration/`** | 7 | Director→Executor→Verifier DAG, contracts/invariants/Ralph loop, role teams & sub-agents, System-1 intent router/guard, hooks, append-only run ledger, automations |
| **`baize/execution/`** | 6 | 16 built-in tools + agent rules + Tool SDK, fail-closed shell sandbox, timeout & interactive-prompt runner, Windows PowerShell pool, Docker sandbox, frontend verifier |
| **`baize/codebase/`** | 6 | Polyglot symbol graph (PageRank), incremental SQLite architecture cache, hierarchical repo maps & AST slicer, blast-radius & test-impact matrix, zero-dep workspace search, recon |
| **`baize/knowledge/`** | 6 | Episodic/semantic/team memory, knowledge graph, TF-IDF vector index & RAG, skill index/catalog/Hermes harvester, skill runner, doc crawler |
| **`baize/governance/`** | 5 | NO FAKE DONE verification gates & manifest validator, 15-case kernel benchmark suite, AST mutation arena & chaos injection, environment `doctor`, Prometheus metrics & profiler |
| **`baize/interfaces/`** | 9 | 29-subcommand CLI, interactive REPL, modular HTTP/SSE server (`server/` 4 modules), Desktop Studio, terminal/web UI & setup wizard |
| **`baize/ext/`** | 7 | Unified MCP client/server/dispatcher (`mcp/` 5 modules), chat channel adapters, lifecycle metrics plugin |

The complete module layout is verified against the filesystem on every commit by `scripts/gates/check_arch_tree.py` and documented in [`docs/architecture.md`](docs/architecture.md).

---

## Repository Layout

```text
baize-agent/
├── baize/              # Production runtime (8 domain packages, 53 modules, 0 flat clutter)
├── tests/              # 10-domain mirrored test suite (95 test modules)
├── scripts/
│   ├── gates/          # Hard verification gates (zero-deps, hygiene, arch-tree, module-attrs, honesty, truth, coverage)
│   └── tools/          # Developer utilities (slicing benchmark, API connectivity probe)
├── assets/skills/      # 23 bundled structured SKILL.md modules
├── docs/               # Architecture, tutorials, benchmarks, quickstarts, Desktop Studio & protocol docs
├── examples/           # Sample extensions including VS Code companion (examples/vscode/)
├── install/            # Cross-platform bootstrap and desktop launch scripts
├── projects/           # Isolated local project workspaces
├── AGENT.md            # Baize autonomous operating protocol
├── baize.manifest.json # Machine-checked delivery evidence manifest
└── pyproject.toml      # Pure-stdlib package definition (dependencies = [])
```

---

## Verification Gates

Every invariant in this repository is checked by executable gates:

```bash
python scripts/gates/check_zero_deps.py         # assert 0 third-party runtime imports in baize/
python scripts/gates/check_hygiene.py           # assert clean tracked tree & valid imports
python scripts/gates/check_arch_tree.py         # assert docs/architecture.md matches baize/ 1:1
python scripts/gates/check_module_attrs.py      # statically verify imported module attributes exist
python scripts/gates/check_endpoint_honesty.py  # assert zero fabricated success payloads & honest 501 stubs
python scripts/gates/sync_truth.py --check      # verify version labels, badges, and doc counts
python -m baize manifest validate baize.manifest.json
python -m baize bench                           # run 15 built-in kernel benchmarks
pytest tests/                                   # run full test suite
```

---

## Historical Tags

Earlier single-file and legacy snapshots remain accessible as read-only Git tags: `v26.0.0-legacy`, `v33.0.0-legacy`.

## Contributing & License

See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) for contribution guidelines and gate requirements. Licensed under the [MIT License](LICENSE).
