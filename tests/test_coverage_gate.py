"""Tests for ``scripts/coverage_gate.py`` - the honest coverage gate.

The gate carries a history of "two sources of truth" bugs, each of which made it
report a number that belonged to something other than the run being checked.
The tests below pin the resolution order, the attribution line, and the
freshness guard: a data file older than the sources it claims to describe must
be a loud "cannot verify", never a quiet pass or fail.

The freshness tests come in pairs on purpose. Each probe has a test proving it
*sees* a stale file (calibration) next to the test proving it refuses one, so a
probe that silently finds nothing cannot be mistaken for a working gate.
"""
from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import pytest

_spec = importlib.util.spec_from_file_location(
    "coverage_gate", ROOT / "scripts" / "coverage_gate.py"
)
coverage_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coverage_gate)


def _real_data_file(tmp_path: Path) -> Path:
    """A genuine (tiny) coverage data file, so the gate has something to measure."""
    coverage = pytest.importorskip("coverage")

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
    return data_file


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def _controlled_root(tmp_path: Path, *, source_age: float = 0.0) -> Path:
    """A tree whose newest source has a *known* age - built, not inherited.

    The freshness rule compares a data file against the newest source of a root.
    A test that hands it *this repository* while aging the data file by a fixed
    number of seconds only reads as "stale" while this repository was edited less
    than that number of seconds ago. Observed with no code change: three tests
    red at 2h14m after the last commit to ``baize/`` (newest source 8031s old),
    all three green again after a ``touch`` on one source file. Build the tree
    instead of inheriting it, and let the tests assert on ``mod.py`` so that
    falling back to the real root cannot pass silently.
    """
    root = tmp_path / "controlled_root"
    (root / "baize").mkdir(parents=True, exist_ok=True)
    src = root / "baize" / "mod.py"
    src.write_text("x = 1\n", encoding="utf-8")
    if source_age:
        _age(src, source_age)
    return root


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
    data_file = _real_data_file(tmp_path)

    assert data_file.exists()
    rc = coverage_gate.main(["gate.py", str(data_file)])
    out = capsys.readouterr().out
    assert "data file :" in out
    assert str(data_file) in out
    # It really measured: either PASSED or FAILED, never the cannot-verify path.
    assert rc in (0, 1)
    assert "COVERAGE GATE" in out


# ------------------------------------------------------- freshness guard
#
# Calibration first: the probe must be able to *see* a stale file. Without this,
# a probe that always answers "fresh" would satisfy every refusal test below by
# accident - the gate would look strict while measuring whatever it was handed.


