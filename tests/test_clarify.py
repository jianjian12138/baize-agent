"""V23.5 clarify tests — pure functions only (no LLM)."""
from __future__ import annotations

from baize.orchestrator import render_prd


def test_render_prd_full():
    qa = {
        "questions": ["范围?"],
        "answers": ["仅登录注册"],
        "assumptions": ["使用 JWT"],
        "prd": "为系统增加基于 JWT 的登录注册。",
    }
    text = render_prd("加用户认证", qa)
    assert "# PRD" in text
    assert "加用户认证" in text
    assert "Q1" in text and "范围?" in text
    assert "A1" in text and "仅登录注册" in text
    assert "JWT" in text
    assert "基于 JWT 的登录注册" in text


def test_render_prd_empty_fallback():
    text = render_prd("模糊目标", None)
    assert "# PRD" in text
    assert "模糊目标" in text
    assert "none" in text
