"""Tests for ``scripts/coverage_gate.py`` - the honest coverage gate.

The gate carries a history of "two sources of truth" bugs, each of which made it
report a number that belonged to something other than the run being checked.
The tests below pin the resolution order and the attribution line.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "coverage_gate", ROOT / "scripts" / "coverage_gate.py"
)
coverage_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coverage_gate)


def test_explicit_argument_wins():
    assert coverage_gate.resolve_data_file(
        ["gate.py", "custom.dat"], {"COVERAGE_FILE": "from-env.dat"}
    ) == Path("custom.dat")


def test_coverage_file_env_is_honoured():
    """The bug this pins: `coverage run` honours COVERAGE_FILE, so the gate must
    too - otherwise it measures a stale `.coverage` left by an earlier run."""
    assert coverage_gate.resolve_data_file(
        ["gate.py"], {"COVERAGE_FILE": "D:/tmp/run-1234"}
    ) == Path("D:/tmp/run-1234")


def test_defaults_to_dot_coverage():
    assert coverage_gate.resolve_data_file(["gate.py"], {}) == Path(".coverage")


def test_empty_env_falls_back_to_default():
    assert coverage_gate.resolve_data_file(
        ["gate.py"], {"COVERAGE_FILE": ""}
    ) == Path(".coverage")


def test_threshold_comes_from_config():
    """The threshold is declared once, in baize.config."""
    from baize.config import load_config

    assert coverage_gate.read_threshold() == int(
        load_config()["TEST_COVERAGE_THRESHOLD"])


def test_missing_data_file_is_exit_2_not_a_pass(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("COVERAGE_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert coverage_gate.main(["gate.py"]) == 2
    assert "no data file" in capsys.readouterr().err


def test_gate_reports_which_file_it_read(tmp_path, capsys):
    """A number must always be attributable to a run. Build a real (tiny)
    coverage data file so the report has something to measure."""
    import coverage

    src = tmp_path / "mod_under_test.py"
    src.write_text("def f():\n    return 1\n", encoding="utf-8")
    data_file = tmp_path / "cov.dat"

    cov = coverage.Coverage(data_file=str(data_file), source=[str(tmp_path)])
    cov.start()
    import importlib.util as iu

    spec = iu.spec_from_file_location("mod_under_test", src)
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.f()
    cov.stop()
    cov.save()

    assert data_file.exists()
    rc = coverage_gate.main(["gate.py", str(data_file)])
    out = capsys.readouterr().out
    assert "data file :" in out
    assert str(data_file) in out
    # It really measured: either PASSED or FAILED, never the cannot-verify path.
    assert rc in (0, 1)
    assert "COVERAGE GATE" in out
