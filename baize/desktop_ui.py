"""Baize Agent Universal Desktop Studio UI (V39.0.0 Aegis).

A self-contained, high-fidelity, zero-dependency modern Single Page Application
aligned with Cursor, Hermes-CN-Desktop, Codex Desktop, and Pi Studio.

Frontend sources live in ``baize/studio/{index.html,styles.css,app.js}`` for
clean maintainability and are assembled (with mtime caching) into a single
HTML document by ``render_desktop_studio``.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import __version__

__all__ = ["render_desktop_studio", "read_studio_asset"]

_STUDIO_DIR = Path(__file__).resolve().parent / "studio"
_ASSET_LOCK = threading.Lock()
_ASSET_CACHE: dict[str, tuple[int, str]] = {}


def read_studio_asset(name: str) -> str | None:
    """Read an asset under ``baize/studio/`` with mtime caching."""
    if name not in ("index.html", "styles.css", "app.js"):
        return None
    p = _STUDIO_DIR / name
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return None
    with _ASSET_LOCK:
        cached = _ASSET_CACHE.get(name)
        if cached is not None and cached[0] == mtime:
            return cached[1]
    text = p.read_text(encoding="utf-8")
    with _ASSET_LOCK:
        _ASSET_CACHE[name] = (mtime, text)
    return text


def render_desktop_studio(version: str = __version__) -> str:
    v = version or __version__
    v_tag = v if v.startswith("V") else f"V{v}"
    html = read_studio_asset("index.html") or ""
    css = (read_studio_asset("styles.css") or "").rstrip("\n")
    js = (read_studio_asset("app.js") or "").rstrip("\n")
    return (
        html.replace("__VER__", v_tag)
        .replace("__STYLE_BLOCK__", css)
        .replace("__SCRIPT_BLOCK__", js)
    )
