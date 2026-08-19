"""Skill index builder & search.

Scans all roots in SKILL_LIBRARY_PATHS plus the local assets/skills directory
for SKILL.md files, extracts name/description from YAML frontmatter (or from
the first heading/paragraph as fallback), and writes a JSON index that any
agent client can load to discover skills without copying files.
"""
from __future__ import annotations

import json
import re
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
        fm_has_desc = "description" in meta
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
            # V23.1: a description recovered from the markdown *body* is not a
            # real frontmatter description; dedup must prefer genuine frontmatter
            # so a bare built-in copy never shadows a complete external copy.
            "desc_is_fallback": not fm_has_desc,
        })
    return records


def _source_priority(source: str) -> int:
    """Authority ranking for dedup tie-breaking.

    Agent-learned/user skills (``user:``) outrank external libraries, which
    outrank the built-in ``assets/skills`` (``local:``)."""
    if source.startswith("user:"):
        return 2
    if source.startswith("local:"):  # built-in assets/skills
        return 0
    return 1


def _norm_score(s: dict) -> tuple:
    """Quality score used to keep the *best* copy when a name repeats.

    V22 kept "first occurrence wins", so a built-in copy missing its
    ``description`` shadowed a complete external copy. We now prefer a *real*
    frontmatter ``description`` over a body-recovered fallback, then longer
    descriptions, then more authoritative sources.
    """
    desc = (s.get("description") or "").strip()
    has_real_desc = 1 if (desc and not s.get("desc_is_fallback")) else 0
    return (has_real_desc, min(len(desc), 200), _source_priority(s.get("source", "")))


def _dedup(skills: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Group by name; keep the highest-``_norm_score`` copy, drop the rest.

    Returns (unique, dropped, duplicate_groups) where ``duplicate_groups``
    records which source won and which were discarded, for the audit view.
    """
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for s in skills:
        key = s["name"].lower()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(s)
    unique: list[dict] = []
    dropped: list[dict] = []
    dup_groups: list[dict] = []
    for key in order:
        cand = groups[key]
        if len(cand) == 1:
            unique.append(cand[0])
            continue
        best_idx = max(range(len(cand)), key=lambda i: _norm_score(cand[i]))
        best = cand[best_idx]
        unique.append(best)
        losers = [c for i, c in enumerate(cand) if i != best_idx]
        dropped.extend(losers)
        dup_groups.append({
            "name": best["name"],
            "kept": best["source"],
            "dropped": [c["source"] for c in losers],
        })
    return unique, dropped, dup_groups


def build_index(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    skills: list[dict] = []

    local_skills = Path(cfg["BAIZE_ASSETS_DIR"]) / "skills"
    if local_skills.is_dir():
        skills.extend(scan_library(local_skills, source="local:assets/skills"))

    for lib in skill_library_paths(cfg):
        if lib.is_dir():
            skills.extend(scan_library(lib, source=str(lib)))

    # V23.2: scan the dedicated user / agent-learned library (separate from
    # collected libs) so autonomous skills are indexed without polluting them.
    # Fall back to a sibling of BAIZE_ASSETS_DIR so tests can omit the key.
    user_lib = Path(cfg.get("BAIZE_USER_SKILLS_DIR",
                            Path(cfg["BAIZE_ASSETS_DIR"]).parent / "user_skills"))
    if user_lib.is_dir():
        skills.extend(scan_library(user_lib, source="user:user_skills"))

    unique, dropped, dup_groups = _dedup(skills)

    # Governance audit (V23.1 / V23.3): per-source counts + frontmatter hygiene.
    per_source: dict[str, int] = {}
    missing: list[dict] = []
    for s in unique:
        per_source[s["source"]] = per_source.get(s["source"], 0) + 1
        if not (s.get("description") or "").strip():
            missing.append({"name": s["name"], "source": s["source"],
                            "path": s["path"]})

    index = {
        "version": 2,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "libraries": [str(p) for p in skill_library_paths(cfg)],
        "user_skills_dir": str(user_lib),
        "count": len(unique),
        "duplicates_deduped": len(dropped),
        "audit": {
            "per_source": per_source,
            "missing_description": missing,
            "duplicate_groups": dup_groups,
        },
        "skills": unique,
    }
    out = Path(cfg["BAIZE_INDEX_FILE"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def safe_name(name: str) -> str:
    """Slugify a skill name into a filesystem-safe directory name."""
    return re.sub(r"[^a-z0-9_-]", "-", (name or "").lower()).strip("-") or "unnamed"


def create_skill(name: str, description: str, body: str, *,
                 domain: str = "", level: str = "",
                 origin: str = "agent", cfg: dict | None = None) -> Path:
    """Persist a new SKILL.md into the user library and re-index (V23.2).

    The single entry point for autonomous skill creation: the agent (via the
    ``save_skill`` tool) and a human (via ``baize skill create``) both persist
    reusable skills here, never inside the built-in ``assets/skills`` collection.
    """
    cfg = cfg or load_config()
    safe = safe_name(name)
    skill_dir = Path(cfg["BAIZE_USER_SKILLS_DIR"]) / safe
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    fm = [
        "---",
        f"name: {safe}",
        f"description: {description.strip()}",
    ]
    if domain.strip():
        fm.append(f"domain: {domain.strip()}")
    if level.strip():
        fm.append(f"level: {level.strip()}")
    fm += [
        f"origin: {origin}",
        f"created_at: {time.strftime('%Y-%m-%dT%H:%M:%S')}",
        "---",
        "",
    ]
    content = "".join(line + "\n" for line in fm) + body.strip() + "\n"
    skill_file.write_text(content, encoding="utf-8")
    build_index(cfg)  # re-index so it is immediately findable
    return skill_file


def audit_index(cfg: dict | None = None) -> dict:
    """Deterministic governance audit (V23.3), no model needed.

    Surfaces duplicate groups, missing frontmatter, and per-source counts so
    collected-vs-autonomous skills can be reviewed and pruned.
    """
    idx = load_index(cfg)
    a = idx.get("audit", {})
    return {
        "count": idx.get("count", 0),
        "duplicates_deduped": idx.get("duplicates_deduped", 0),
        "per_source": a.get("per_source", {}),
        "missing_description": a.get("missing_description", []),
        "duplicate_groups": a.get("duplicate_groups", []),
    }


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
