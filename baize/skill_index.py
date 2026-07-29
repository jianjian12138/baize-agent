"""Skill index builder & search.

Scans all roots in SKILL_LIBRARY_PATHS plus the local assets/skills directory
for SKILL.md files, extracts name/description from YAML frontmatter (or from
the first heading/paragraph as fallback), and writes a JSON index that any
agent client can load to discover skills without copying files.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import load_config, skill_library_paths

MAX_DEPTH = 4  # skill folders are shallow; avoid walking node_modules jungles
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build", "vendor",
             ".venv", "venv", "legacy"}


def _parse_frontmatter(text: str) -> dict:
    """Minimal YAML frontmatter parser for 'key: value' pairs."""
    meta: dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return meta
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def _fallback_meta(text: str, folder: str) -> dict:
    """Derive name/description from markdown body when frontmatter is absent."""
    name, desc = folder, ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# ") and name == folder:
            name = s[2:].strip()
        elif s and not s.startswith("#") and not s.startswith("---") and not desc:
            desc = s[:200]
        if name != folder and desc:
            break
    return {"name": name, "description": desc}


def _iter_skill_files(root: Path):
    """Yield SKILL.md files up to MAX_DEPTH below root, skipping junk dirs."""
    base_depth = len(root.parts)

    def walk(d: Path):
        if len(d.parts) - base_depth > MAX_DEPTH:
            return
        try:
            entries = sorted(d.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                yield from walk(entry)
            elif entry.name == "SKILL.md":
                yield entry

    yield from walk(root)


def scan_library(root: Path, source: str) -> list[dict]:
    records = []
    for skill_file in _iter_skill_files(root):
        try:
            text = skill_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta = _parse_frontmatter(text)
        folder = skill_file.parent.name
        if "name" not in meta or "description" not in meta:
            fb = _fallback_meta(text, folder)
            meta.setdefault("name", fb["name"])
            meta.setdefault("description", fb["description"])
        records.append({
            "name": meta.get("name", folder),
            "description": meta.get("description", ""),
            "path": str(skill_file.parent),
            "skill_file": str(skill_file),
            "source": source,
        })
    return records


def build_index(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    skills: list[dict] = []

    local_skills = Path(cfg["BAIZE_ASSETS_DIR"]) / "skills"
    if local_skills.is_dir():
        skills.extend(scan_library(local_skills, source="local:assets/skills"))

    for lib in skill_library_paths(cfg):
        if lib.is_dir():
            skills.extend(scan_library(lib, source=str(lib)))

    # Deduplicate by skill name: first occurrence wins (local > external libs).
    # This prevents the same skill appearing 2-3x when it exists in multiple libraries.
    seen: set[str] = set()
    unique: list[dict] = []
    duplicates: list[dict] = []
    for s in skills:
        key = s["name"].lower()
        if key in seen:
            duplicates.append(s)
            continue
        seen.add(key)
        unique.append(s)

    index = {
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "libraries": [str(p) for p in skill_library_paths(cfg)],
        "count": len(unique),
        "duplicates_deduped": len(duplicates),
        "skills": unique,
    }
    out = Path(cfg["BAIZE_INDEX_FILE"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def load_index(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    out = Path(cfg["BAIZE_INDEX_FILE"])
    if not out.exists():
        return build_index(cfg)
    return json.loads(out.read_text(encoding="utf-8"))


def search(keyword: str, cfg: dict | None = None, limit: int = 20) -> list[dict]:
    keyword = keyword.lower()
    index = load_index(cfg)
    hits = []
    for s in index["skills"]:
        haystack = f"{s['name']} {s['description']} {s['path']}".lower()
        if keyword in haystack:
            hits.append(s)
        if len(hits) >= limit:
            break
    return hits
