"""Public-benchmark honest coverage map (P3-1).

Baize does NOT farm public agent benchmarks (SWE-bench / Terminal-Bench /
AgentBench / WebArena / GPQA) - doing so risks gaming the scoreboard and
violates NO FAKE DONE. Instead each public benchmark is mapped to the
*underlying capability* baize provides, with an honest status:

  - covered : baize implements the capability end-to-end with real assertions
  - partial : capability exists, exercised via internal benchmarks only
  - not_run : the public harness itself is NOT executed by baize

``coverage_report()`` is surfaced by ``baize bench --public`` and the serve
``/bench`` endpoint so reviewers see exactly what is and isn't claimed.
"""
from __future__ import annotations

PUBLIC_BENCHMARKS = [
    {"name": "SWE-bench", "measures": "repo-level code fix from issue+PR",
     "capability": "tool use (bash/read/write) + self-verify", "status": "partial"},
    {"name": "Terminal-Bench", "measures": "shell task completion",
     "capability": "bash sandbox + verifier gate", "status": "partial"},
    {"name": "AgentBench", "measures": "multi-environment agent",
     "capability": "tool registry + orchestrator", "status": "partial"},
    {"name": "WebArena", "measures": "web navigation",
     "capability": "browser tool (external MCP)", "status": "not_run"},
    {"name": "GPQA", "measures": "grad-level QA",
     "capability": "LLM reasoning (model-dependent)", "status": "not_run"},
    {"name": "NO-FAKE-DONE gate", "measures": "honest scoring discipline",
     "capability": "Verifier + manifest + coverage gate", "status": "covered"},
]

VALID_STATUSES = ("covered", "partial", "not_run")


def coverage_report() -> dict:
    counts = {s: 0 for s in VALID_STATUSES}
    for b in PUBLIC_BENCHMARKS:
        if b["status"] in counts:
            counts[b["status"]] += 1
    return {
        "benchmarks": PUBLIC_BENCHMARKS,
        "counts": counts,
        "honest_note": ("baize does not execute public harnesses; "
                        "status reflects capability coverage only, never a "
                        "claimed score on a benchmark it has not run."),
    }
