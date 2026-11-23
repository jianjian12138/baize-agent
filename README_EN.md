<div align="center">

# 🏛️ Baize Agent — V46.0.0 Sovereign

**Zero Runtime Dependencies · Physical Verification Gates (`NO FAKE DONE`) · 8-Domain, 58-Module Industrial Pure-Python Autonomous Engineering Runtime**

[![Version](https://img.shields.io/badge/version-V46.0.0--Sovereign-orange?style=flat-square)](baize/__init__.py)
[![Tests](https://img.shields.io/badge/tests-1344%2F1344%20passed%20(100%25)-brightgreen?style=flat-square)](tests/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20third--party%20(stdlib%20only)-blue?style=flat-square)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

[**中文文档**](README.md) · [**5-Min Start**](docs/START-HERE.md) · [**Architecture**](docs/architecture.md) · [**Usage Guide**](docs/USAGE_GUIDE.md) · [**Benchmarks**](docs/benchmarks.md)

</div>

---

## Why Baize Agent?

**Baize Agent V46 Sovereign** delivers an industrial-grade autonomous coding runtime with **zero third-party runtime dependencies (100% Python 3.10+ stdlib)**:

- **Accelerated Core Loop & Atomic Git Rollback**: End-to-end live token streaming (REPL & HTTP SSE), concurrent read-only tool batch execution (mutating calls strictly serialized), and non-invasive Git tree checkpoints (`GitCheckpointManager`) with automatic or one-command rollback (`baize rollback`).
- **Tiered Isolation Sandbox**: Local hardened default (static guardrails + Landlock/Seatbelt + POSIX `rlimit` CPU/FD caps + secret env scrubbing) plus one-flag Docker container isolation (`BAIZE_SANDBOX_MODE=docker|auto` with `--network=none`, `--pids-limit`, and fail-closed strict mode).
- **Zero-Dependency LSP & Compiler Diagnostics Bridge**: Pure-stdlib stdio JSON-RPC 2.0 LSP client + instant compiler/syntax adapters (`baize diagnose`), automatically triggered after `write_file`/`patch_file` edits to catch errors on the same turn.
- **Real Multi-File Coding Evaluation Harness**: Curated isolated coding tasks (`baize eval`) supporting deterministic `oracle` verification in CI and `live` LLM evaluation with persistent JSONL scorecards and regression diffing (`--compare`).
- **Productionized Persistent Async Server**: SQLite WAL persistent job queue (`POST /api/jobs`, crash recovery, cooperative cancel, SSE streaming), sliding-window rate limiting (`429`), real `/team/dag` planning/execution, and checkpoint-protected `/api/git/apply_hunk`.
- **NO FAKE DONE Gates & Static Codebase Intelligence**: Polyglot symbol graph (PageRank), incremental SQLite cache, hierarchical repo maps, and blast-radius/test-impact analysis.

---

## Quick Start

```bash
git clone https://github.com/jianjian12138/baize-agent.git
cd baize-agent
cp .env.example .env            # configure OpenAI / Anthropic / DeepSeek / Ollama API key
python -m baize doctor          # inspect runtime, config, and tiered sandbox posture
```

### Core CLI Workflows

```bash
python -m baize                                   # launch live-streaming interactive REPL
python -m baize run "add edge-case unit tests for auth and verify"
python -m baize team "refactor payment state machine and run regression tests"
python -m baize diagnose baize/core/agent.py      # run compiler / stdio LSP diagnostics
python -m baize eval --mode oracle                # run multi-file coding eval suite (--mode live for real LLM)
python -m baize rollback --list                   # inspect or roll back Git transactional checkpoints
python -m baize impact baize/core/agent.py --run  # compute impacted tests and run them
python -m baize serve --port 8765                 # start HTTP/SSE server with SQLite persistent job queue
python -m baize mcp                               # run standard JSON-RPC 2.0 MCP server (stdio)
```

---

## Architecture (8 Domains · 58 Modules)

| Package | Modules | Responsibility |
| :--- | :---: | :--- |
| **`baize/core/`** | 7 | Streaming + parallel-read Agent loop, multi-provider LLM client (keep-alive pool + prompt cache + streaming tool-call accumulation), config/schema/logging, sessions, autonomy, plugins |
| **`baize/orchestration/`** | 7 | Director→Executor→Verifier DAG, contracts/invariants/Ralph loop, role teams & sub-agents, System-1 intent router/guard, hooks, append-only run ledger, automations |
| **`baize/execution/`** | 7 | 17 default tools + Tool SDK, tiered sandbox (Landlock/Seatbelt + `rlimit` + env scrub + Docker), Git atomic checkpoints, proc timeouts, PowerShell pool, frontend verifier |
| **`baize/codebase/`** | 7 | Zero-dep stdio LSP/compiler diagnostics bridge, polyglot symbol graph (PageRank), incremental SQLite cache, hierarchical repo maps & AST slicer, blast-radius/test-impact, workspace search, recon |
| **`baize/knowledge/`** | 6 | Episodic/semantic/team memory, knowledge graph, TF-IDF vector index & RAG, skill index/catalog/Hermes harvester, skill runner, doc crawler |
| **`baize/governance/`** | 6 | NO FAKE DONE verification gates & manifest validator, 15-case kernel benchmark suite, real multi-file coding eval harness, AST mutation & chaos injection, `doctor`, Prometheus metrics |
| **`baize/interfaces/`** | 11 | 32-subcommand CLI, streaming REPL, modular HTTP/SSE server with SQLite WAL persistent job queue (`server/` 6 modules), Desktop Studio, terminal/web UI |
| **`baize/ext/`** | 7 | Unified MCP client/server/dispatcher (`mcp/` 5 modules), chat channel adapters, lifecycle metrics plugin |

The module layout is verified against the filesystem on every commit by `scripts/gates/check_arch_tree.py` and documented in [`docs/architecture.md`](docs/architecture.md).

---

## Verification Gates

```bash
python scripts/gates/check_zero_deps.py         # assert 0 third-party runtime imports in baize/
python scripts/gates/check_hygiene.py           # assert clean tracked tree & valid imports
python scripts/gates/check_arch_tree.py         # assert docs/architecture.md matches baize/ 1:1
python scripts/gates/check_module_attrs.py      # statically verify imported module attributes exist
python scripts/gates/check_endpoint_honesty.py  # assert zero fabricated payloads, zero 501 stubs & honest 410 retirements
python scripts/gates/sync_truth.py --check      # verify version labels, badges, and doc counts
python -m baize manifest validate baize.manifest.json
python -m baize bench                           # run 15 built-in kernel benchmarks
python -m baize eval --mode oracle              # verify multi-file coding evaluation harness
pytest tests/                                   # run full test suite
```

---

## Historical Tags

Earlier single-file and legacy snapshots remain accessible as read-only Git tags: `v26.0.0-legacy`, `v33.0.0-legacy`.

## Contributing & License

See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) for contribution guidelines and gate requirements. Licensed under the [MIT License](LICENSE).