def test_the_staleness_probe_sees_a_stale_file(tmp_path):
    """Calibration: given a file older than the tree, the probe says so."""
    root = tmp_path / "repo"
    (root / "baize").mkdir(parents=True)
    (root / "baize" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    data_file = tmp_path / "cov.dat"
    data_file.write_bytes(b"stub")
    _age(data_file, 3600)

    reason = coverage_gate.staleness(data_file, root)
    assert reason is not None, "probe failed to notice a 1h-old data file"
    assert "older tree" in reason
    assert "mod.py" in reason


def test_a_data_file_newer_than_the_sources_is_not_stale(tmp_path):
    root = tmp_path / "repo"
    (root / "baize").mkdir(parents=True)
    (root / "baize" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    data_file = tmp_path / "cov.dat"
    data_file.write_bytes(b"stub")
    _age(data_file, -10)  # ten seconds in the future, as coverage's own write is

    assert coverage_gate.staleness(data_file, root) is None


def test_same_second_is_not_treated_as_stale(tmp_path):
    """Coarse clocks make a same-second write normal; refusing it would be a
    false alarm on a perfectly good run."""
    root = tmp_path / "repo"
    (root / "baize").mkdir(parents=True)
    src = root / "baize" / "mod.py"
    src.write_text("x = 1\n", encoding="utf-8")

    data_file = tmp_path / "cov.dat"
    data_file.write_bytes(b"stub")
    stamp = src.stat().st_mtime
    os.utime(data_file, (stamp, stamp))

    assert coverage_gate.staleness(data_file, root) is None


def test_nothing_to_compare_against_does_not_block(tmp_path):
    """An empty tree is "cannot judge", not "stale": a gate must not invent a
    verdict from an absent comparison."""
    empty = tmp_path / "empty"
    empty.mkdir()
    data_file = tmp_path / "cov.dat"
    data_file.write_bytes(b"stub")
    _age(data_file, 3600)

    assert coverage_gate.newest_source_mtime(empty) == 0.0
    assert coverage_gate.staleness(data_file, empty) is None


def test_a_stale_data_file_is_refused_not_measured(tmp_path, capsys, monkeypatch):
    """The bug this pins: a stale file used to be measured against the current
    tree and reported as a confident pass or fail.

    The root is built here on purpose - see
    ``test_a_data_file_newer_than_its_own_tree_is_still_measured`` for what
    happens when this comparison is aimed at the checkout instead.
    """
    monkeypatch.setattr(coverage_gate, "ROOT", _controlled_root(tmp_path))

    data_file = _real_data_file(tmp_path)
    _age(data_file, 3600)

    rc = coverage_gate.main(["gate.py", str(data_file)])
    captured = capsys.readouterr()
    assert rc == 2, "a stale data file must be cannot-verify, not a verdict"
    assert "cannot verify" in captured.err
    assert "mod.py" in captured.err, (
        "the refusal named a file outside the controlled root, so it was not "
        "staleness that was detected")
    # And it must not have printed a verdict it cannot support.
    assert "PASSED" not in captured.out
    assert "FAILED" not in captured.out


def test_allow_stale_measures_the_file_anyway(tmp_path, capsys, monkeypatch):
    """--allow-stale is the caller asserting the file does describe the tree."""
    # Same scenario as the refusal above, so the pair differs only in the flag.
    monkeypatch.setattr(coverage_gate, "ROOT", _controlled_root(tmp_path))

    data_file = _real_data_file(tmp_path)
    _age(data_file, 3600)

    rc = coverage_gate.main(["gate.py", "--allow-stale", str(data_file)])
    out = capsys.readouterr().out
    assert rc in (0, 1), "with the assertion made, the gate must measure"
    assert "not checked" in out


def test_a_fresh_data_file_still_measures(tmp_path, capsys, monkeypatch):
    """The guard must not break the normal path: coverage writes its data after
    reading the sources, so the file is newest and the gate proceeds."""
    monkeypatch.setattr(coverage_gate, "ROOT", _controlled_root(tmp_path))

    data_file = _real_data_file(tmp_path)

    rc = coverage_gate.main(["gate.py", str(data_file)])
    out = capsys.readouterr().out
    assert "freshness : data file is newer than the newest source file" in out
    assert rc in (0, 1)


def test_a_data_file_newer_than_its_own_tree_is_still_measured(
        tmp_path, capsys, monkeypatch):
    """The other half of the rule, in the configuration a real defect drifted into.

    The refusal test above used to compare a 1h-old data file against *this
    repository's* newest source. That premise expires: the comparison only comes
    out "stale" while ``baize/`` or ``tests/`` was edited less than an hour ago.
    Measured, with no code change: three tests red at 2h14m after the last commit
    to ``baize/``, all three green again after a ``touch`` on one source file. The
    probe answered correctly both times - the tests were asking about the
    checkout. So: a data file newer than the newest source of *its own* root must
    be measured. Refusing it here would be a false alarm, and that is exactly the
    state those tests decayed into.
    """
    monkeypatch.setattr(
        coverage_gate, "ROOT", _controlled_root(tmp_path, source_age=3 * 3600))

    data_file = _real_data_file(tmp_path)
    _age(data_file, 3600)

    rc = coverage_gate.main(["gate.py", str(data_file)])
    out = capsys.readouterr().out
    assert rc in (0, 1), (
        "a data file newer than the newest source of its own root must be "
        "measured, not refused")
    assert "is newer than the newest source file" in out


def test_the_freshness_line_does_not_claim_a_check_that_never_ran(
        tmp_path, monkeypatch, capsys):
    """When there is nothing to compare against, the gate must say so rather
    than print the same 'is newer' line it prints after a real comparison."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(coverage_gate, "ROOT", empty)

    data_file = _real_data_file(tmp_path)
    _age(data_file, 3600)

    rc = coverage_gate.main(["gate.py", str(data_file)])
    out = capsys.readouterr().out
    assert rc in (0, 1), "with nothing to compare, the gate must still measure"
    assert "not judged" in out
    assert "is newer than the newest source file" not in out
