#!/usr/bin/env python
"""Honest coverage gate for the Baize engine.

Reads the measured coverage TOTAL from a coverage.py data file and compares it
against the threshold declared in ``baize.config`` (``TEST_COVERAGE_THRESHOLD``).
Using the config as the single source of truth means the documented promise and
the enforced number can never silently drift apart - no paper gate, no fake
green (NO FAKE DONE).

Two bugs this script used to carry, both of the "two sources of truth" family:

* CI re-implemented the check inline against its own hardcoded ``80``, while
  ``Makefile`` claimed the config was authoritative. CI now calls this script.
* Running ``python scripts/coverage_gate.py`` puts ``scripts/`` - not the repo
  root - on ``sys.path``, so ``import baize`` failed and the gate silently fell
  back to a hardcoded ``85``. The config value was never actually consulted.
  The repo root is now added to ``sys.path`` explicitly.

Usage:
    python scripts/coverage_gate.py [data_file]

``data_file`` defaults to ``.coverage``, coverage.py's default - which is also
what ``pytest --cov=baize`` writes, so CI and local runs measure the identical
number. (The XML report is deliberately NOT accepted: ``coverage.xml``'s
``line-rate`` counts statements only, while ``.coverage`` reports statements and
branches together, so the two disagree by several points on the same run.)

Exit codes:
    0  coverage >= threshold            (gate passed)
    1  coverage <  threshold            (gate FAILED)
    2  cannot verify                    (no data file, or config unreadable)
"""
from __future__ import annotations

import sys
from pathlib import Path

# `python scripts/coverage_gate.py` puts scripts/ - not the repo root - on
# sys.path, so `import baize` needs the repo root added explicitly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_threshold() -> int:
    """Threshold from baize.config - the one place it is declared.

    Unreadable config is a *cannot verify* condition, not a reason to invent a
    number: reporting a pass against a threshold nobody declared would be a
    paper gate.
    """
    try:
        from baize.config import load_config

        return int(load_config()["TEST_COVERAGE_THRESHOLD"])
    except Exception as exc:
        print(
            f"COVERAGE GATE ERROR: cannot read TEST_COVERAGE_THRESHOLD from "
            f"baize.config ({exc}). Refusing to guess a threshold.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def main(argv: list[str]) -> int:
    data_file = argv[1] if len(argv) > 1 else ".coverage"
    if not Path(data_file).exists():
        print(f"COVERAGE GATE ERROR: no data file at {data_file!r}", file=sys.stderr)
        return 2

    threshold = read_threshold()

    import coverage

    cov = coverage.Coverage(data_file=data_file)
    cov.load()
    total = cov.report()  # prints the per-module table and returns TOTAL %

    if total < threshold:
        print(f"COVERAGE GATE FAILED: {total:.1f}% < {threshold}% (declared TEST_COVERAGE_THRESHOLD)")
        return 1
    print(f"COVERAGE GATE PASSED: {total:.1f}% >= {threshold}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
