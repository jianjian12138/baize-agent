# Baize-Agent Architecture Overview

## 1. System Philosophy (Pi + Hermes + Unix)

Baize-Agent is an autonomous agent engineering runtime built on three pillars:
1. **Zero Runtime Dependencies**: 100% pure Python standard library (no PyYAML, no requests, no external vector DBs).
2. **Deterministic Governance & Verification (NO FAKE DONE)**: Progress is recorded in append-only JSONL ledgers with machine checks; claims without verified evidence are strictly rejected.
3. **Progressive Disclosure & Thin Layers**: Modular subpackages with progressive discovery and swappable components.

---

## 2. Modular Package Structure

```text
baize/                              # 0 flat modules + __main__.py, 9 domain subpackages
├── core/                           # agent loop, LLM adapters, config, sessions, autonomy
│   ├── agent.py  autonomy.py  component.py  config.py  config_schema.py  http_pool.py
│   ├── llm.py  logging_setup.py  modes.py  plugin.py  prompt_cache.py  sessions.py
├── orchestration/                  # Director->Executor->Verifier DAG, contracts, hooks, ledger
│   ├── automations.py  contract.py  hooks.py  intent_router.py  invariants_anchor.py
│   ├── orchestrator.py  ralph.py  run_ledger.py  subagent.py  system1.py  team.py
├── execution/                      # tool registry, sandboxes, proc timeouts, PowerShell/Docker
│   ├── agent_rules.py  browser_verify.py  docker_sandbox.py  interactive_detector.py
│   ├── powershell.py  proc.py  safe_exec.py  sandbox.py  tool_sdk.py  tools.py
├── codebase/                       # 6 orthogonal static code intelligence modules
│   ├── arch_cache.py               # incremental mtime/size-keyed SQLite architecture cache
│   ├── impact.py                   # blast-radius analyzer, test-impact matrix & unified change-impact
│   ├── recon.py                    # pre-flight prior-art & skill library reconnaissance
│   ├── repo_map.py                 # flat + L0/L1/L2 hierarchical repo maps & AST context slicer
│   ├── symbol_graph.py             # AST/regex symbol graph, PageRank, canonical SKIP_DIRS/SUPPORTED_EXTS
│   └── workspace_search.py         # zero-dependency workspace grep & glob search
├── knowledge/                      # layered memory, semantic RAG, vectors, skills catalog & index
│   ├── doc_crawler.py  graph.py  memory.py  rag.py  skill_harvester.py
│   ├── skill_index.py  skill_runner.py  skills_catalog.py  team_memory.py  vector.py
├── governance/                     # NO FAKE DONE gate, manifest, doctor, bench, chaos, mutation, obs
│   ├── bench.py  bench_public.py  chaos.py  doctor.py  gate.py
│   ├── manifest.py  mutation.py  observability.py  perf.py
├── interfaces/                     # CLI, REPL, HTTP/SSE server, dashboard, desktop UI, setup wizard
│   ├── cli.py  dashboard.py  desktop.py  desktop_ui.py  repl.py
│   ├── serve.py  session_viewer.py  setup_wizard.py  ui.py
│   └── server/                     # decomposed HTTP server subpackage
│       ├── routes_get.py           # GET routes (/health, /api/workspace/search, /api/perf/profile, etc.)
│       ├── routes_post.py          # POST dispatch & handlers
│       ├── security.py             # fail-closed auth, CORS allowlist, path guards
│       └── streaming.py            # real-time SSE streaming for /run/stream
├── ext/                            # optional extensions (lazily loaded, fail-closed)
│   ├── channels.py                 # conversation adapter interface for chat channels
│   ├── mcp/                        # unified Model Context Protocol client/server/dispatcher
│   │   ├── client.py  component.py  dispatcher.py  server.py  transport.py
│   ├── plugins/
│   │   └── metrics.py              # feeds observability counters from lifecycle hooks
│   └── providers/                  # reserved - currently empty
└── labs/                           # experimental engines (causal, forking, replay, swarm, radar)
    ├── adversarial.py  byzantine.py  causal.py  forking.py  intelligence_radar.py
    └── replay.py  snapshot.py  swarm.py  synthesizer.py  tool_market.py
```

> This tree is generated from the filesystem by
> `scripts/gates/check_arch_tree.py`, which runs in the `hygiene` gate. An earlier
> revision of this section described a `core/ orchestration/ tooling/
> knowledge/ security/ server/` layout that did not exist: 39 of the 43 files it
> listed were really flat modules directly under `baize/`. The check exists so
> that cannot happen again.

---

## 3. Data Flow & Execution Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as CLI / API Server
    participant Orch as Orchestrator
    participant Ledger as RunLedger
    participant Exec as Executor Agent
    participant Gate as Machine Checks
    participant Verif as Verifier Agent
    participant Mem as Memory / Skills

    User->>CLI: baize run "Goal" (or team / resume)
    CLI->>Orch: orchestrate(goal)
    Orch->>Ledger: record plan_created
    loop Each Atomic Task
        Orch->>Ledger: task_claimed & task_started
        Orch->>Exec: execute(subtask, RolePolicy)
        Exec->>Exec: Reason -> Tool -> Observe
        Exec-->>Orch: executor_summary
        Orch->>Gate: run_checks (file_exists, cmd_ok, evidence)
        alt Machine Checks FAIL
            Gate-->>Orch: verdict="fail" (NO FAKE DONE)
        else Machine Checks PASS
            Orch->>Verif: independent verification
            Verif-->>Orch: verdict="pass" / "fail" + evidence
        end
        alt Verified PASS
            Orch->>Ledger: task_verified + evidence
            Orch->>Mem: candidate learning / memory layer
        else Fail & Retries Exhausted
            Orch->>Ledger: task_failed + issues
        end
    end
    Orch->>CLI: OrchestrationResult
    CLI-->>User: Structured Report
```
