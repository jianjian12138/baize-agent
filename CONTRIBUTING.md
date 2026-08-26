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
- `pytest tests/` is green and coverage stays ≥ 85% (see
  `config.TEST_COVERAGE_THRESHOLD`).
- New tools are primitives registered with a JSON schema; avoid baking
  features into the core loop.
- Keep changes small and reviewable; describe the "why" in the PR.

## Reporting issues

Open an issue describing the environment, the command run, and the observed vs
expected behavior. Include the `Baize Doctor Report` output when relevant.
