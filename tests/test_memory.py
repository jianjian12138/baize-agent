"""Real tests for persistence memory - real files, real reads."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.memory import (compress, log_event, recall,  # noqa: E402
                          remember, stats)


def cfg_for(tmp_path: Path) -> dict:
    return {"BAIZE_PERSISTENCE_DIR": str(tmp_path / "persistence")}


def _day_offset(n: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))


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


# ---------------------------------------------------------------------------
# Coverage expansion: compress distillation, blank/malformed line handling,
# recall early-break, and stats without a notes.md file.
# ---------------------------------------------------------------------------

def test_recall_skips_blank_note_lines(tmp_path):
    cfg = cfg_for(tmp_path)
    Path(cfg["BAIZE_PERSISTENCE_DIR"]).mkdir(parents=True, exist_ok=True)
    notes = Path(cfg["BAIZE_PERSISTENCE_DIR"]) / "notes.md"
    notes.write_text(
        "- [2026-01-01] real note about coupon\n\n"
        "- [2026-01-02] second note\n",
        encoding="utf-8")
    hits = recall("coupon", cfg)
    assert len(hits) == 1
    assert "real note" in hits[0]["text"]


def test_recall_skips_malformed_log_lines(tmp_path):
    cfg = cfg_for(tmp_path)
    logf = Path(cfg["BAIZE_PERSISTENCE_DIR"]) / "logs" / "2026-01-01.jsonl"
    logf.parent.mkdir(parents=True, exist_ok=True)
    logf.write_text(
        '{"ts":"x","text":"good entry","tags":[]}\nthis is not json\n',
        encoding="utf-8")
    hits = recall("", cfg)  # empty query returns everything valid
    assert len(hits) == 1
    assert hits[0]["text"] == "good entry"


def test_recall_early_break_on_limit(tmp_path):
    cfg = cfg_for(tmp_path)
    for i in range(10):
        log_event(f"shared keyword entry number {i}", None, cfg)
    hits = recall("shared", cfg, limit=2)
    assert len(hits) == 2  # limit applied


def test_compress_distills_old_logs(tmp_path):
    cfg = cfg_for(tmp_path)
    old_day = _day_offset(5)
    old_log = (Path(cfg["BAIZE_PERSISTENCE_DIR"]) / "logs" /
               f"{old_day}.jsonl")
    old_log.parent.mkdir(parents=True, exist_ok=True)
    old_log.write_text(
        json.dumps({"ts": old_day, "text": "old event alpha",
                    "tags": ["t1", "t2"]}) + "\n",
        encoding="utf-8")
    # a current log that must survive compression
    log_event("current event", ["cur"], cfg)

    res = compress(days=1, cfg=cfg)
    assert res["compressed_files"] == 1
    assert res["events_distilled"] == 1
    assert not old_log.exists()  # old file unlinked

    notes = Path(cfg["BAIZE_PERSISTENCE_DIR"]) / "notes.md"
    assert notes.exists()
    assert "compressed" in notes.read_text(encoding="utf-8")

    s = stats(cfg)
    assert s["log_files"] == 1  # current log remains


def test_stats_without_notes_file(tmp_path):
    cfg = cfg_for(tmp_path)
    log_event("only an event", None, cfg)
    s = stats(cfg)
    assert s["notes"] == 0
    assert s["events"] == 1


def test_compress_default_days_and_malformed(tmp_path):
    cfg = cfg_for(tmp_path)
    # default-days path (days=None -> reads BAIZE_MEMORY_COMPRESS_DAYS)
    res = compress(cfg=cfg)
    assert res["compressed_files"] == 0  # nothing old yet

    # an old log containing only a malformed line: file unlinked, 0 distilled
    old_day = _day_offset(5)
    old_log = (Path(cfg["BAIZE_PERSISTENCE_DIR"]) / "logs" /
               f"{old_day}.jsonl")
    old_log.parent.mkdir(parents=True, exist_ok=True)
    old_log.write_text("this is not json\n", encoding="utf-8")
    res = compress(days=1, cfg=cfg)
    assert res["compressed_files"] == 1
    assert res["events_distilled"] == 0
    assert not old_log.exists()
