#!/usr/bin/env python
"""Honest coverage gate for the Baize engine.

Reads the measured coverage TOTAL from a coverage.py data file and compares it
against the threshold declared in ``baize.config`` (``TEST_COVERAGE_THRESHOLD``).
Using the config as the single source of truth means the documented promise and
the enforced number can never silently drift apart - no paper gate, no fake
green (NO FAKE DONE).

Usage:
    python scripts/coverage_gate.py [data_file]

``data_file`` defaults to ``.coverage`` (coverage.py's default). Exit codes:
    0  coverage >= threshold            (gate passed)
    1  coverage <  threshold            (gate FAILED)
    2  no coverage data file found      (cannot verify)
"""
from __future__ import annotations

import sys
from pathlib import Path

import coverage


def main(argv: list[str]) -> int:
    data_file = argv[1] if len(argv) > 1 else ".coverage"
    if not Path(data_file).exists():
        print(f"COVERAGE GATE ERROR: no data file at {data_file!r}",
              file=sys.stderr)
        return 2

    try:
        from baize.config import load_config
        threshold = int(load_config().get("TEST_COVERAGE_THRESHOLD", 85))
    except Exception as exc:  # fall back to a safe default if config breaks
        print(f"COVERAGE GATE WARN: could not read config ({exc}); "
              f"using threshold 85", file=sys.stderr)
        threshold = 85

    cov = coverage.Coverage(data_file=data_file)
    cov.load()
    total = cov.report()  # prints the per-module table and returns TOTAL %

    if total < threshold:
        print(f"COVERAGE GATE FAILED: {total:.1f}% < {threshold}% "
              f"(declared TEST_COVERAGE_THRESHOLD)")
        return 1
    print(f"COVERAGE GATE PASSED: {total:.1f}% >= {threshold}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
