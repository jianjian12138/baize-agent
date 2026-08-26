"""Real tests for the manifest gate. No mocks, real files on disk."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.manifest import validate_manifest  # noqa: E402


def write_manifest(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_missing_file_is_error(tmp_path):
    res = validate_manifest(tmp_path / "nope.json")
    assert not res.ok
    assert any("not found" in e for e in res.errors)


def test_invalid_json_is_error(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text("{broken", encoding="utf-8")
    res = validate_manifest(p)
    assert not res.ok
    assert any("invalid JSON" in e for e in res.errors)


def test_done_without_evidence_is_rejected(tmp_path):
    """THE core rule: NO FAKE DONE."""
    p = write_manifest(tmp_path, {
        "project": "x", "version": "1.0.0",
        "phases": [{"id": "P1", "name": "align", "status": "done",
                    "evidence": []}],
    })
    res = validate_manifest(p)
    assert not res.ok
    assert any("NO FAKE DONE" in e for e in res.errors)


def test_done_with_missing_evidence_file_is_rejected(tmp_path):
    p = write_manifest(tmp_path, {
        "project": "x", "version": "1.0.0",
        "phases": [{"id": "P1", "name": "align", "status": "done",
                    "evidence": ["ghost_report.md"]}],
    })
    res = validate_manifest(p)
    assert not res.ok
    assert any("evidence missing" in e for e in res.errors)


def test_done_with_real_evidence_passes(tmp_path):
    (tmp_path / "report.md").write_text("real evidence", encoding="utf-8")
    p = write_manifest(tmp_path, {
        "project": "x", "version": "1.0.0",
        "phases": [
            {"id": "P1", "name": "align", "status": "done",
             "evidence": ["report.md"]},
            {"id": "P2", "name": "build", "status": "in_progress",
             "evidence": []},
        ],
    })
    res = validate_manifest(p)
    assert res.ok, res.errors


def test_invalid_status_rejected(tmp_path):
    p = write_manifest(tmp_path, {
        "project": "x", "version": "1.0.0",
        "phases": [{"id": "P1", "status": "finished!!", "evidence": []}],
    })
    res = validate_manifest(p)
    assert not res.ok


def test_done_after_pending_warns(tmp_path):
    (tmp_path / "ev.md").write_text("e", encoding="utf-8")
    p = write_manifest(tmp_path, {
        "project": "x", "version": "1.0.0",
        "phases": [
            {"id": "P1", "status": "pending", "evidence": []},
            {"id": "P2", "status": "done", "evidence": ["ev.md"]},
        ],
    })
    res = validate_manifest(p)
    assert res.ok  # warning, not error
    assert any("order looks inconsistent" in w for w in res.warnings)
