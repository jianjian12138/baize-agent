"""Real tests for the skill indexer using real temp skill libraries."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.skill_index import (  # noqa: E402
    _parse_frontmatter, build_index, scan_library, search,
)


def make_skill(root: Path, folder: str, name: str, desc: str,
               frontmatter: bool = True) -> Path:
    d = root / folder
    d.mkdir(parents=True)
    if frontmatter:
        content = f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n"
    else:
        content = f"# {name}\n\n{desc}\n"
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


def cfg_for(tmp_path: Path, libs: list[Path]) -> dict:
    persistence = tmp_path / "persistence"
    assets = tmp_path / "assets"
    (assets / "skills").mkdir(parents=True, exist_ok=True)
    persistence.mkdir(exist_ok=True)
    return {
        "BAIZE_PERSISTENCE_DIR": str(persistence),
        "BAIZE_ASSETS_DIR": str(assets),
        "BAIZE_PROJECTS_DIR": str(tmp_path),
        "BAIZE_INDEX_FILE": str(persistence / "skill_index.json"),
        "SKILL_LIBRARY_PATHS": ",".join(str(p) for p in libs),
    }


def test_frontmatter_parse():
    meta = _parse_frontmatter("---\nname: tdd\ndescription: test first\n---\n# x")
    assert meta["name"] == "tdd"
    assert meta["description"] == "test first"


def test_scan_finds_skills_with_and_without_frontmatter(tmp_path):
    lib = tmp_path / "lib"
    make_skill(lib, "tdd-workflow", "tdd-workflow", "red green refactor")
    make_skill(lib, "code-review", "Code Review", "review discipline",
               frontmatter=False)
    records = scan_library(lib, source="test")
    names = {r["name"] for r in records}
    assert names == {"tdd-workflow", "Code Review"}


def test_scan_skips_node_modules(tmp_path):
    lib = tmp_path / "lib"
    make_skill(lib, "real-skill", "real", "ok")
    junk = lib / "node_modules" / "pkg"
    junk.mkdir(parents=True)
    (junk / "SKILL.md").write_text("# junk", encoding="utf-8")
    records = scan_library(lib, source="test")
    assert len(records) == 1
    assert records[0]["name"] == "real"


def test_build_index_writes_json_and_search_hits(tmp_path):
    lib = tmp_path / "lib"
    make_skill(lib, "maozx-investigation", "maozx-investigation",
               "no investigation, no right to speak")
    cfg = cfg_for(tmp_path, [lib])

    index = build_index(cfg)
    assert index["count"] == 1
    assert Path(cfg["BAIZE_INDEX_FILE"]).exists()

    hits = search("investigation", cfg)
    assert len(hits) == 1
    assert hits[0]["name"] == "maozx-investigation"

    assert search("nonexistent-keyword-xyz", cfg) == []


def test_build_index_deduplicates_same_name_across_libraries(tmp_path):
    """Same skill name in local + external lib should appear only once."""
    lib = tmp_path / "lib"
    # Create the same skill in both local assets and external lib
    make_skill(lib, "tdd-workflow", "tdd-workflow", "from external lib")
    local_assets = tmp_path / "assets" / "skills"
    make_skill(local_assets, "tdd-workflow", "tdd-workflow", "from local")

    cfg = cfg_for(tmp_path, [lib])
    index = build_index(cfg)

    # Should be deduped to 1, not 2
    assert index["count"] == 1
    assert index["duplicates_deduped"] == 1
    # Local should win (first occurrence)
    assert index["skills"][0]["source"] == "local:assets/skills"
