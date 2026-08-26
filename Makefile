# Baize Agent - developer convenience targets.
# Works on Unix/macOS and Windows (via Git Bash / WSL).
PY ?= python

.PHONY: install doctor test index clean cov gate

install:
	$(PY) install/bootstrap.py

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

# Alias so CI can simply call `make gate`.
gate: cov

index:
	$(PY) -m baize.cli index build

clean:
	$(PY) -m baize.cli memory clear 2>/dev/null || true
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov
