# Baize Agent - developer convenience targets.
# Works on Unix/macOS and Windows (via Git Bash / WSL).
PY ?= python

.PHONY: install doctor test index clean

install:
	$(PY) install/bootstrap.py

doctor:
	$(PY) -m baize.cli doctor

test:
	$(PY) -m pytest tests/ -q

index:
	$(PY) -m baize.cli index build

clean:
	$(PY) -m baize.cli memory clear 2>/dev/null || true
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov
