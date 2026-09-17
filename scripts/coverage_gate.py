#!/usr/bin/env python
"""Honest coverage gate for the Baize engine.

Reads the measured coverage TOTAL from a coverage.py data file and compares it
against the threshold declared in ``baize.config`` (``TEST_COVERAGE_THRESHOLD``).
Using the config as the single source of truth means the documented promise and
the enforced number can never silently drift apart - no paper gate, no fake
green (NO FAKE DONE).

Bugs this script used to carry, all of the "two sources of truth" family:

* CI re-implemented the check inline against its own hardcoded ``80``, while
  ``Makefile`` claimed the config was authoritative. CI now calls this script.
* Running ``python scripts/coverage_gate.py`` puts ``scripts/`` - not the repo
  root - on ``sys.path``, so ``import baize`` failed and the gate silently fell
  back to a hardcoded ``85``. The config value was never actually consulted.
  The repo root is now added to ``sys.path`` explicitly.
* The data file was resolved as ``argv[1] or ".coverage"``, ignoring
  ``COVERAGE_FILE``. Since ``coverage run`` *does* honour ``COVERAGE_FILE``, a
  run that redirected its data elsewhere left a stale ``.coverage`` behind and
  the gate measured the stale file. Observed in practice: a run that redirected
  its data reported 68.7% while the run's own data file held 78.1%. The gate now
  resolves ``argv[1]`` > ``COVERAGE_FILE`` > ``.coverage``, and always prints
  which file it read and when that file was written, so a number can never be
  attributed to the wrong run again.

Usage:
    python scripts/coverage_gate.py [data_file]

(The XML report is deliberately NOT accepted: ``coverage.xml``'s ``line-rate``
counts statements only, while the data file reports statements and branches
together, so the two disagree by several points on the same run.)

Exit codes:
    0  coverage >= threshold            (gate passed)
    1  coverage <  threshold            (gate FAILED)
    2  cannot verify                    (no data file, or config unreadable)
"""
from __future__ import annotations

import os
import sys
import time
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


def resolve_data_file(argv: list[str], env: dict | None = None) -> Path:
    """Explicit argument > ``COVERAGE_FILE`` > ``.coverage``.

    Honouring ``COVERAGE_FILE`` is not a nicety: ``coverage run`` honours it, so
    a gate that does not will happily measure a different, older file than the
    run it is supposed to be checking.
    """
    if len(argv) > 1:
        return Path(argv[1])
    env = os.environ if env is None else env
    from_env = env.get("COVERAGE_FILE")
    return Path(from_env) if from_env else Path(".coverage")


def main(argv: list[str]) -> int:
    data_file = resolve_data_file(argv)
    if not data_file.exists():
        print(f"COVERAGE GATE ERROR: no data file at {str(data_file)!r}",
              file=sys.stderr)
        return 2

    # Always name the file and its age: the failure mode this guards against is
    # a confidently wrong number read from a stale file.
    written = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(data_file.stat().st_mtime))
    print(f"data file : {data_file}  (written {written})")

    threshold = read_threshold()

    import coverage

    cov = coverage.Coverage(data_file=str(data_file))
    cov.load()
    total = cov.report()  # prints the per-module table and returns TOTAL %

    if total < threshold:
        print(f"COVERAGE GATE FAILED: {total:.1f}% < {threshold}% (declared TEST_COVERAGE_THRESHOLD)")
        return 1
    print(f"COVERAGE GATE PASSED: {total:.1f}% >= {threshold}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
