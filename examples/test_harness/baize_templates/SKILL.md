---
name: project-test-harness
description: Mandatory deterministic Test Harness verification gate for this repository.
---
# Deterministic Test Harness Verification Gate

Before declaring any bug fix, refactor, or feature complete:
1. Run `python3 <path-to-harness>/runner.py --config <your-harness.config.json> --suite all --json` (or call MCP tool `run_harness`).
2. Confirm `exit_code == 0` and `failed == 0`.
3. Never mock away core business invariants (database conservation, idempotency, concurrency guards) to make tests pass.
4. When a scenario fails, inspect `.artifacts/latest_report.json` (`failures`, `transcript`, `server_log_tail`), fix root cause minimally, and re-run until green.
