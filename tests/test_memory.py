"""Real tests for persistence memory - real files, real reads."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.memory import log_event, recall, remember, stats  # noqa: E402


def cfg_for(tmp_path: Path) -> dict:
    return {"BAIZE_PERSISTENCE_DIR": str(tmp_path / "persistence")}


def test_log_event_appends_jsonl(tmp_path):
    cfg = cfg_for(tmp_path)
    path = log_event("fixed router prefix bug", ["bugfix"], cfg)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    log_event("second entry", None, cfg)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_remember_and_recall(tmp_path):
    cfg = cfg_for(tmp_path)
    remember("coupon discountType=2 means rate 0-1", cfg)
    log_event("investigated pagination structure", ["api"], cfg)

    hits = recall("coupon", cfg)
    assert len(hits) == 1
    assert hits[0]["source"] == "notes.md"

    hits = recall("pagination", cfg)
    assert len(hits) == 1
    assert hits[0]["source"].endswith(".jsonl")

    assert recall("never-written-keyword", cfg) == []


def test_stats_counts_real_content(tmp_path):
    cfg = cfg_for(tmp_path)
    remember("note one", cfg)
    remember("note two", cfg)
    log_event("event one", None, cfg)
    s = stats(cfg)
    assert s["notes"] == 2
    assert s["events"] == 1
    assert s["log_files"] == 1


def test_recall_multi_keyword_and(tmp_path):
    """Multiple keywords use AND: all must appear in the record."""
    cfg = cfg_for(tmp_path)
    log_event("fixed router prefix bug in vue", ["bugfix"], cfg)
    log_event("router guard added for auth", ["feature"], cfg)

    # both "router" and "bug" must match -> only first record
    hits = recall("router bug", cfg)
    assert len(hits) == 1
    assert "prefix" in hits[0]["text"]

    # "router" and "auth" -> only second record
    hits = recall("router auth", cfg)
    assert len(hits) == 1
    assert "guard" in hits[0]["text"]

    # "router" and "nonexistent" -> no match
    assert recall("router nonexistent-word-xyz", cfg) == []


def test_recall_tags_filter(tmp_path):
    """Tag filter only returns records with matching tags."""
    cfg = cfg_for(tmp_path)
    log_event("deployed to staging", ["deploy", "staging"], cfg)
    log_event("fixed login bug", ["bugfix"], cfg)
    remember("a note without tags", cfg)

    # filter by "deploy" tag -> only first log record
    hits = recall("", cfg, tags=["deploy"])
    assert len(hits) == 1
    assert "staging" in hits[0]["text"]

    # filter by "bugfix" tag -> only second log record
    hits = recall("", cfg, tags=["bugfix"])
    assert len(hits) == 1
    assert "login" in hits[0]["text"]

    # notes.md excluded when tag filter active (no tags field)
    hits = recall("note", cfg, tags=["deploy"])
    assert len(hits) == 0
