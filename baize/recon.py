"""V23.4 pre-flight reconnaissance — avoid reinventing the wheel.

Before a goal is executed, scan:

(a) the local skill library for existing implementations that already solve
    (part of) the goal, and
(b) optionally external Chinese ecosystems (Gitee / Aliyun / Tencent Cloud /
    Juejin / Zhihu) for prior art.

External search is **OFF by default** and requires explicit opt-in
(``BAIZE_RECON_WEB=1`` AND ``--web``) because it leaves the machine — the
local-only scan is the fail-closed default. Zero runtime dependencies: web
search uses only :mod:`urllib` and only when explicitly enabled.

This mirrors the AI Labs "Advise Project Approach" idea (search before you
build) and balances the overseas bias by adding Chinese sources.
"""
from __future__ import annotations

import re

from . import skill_index
from .config import load_config

# Chinese-ecosystem search sources (template -> formatted URL). Consulted only
# when web recon is explicitly enabled; each is an untrusted outbound GET.
WEB_SOURCES = {
    "gitee": "https://search.gitee.com/?q={q}",
    "aliyun": "https://developer.aliyun.com/search?q={q}",
    "tencent": "https://cloud.tencent.com/developer/search?q={q}",
    "juejin": "https://juejin.cn/search?query={q}",
    "zhihu": "https://www.zhihu.com/search?type=content&q={q}",
}

_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "with",
    "this", "that", "实现", "使用", "一个", "这个", "我们", "请", "帮忙",
    "如何", "怎么", "添加", "加", "支持", "功能", "项目", "代码", "我",
}


def _cjk_ngrams(text: str) -> list[str]:
    """Stopword-aware CJK keyword windows.

    We first cut the CJK run wherever a *multi-character* stopword occurs
    (e.g. 如何 / 添加 / 功能), so a query like "如何添加一个用户认证功能"
    resolves into the content run "用户认证" instead of a cloud of overlapping
    fragments. Within each content run we then emit n-grams ordered longest
    first (up to 4-grams) so specific terms win over generic ones when the
    caller trims to ``top_k``.
    """
    multi = sorted((s for s in _STOPWORDS if len(s) >= 2),
                   key=len, reverse=True)
    runs: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)
    while i < n:
        hit = next((sw for sw in multi if text.startswith(sw, i)), None)
        if hit:
            if buf:
                runs.append("".join(buf))
                buf = []
            i += len(hit)
        else:
            buf.append(text[i])
            i += 1
    if buf:
        runs.append("".join(buf))
    out: list[str] = []
    for run in runs:
        if len(run) < 2:
            continue
        for length in range(min(4, len(run)), 1, -1):
            for j in range(len(run) - length + 1):
                out.append(run[j:j + length])
    return out


def extract_keywords(goal: str, top_k: int = 5) -> list[str]:
    """Cheap keyword extraction: strip punctuation, drop stopwords, de-dup.

    ASCII tokens are kept verbatim; CJK runs are segmented on multi-character
    stopwords and expanded into length-prioritised n-grams (e.g. "用户认证")
    so callers see real terms rather than the whole sentence as one token.
    """
    # 1) tokenise on whitespace + ASCII punctuation
    raw = re.findall(r"[A-Za-z0-9_\-]+|[一-龥]+", goal.lower())
    ngrams: list[str] = []
    for w in raw:
        if re.match(r"[一-龥]+", w):
            ngrams.extend(_cjk_ngrams(w))
        else:
            ngrams.append(w)
    seen: set[str] = set()
    uniq: list[str] = []
    for w in ngrams:
        if w in _STOPWORDS or len(w) < 2:
            continue
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq[:top_k]


def recon_library(goal: str, cfg: dict | None = None) -> list[dict]:
    """Search the local skill index for prior art related to the goal."""
    hits: list[dict] = []
    seen: set[str] = set()
    for kw in extract_keywords(goal):
        for h in skill_index.search(kw, cfg=cfg, limit=20):
            if h["name"] not in seen:
                seen.add(h["name"])
                hits.append(h)
    return hits


def _web_search(query: str) -> dict:
    """Build external search URLs (no body fetch — click-to-open, zero-parse).

    We deliberately return search URLs rather than scraping untrusted HTML:
    keeps the stdlib footprint at zero and avoids parsing third-party markup.
    """
    sources = [{"name": name, "url": tmpl.format(q=query)}
               for name, tmpl in WEB_SOURCES.items()]
    return {"query": query, "sources": sources}


def recon(goal: str, cfg: dict | None = None, web: bool = False) -> dict:
    """Pre-flight recon. Returns a structured advisory dict.

    Local skill matches are always scanned. External web search runs only when
    both ``web=True`` AND ``BAIZE_RECON_WEB=1`` (default off) — fail-closed.
    """
    cfg = cfg or load_config()
    lib_hits = recon_library(goal, cfg)

    web_hits: list[dict] = []
    web_enabled = str(cfg.get("BAIZE_RECON_WEB", "0")) == "1"
    if web and web_enabled:
        for kw in extract_keywords(goal, top_k=3):
            web_hits.append(_web_search(kw))
    elif web and not web_enabled:
        web_hits = [{"disabled": True,
                     "hint": "set BAIZE_RECON_WEB=1 to enable external recon"}]

    return {
        "goal": goal,
        "library_hits": lib_hits,
        "web_hits": web_hits,
        "advice": _render_advice(lib_hits),
    }


def _render_advice(lib_hits: list[dict]) -> str:
    if lib_hits:
        names = ", ".join(h["name"] for h in lib_hits[:6])
        return (f"已有同类技能可复用: {names}。建议先检索/加载这些技能，"
                f"避免从零实现。")
    return ("技能库中未发现同类实现。如为全新需求可直接实现；"
            "如需外部方案，可显式开启 web 侦察（--web）。")
