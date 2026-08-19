"""V23.4 recon tests — local-only, no network."""
from __future__ import annotations

from pathlib import Path

from baize import recon, skill_index


def _make_cfg(tmp_path: Path) -> dict:
    lib = tmp_path / "lib"
    (lib / "deploy-checklist").mkdir(parents=True)
    (lib / "deploy-checklist" / "SKILL.md").write_text(
        "---\nname: deploy-checklist\n"
        "description: 部署上线前的检查清单与回滚步骤\n---\n",
        encoding="utf-8")
    (tmp_path / "assets" / "skills").mkdir(parents=True)
    (tmp_path / "user_skills").mkdir()
    return {
        "BAIZE_INDEX_FILE": str(tmp_path / "idx.json"),
        "BAIZE_ASSETS_DIR": str(tmp_path / "assets"),
        "BAIZE_USER_SKILLS_DIR": str(tmp_path / "user_skills"),
        "SKILL_LIBRARY_PATHS": str(lib),
    }


def test_extract_keywords_strips_stopwords():
    kws = recon.extract_keywords("如何添加一个用户认证功能")
    assert "如何" not in kws
    assert "添加" not in kws
    assert "用户认证" in kws or "认证" in kws


def test_recon_library_finds_prior_art(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    skill_index.build_index(cfg)
    hits = recon.recon_library("部署上线的 checklist 怎么写", cfg=cfg)
    names = [h["name"] for h in hits]
    assert "deploy-checklist" in names


def test_recon_structure_and_web_gate(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    skill_index.build_index(cfg)
    rep = recon.recon("部署 checklist", cfg=cfg)
    assert set(rep) >= {"goal", "library_hits", "web_hits", "advice"}
    # web off by default -> web_hits empty; with BAIZE_RECON_WEB=1 + web=True
    # we emit external search URLs (no network call in this pure test path).
    cfg_on = dict(cfg, BAIZE_RECON_WEB="1")
    rep_web = recon.recon("部署 checklist", cfg=cfg_on, web=True)
    assert any(h.get("sources") for h in rep_web["web_hits"])
