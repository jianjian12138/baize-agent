#!/usr/bin/env python
"""Measure the real compression ratio of ``slice_code_context`` on this tree.

Why this exists
---------------
Three places stated a token-saving number and no two agreed:

    README.md / README_EN.md     50% ~ 70%
    baize/context_slicer.py      50%-75%   (module docstring)
    baize/intelligence_radar.py  Token 节省 70%

None carried a measurement, and ``README.md`` applies the opposite standard one
table row above: its mutation-testing row reads "击杀率由探针实测得出，不是固定
100%". A number in a feature table is read as a measurement whether or not it is
one, so the honest options are to measure it or to drop it.

The function already computes a ratio per call (``compression_ratio`` in the
returned dict), so the range can be measured instead of asserted.

What it prints
--------------
A distribution, not a headline number. A "typical" figure that hides the spread
would recreate the defect in a new place: the real lower bound is 0%, and a
reader told "50%-75%" would be wrong about roughly one slice in thirteen.

Usage
-----
    python scripts/measure_slicing.py            # human-readable
    python scripts/measure_slicing.py --json     # machine-readable

Exit codes: 0 measured, 2 could not measure.
"""
from __future__ import annotations

import argparse
import ast
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from baize.context_slicer import slice_code_context  # noqa: E402

#: Package directory to slice. Scoped to the package rather than the whole
#: repo: the claim is about the tool's behaviour on production code, and the
#: test suite is not what a user slices.
PACKAGE_DIR = "baize"

#: How many top-level symbols to sample per module. Slicing every symbol of
#: every module is O(n^2) in module size and adds nothing to the distribution.
SYMBOLS_PER_MODULE = 6


def tracked_python_files() -> list[str]:
    """Tracked ``.py`` files under the package, via git so untracked scratch is ignored.

    Filtered in Python rather than with a git pathspec: ``baize/**/*.py`` is not
    "everything under baize" - git's ``**`` requires at least one directory, so
    that pathspec silently skipped every top-level module and measured 12 files
    instead of 78.
    """
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise SystemExit(f"MEASURE ERROR: git ls-files failed:\n{out.stderr}")
    prefix = PACKAGE_DIR + "/"
    return [
        line.strip() for line in out.stdout.splitlines()
        if line.strip().startswith(prefix) and line.strip().endswith(".py")
    ]


def top_level_symbols(source: str) -> list[str]:
    """Names of top-level defs/classes, or ``[]`` when the file does not parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def measure() -> dict[str, object]:
    """Slice every sampled symbol and return the distribution plus the raw rows."""
    rows: list[dict[str, object]] = []
    for rel in tracked_python_files():
        path = ROOT / rel
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for name in top_level_symbols(source)[:SYMBOLS_PER_MODULE]:
            try:
                result = slice_code_context(source, name)
            except Exception as exc:  # noqa: BLE001 - a crash here is data, not a stop
                rows.append({"file": rel, "symbol": name, "ratio": None,
                             "error": f"{type(exc).__name__}: {exc}"})
                continue
            raw = str(result.get("compression_ratio", ""))
            try:
                ratio = float(raw.rstrip("%"))
            except ValueError:
                ratio = None
            rows.append({
                "file": rel,
                "symbol": name,
                "ratio": ratio,
                "pruned": result.get("pruned_functions_count", 0),
            })

    ratios = [r["ratio"] for r in rows if r["ratio"] is not None]
    if not ratios:
        raise SystemExit("MEASURE ERROR: no slice produced a usable ratio")

    ordered = sorted(ratios)
    quartiles = statistics.quantiles(ordered, n=4)
    buckets = {"0%": 0, "0-25%": 0, "25-50%": 0, "50-75%": 0, "75-100%": 0}
    for value in ordered:
        if value == 0:
            buckets["0%"] += 1
        elif value < 25:
            buckets["0-25%"] += 1
        elif value < 50:
            buckets["25-50%"] += 1
        elif value < 75:
            buckets["50-75%"] += 1
        else:
            buckets["75-100%"] += 1

    return {
        "modules": len({r["file"] for r in rows}),
        "slices": len(rows),
        "usable": len(ratios),
        "min": ordered[0],
        "p25": quartiles[0],
        "median": statistics.median(ordered),
        "p75": quartiles[2],
        "max": ordered[-1],
        "mean": statistics.mean(ordered),
        "buckets": buckets,
        "rows": rows,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="emit the full result as JSON instead of a table")
    args = ap.parse_args(argv[1:])

    result = measure()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"modules scanned : {result['modules']}")
    print(f"slices measured : {result['slices']} (usable ratios: {result['usable']})")
    print()
    print(f"min    : {result['min']:.1f}%")
    print(f"p25    : {result['p25']:.1f}%")
    print(f"median : {result['median']:.1f}%")
    print(f"p75    : {result['p75']:.1f}%")
    print(f"max    : {result['max']:.1f}%")
    print(f"mean   : {result['mean']:.1f}%")
    print()
    usable = int(result["usable"])
    for label, count in result["buckets"].items():  # type: ignore[union-attr]
        print(f"  {label:>8}: {count:4}  ({count / usable * 100:.1f}%)")
    print()
    print("A fixed range cannot describe this: the lower bound is 0%, so any")
    print("claim of the form 'cuts tokens by X%' is false for some input.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
