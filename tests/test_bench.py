"""Tests for #76 - local end-to-end benchmarks + honest public coverage map.

The bench harness runs REAL subsystems with REAL assertions (NO FAKE DONE);
here we assert the harness itself is green and the public map is honest.
"""
from __future__ import annotations

import re

from baize import bench
from baize import bench_public


def test_all_benchmarks_pass():
    rep = bench.run_all()
    assert rep["total"] >= 12, f"expected >=12 cases, got {rep['total']}"
    assert rep["all_ok"], (
        f"bench regression: {[c['name'] for c in rep['cases'] if not c['ok']]}")
    names = {c["name"] for c in rep["cases"]}
    # the P1-P3 end-to-end cases are present
    for required in ("subagent_isolation", "skill_self_evolve",
                     "automation_fire", "session_fork_compress",
                     "multi_provider_parse", "plan_mode_block",
                     "manifest_gate", "memory_compress", "public_benchmarks"):
        assert required in names, f"missing bench case: {required}"


def test_public_coverage_is_honest():
    rep = bench_public.coverage_report()
    assert rep["benchmarks"], "no benchmark entries"
    for b in rep["benchmarks"]:
        assert b["status"] in bench_public.VALID_STATUSES, f"bad status: {b}"
    # we must NOT claim a 'passed' score on a harness we do not run
    assert any(b["status"] == "not_run" for b in rep["benchmarks"])
    assert "does not execute" in rep["honest_note"]


def test_bench_module_zero_third_party_imports():
    src = open(__import__("baize.bench", fromlist=["x"]).__file__,
               encoding="utf-8").read()
    forbidden = r"^\s*(import|from)\s+(requests|httpx|yaml|tiktoken|litellm|"
    forbidden += r"anthropic|openai)\b"
    assert re.findall(forbidden, src, re.M) == [], "forbidden import"
