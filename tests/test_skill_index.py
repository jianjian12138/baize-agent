"""Tests for V23 skill-index governance: best-copy dedup + autonomous create."""
from __future__ import annotations

import json

from baize.skill_index import (_dedup, audit_index, build_index, create_skill,
                               safe_name)


def test_safe_name_slugifies():
    assert safe_name("My Skill!") == "my-skill"
    assert safe_name("foo/bar baz") == "foo-bar-baz"
    assert safe_name("") == "unnamed"


def test_dedup_keeps_most_complete_copy():
    """V23.1: a built-in copy missing its description must NOT shadow a
    complete external copy (the V22 'first occurrence wins' bug)."""
    skills = [
        {"name": "Foo", "description": "", "path": "/a/foo",
         "source": "local:assets/skills"},
        {"name": "Foo", "description": "does the foo thing", "path": "/b/foo",
         "source": "user:user_skills"},
        {"name": "Bar", "description": "single copy", "path": "/c/bar",
         "source": "local:assets/skills"},
    ]
    unique, dropped, groups = _dedup(skills)
    assert len(unique) == 2
    foo = next(s for s in unique if s["name"] == "Foo")
    assert foo["source"] == "user:user_skills"
    assert len(dropped) == 1
    assert groups[0]["name"] == "Foo"
    assert groups[0]["kept"] == "user:user_skills"


def test_create_skill_writes_and_indexes(tmp_path):
    cfg = {
        "BAIZE_USER_SKILLS_DIR": str(tmp_path / "user_skills"),
        "BAIZE_INDEX_FILE": str(tmp_path / "persistence" / "skill_index.json"),
        "BAIZE_ASSETS_DIR": str(tmp_path / "assets"),
        "SKILL_LIBRARY_PATHS": "",
    }
    sf = create_skill("My Skill!", "does X", "body text",
                      domain="dev", level="1", cfg=cfg)
    assert sf.is_file()
    assert sf.parent.name == "my-skill"
    text = sf.read_text(encoding="utf-8")
    assert "name: my-skill" in text
    assert "domain: dev" in text
    assert "origin: agent" in text
    data = json.loads((tmp_path / "persistence" / "skill_index.json")
                      .read_text(encoding="utf-8"))
    assert any(s["name"] == "my-skill" and s["source"] == "user:user_skills"
               for s in data["skills"])


def test_audit_reports_missing_and_duplicates(tmp_path, monkeypatch):
    cfg = {
        "BAIZE_USER_SKILLS_DIR": str(tmp_path / "user_skills"),
        "BAIZE_INDEX_FILE": str(tmp_path / "persistence" / "skill_index.json"),
        "BAIZE_ASSETS_DIR": str(tmp_path / "assets"),
        "SKILL_LIBRARY_PATHS": str(tmp_path / "ext"),
    }
    # built-in copy missing description
    (tmp_path / "assets" / "skills" / "dup").mkdir(parents=True)
    (tmp_path / "assets" / "skills" / "dup" / "SKILL.md").write_text(
        "# Dup\nno frontmatter body\n", encoding="utf-8")
    # external complete copy (should win)
    (tmp_path / "ext" / "dup").mkdir(parents=True)
    (tmp_path / "ext" / "dup" / "SKILL.md").write_text(
        "---\nname: dup\ndescription: complete copy\n---\n", encoding="utf-8")
    build_index(cfg)
    rep = audit_index(cfg)
    assert rep["count"] == 1
    assert rep["duplicates_deduped"] == 1
    assert any(m["name"] == "dup" for m in rep["missing_description"]) is False
    assert any(g["name"] == "dup" for g in rep["duplicate_groups"])
