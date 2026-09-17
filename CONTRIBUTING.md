# Contributing to Baize Agent

Thanks for your interest in Baize (白泽) — a zero-dependency, honesty-first
engineering agent runtime.

## Principles (please respect)

1. **Stdlib-only runtime.** The `baize/` package must stay pure Python standard
   library with **no third-party runtime dependencies**. New capabilities that
   need system interfaces (MCP, OS sandbox, hooks) belong in **optional
   adapter layers that default to OFF** and never pollute the white-box core.
2. **NO FAKE DONE.** Every "done" must be backed by physical evidence and an
   independent verifier. Do not report success you cannot prove. When in doubt,
   fail closed.
3. **Honesty over features.** We would rather be a trustworthy base than a
   feature-parity clone of commercial agents. Prefer depth and provability.

## Development setup

The runtime needs only Python ≥ 3.10 (tested on 3.13). No install step for the
core. For tests, use an isolated virtualenv:

```bash
python -m venv .venv
.venv/Scripts/pip install pytest        # Windows
.venv/bin/pip install pytest            # macOS / Linux
.venv/Scripts/python -m pytest tests/ -q
```

Or simply `make test` (uses `python`).

## Before opening a PR

- `python -m baize.cli doctor` passes (real environment gate).
- `pytest tests/` is green and coverage stays at or above the floor in
  `config.TEST_COVERAGE_THRESHOLD` (85). `make gate` enforces it, and CI reads the
  same config value. **This gate is currently RED** - measured coverage is 77.4%,
  so the repo does not yet meet its own floor. Closing that ~8 point gap is the
  work; editing the number down is not.
- New tools are primitives registered with a JSON schema; avoid baking
  features into the core loop.
- Keep changes small and reviewable; describe the "why" in the PR.
- `make truth` passes — see below.
- `make hygiene` passes — see below.

## Never hand-type the version or the test count

`baize/__init__.py` holds the **only** version literals in the repository:

```python
__version__  = "37.0.0"
__codename__ = "Prometheus"
```

Every other appearance — README titles, the shields.io badges, the compare-table
header, `AGENT.md`, the QUICKSTART/USAGE_GUIDE docs, `baize.manifest.json` and
`pyproject.toml` — is derived from those two lines by `scripts/sync_truth.py`.
The test badge is likewise **measured** by running the suite, never typed.

To cut a release, edit the two literals and run:

```bash
python scripts/sync_truth.py     # rewrites every derived surface
make truth                       # verifies no drift (CI runs this too)
```

`make truth` fails on any drift, so a stale `V36.0.0 Titan` title or a test badge
that disagrees with the suite breaks the build instead of shipping. Historical
version references (for example the `V26.0.0` / `V33.0.0` rows in the README
branch table) are explicitly protected and are never rewritten.

## .gitignore does not untrack anything

`.gitignore` only affects *untracked* files. Adding a path to it does **not**
remove it from the index — which is how 78 `__pycache__` blobs, 31
`persistence/` runtime files and 21 probe scripts stayed committed for months
while `.gitignore` listed those very paths.

To drop something that is already tracked, keep the file on disk and remove it
from the index:

```bash
git rm -r --cached <path>     # runtime state you still want locally
git rm <path>                 # one-off scratch that is worthless to others
```

`make hygiene` (`scripts/check_hygiene.py`) scans the index for tracked junk and
fails CI if any is found.

## Reporting issues

Open an issue describing the environment, the command run, and the observed vs
expected behavior. Include the `Baize Doctor Report` output when relevant.
