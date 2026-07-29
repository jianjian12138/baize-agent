"""Real tests for the environment doctor - real dirs, real probes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.doctor import format_report, run_checks  # noqa: E402


def cfg_for(tmp_path: Path, libs: str = "") -> dict:
    persistence = tmp_path / "persistence"
    projects = tmp_path / "projects"
    assets = tmp_path / "assets"
    for d in (persistence, projects, assets):
        d.mkdir(parents=True, exist_ok=True)
    return {
        "BAIZE_PERSISTENCE_DIR": str(persistence),
        "BAIZE_PROJECTS_DIR": str(projects),
        "BAIZE_ASSETS_DIR": str(assets),
        "SKILL_LIBRARY_PATHS": libs,
    }


def test_all_required_pass_with_valid_dirs(tmp_path):
    report = run_checks(cfg_for(tmp_path))
    assert report.passed, format_report(report)


def test_missing_dir_fails(tmp_path):
    cfg = cfg_for(tmp_path)
    cfg["BAIZE_PROJECTS_DIR"] = str(tmp_path / "does-not-exist")
    report = run_checks(cfg)
    assert not report.passed
    failing = [r.name for r in report.results if r.required and not r.ok]
    assert "dir BAIZE_PROJECTS_DIR" in failing


def test_configured_but_missing_skill_library_fails(tmp_path):
    cfg = cfg_for(tmp_path, libs=str(tmp_path / "ghost-lib"))
    report = run_checks(cfg)
    assert not report.passed


def test_existing_skill_library_passes(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    cfg = cfg_for(tmp_path, libs=str(lib))
    report = run_checks(cfg)
    assert report.passed, format_report(report)


def test_empty_library_config_is_warning_not_failure(tmp_path):
    report = run_checks(cfg_for(tmp_path, libs=""))
    assert report.passed
    warn = [r for r in report.results if r.name == "skill libraries"]
    assert len(warn) == 1 and not warn[0].required


def test_format_report_contains_pass_fail_warn(tmp_path):
    cfg = cfg_for(tmp_path, libs=str(tmp_path / "ghost-lib"))
    report = run_checks(cfg)
    text = format_report(report)
    assert "PASS" in text
    assert "FAIL" in text
    assert "RESULT:" in text


def test_format_report_passed_shows_passed(tmp_path):
    report = run_checks(cfg_for(tmp_path))
    text = format_report(report)
    assert "RESULT: PASSED" in text


def test_format_report_failed_shows_failed(tmp_path):
    cfg = cfg_for(tmp_path)
    cfg["BAIZE_PROJECTS_DIR"] = str(tmp_path / "no-exist")
    report = run_checks(cfg)
    text = format_report(report)
    assert "RESULT: FAILED" in text
