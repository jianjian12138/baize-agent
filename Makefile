# Baize Agent - developer convenience targets.
# Works on Unix/macOS and Windows (via Git Bash / WSL).
PY ?= python

.PHONY: install doctor test index clean cov gate chat serve repl truth hygiene honesty deps

install:
	$(PY) install/bootstrap.py

chat:
	$(PY) -m baize chat

repl: chat

serve:
	$(PY) -m baize serve

doctor:
	$(PY) -m baize.cli doctor

test:
	$(PY) -m pytest tests/ -q

# Coverage run + honest gate. The threshold is read from baize.config
# (TEST_COVERAGE_THRESHOLD) by scripts/coverage_gate.py - single source of
# truth, so the gate can never drift from the documented promise.
cov:
	$(PY) -m coverage run -m pytest tests/ -q
	$(PY) scripts/coverage_gate.py

# Alias so CI can simply call `make gate`. Cheap checks first so a broken
# promise fails in seconds instead of after a full coverage run.
gate: deps truth hygiene honesty cov

# The engine's headline promise: `pip install baize-agent` pulls no third-party
# packages, so `import baize` works on a bare interpreter.
# scripts/check_zero_deps.py fails ONLY on module-level third-party imports,
# because only those execute on `import baize`. Guarded optional imports
# (try/except ImportError, function-body, TYPE_CHECKING) are reported, not
# failed - the previous all-or-nothing version was red from V24 to V37.
deps:
	$(PY) scripts/check_zero_deps.py

# Version + test count single source of truth. baize/__init__.py holds the only
# version literals; scripts/sync_truth.py owns every derived surface (README
# titles and badges, manifest, docs) and this target fails on any drift.
# Run `python scripts/sync_truth.py` (no --check) to regenerate them.
truth:
	$(PY) scripts/sync_truth.py --check

# .gitignore does not apply retroactively: a path that is already tracked stays
# tracked forever. This target inspects the index for junk the ignore rules were
# meant to exclude (pycache, persistence/, probe scripts, ...).
hygiene:
	$(PY) scripts/check_hygiene.py
	$(PY) scripts/check_arch_tree.py
	$(PY) scripts/check_module_attrs.py

# NO FAKE DONE at the API layer. Seven routes used to answer HTTP 200 with a
# hardcoded success payload ("PR #43 opened", "4/4 checks green") while doing no
# work. This target starts the real server and probes every declared stub route,
# so it fails on behaviour rather than on source-code shape.
honesty:
	$(PY) scripts/check_endpoint_honesty.py

index:
	$(PY) -m baize.cli index build

clean:
	$(PY) -m baize.cli memory clear 2>/dev/null || true
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov
