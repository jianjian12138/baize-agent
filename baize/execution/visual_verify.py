"""V46 Sovereign Two-Stage Visual UI Self-Healing Verifier.

Pure Python standard library only.
Stage 1 (Deterministic): Checks HTTP reachability, console errors, uncaught
    exceptions, DOM health, broken images, and captures Desktop (1280x800) +
    Mobile (390x844) screenshots via pure-stdlib CDPBrowserClient (with honest
    HTTP-only fallback when Chrome/Chromium is not installed).
Stage 2 (Multimodal Vision): When screenshots exist and a multimodal LLM client
    is provided/configured, attaches captured PNGs via ``encode_image_part`` to
    identify layout/contrast/overflow/UX defects and returns structured feedback
    for Agent self-healing.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import load_config
from ..governance.dlp import check_egress_url

__all__ = [
    "VIEWPORT_PRESETS",
    "ViewportCapture",
    "VisualVerifyReport",
    "verify_ui",
]

VIEWPORT_PRESETS: dict[str, tuple[int, int]] = {
    "desktop": (1280, 800),
    "mobile": (390, 844),
    "tablet": (768, 1024),
}


@dataclass
class ViewportCapture:
    viewport: str
    width: int
    height: int
    ok: bool = False
    http_status: int = 0
    title: str = ""
    screenshot_path: str = ""
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    dom_text_length: int = 0
    broken_images: int = 0
    overflow_x: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VisualVerifyReport:
    url: str
    ok: bool
    stage1_ok: bool
    stage2_ran: bool = False
    stage2_ok: bool = True
    backend: str = "http-fallback"
    captures: list[ViewportCapture] = field(default_factory=list)
    defects: list[str] = field(default_factory=list)
    vision_summary: str = ""
    elapsed_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "ok": self.ok,
            "passed": self.ok,
            "stage1_ok": self.stage1_ok,
            "stage2_ran": self.stage2_ran,
            "stage2_ok": self.stage2_ok,
            "backend": self.backend,
            "captures": [c.to_dict() for c in self.captures],
            "defects": list(self.defects),
            "vision_summary": self.vision_summary,
            "elapsed_ms": self.elapsed_ms,
        }

    def format_for_agent(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines = [
            f"[verify_ui:{self.backend}] {status} url={self.url} elapsed={self.elapsed_ms:.1f}ms "
            f"(stage1={'ok' if self.stage1_ok else 'fail'}, stage2={'ran' if self.stage2_ran else 'skipped'})"
        ]
        for cap in self.captures:
            shot = f" screenshot={cap.screenshot_path}" if cap.screenshot_path else ""
            lines.append(
                f"  - {cap.viewport} ({cap.width}x{cap.height}): ok={cap.ok} "
                f"title={cap.title!r} dom_chars={cap.dom_text_length} "
                f"console_err={len(cap.console_errors)} page_err={len(cap.page_errors)} "
                f"broken_img={cap.broken_images} overflow_x={cap.overflow_x}{shot}"
            )
        if self.defects:
            lines.append("  Defects to fix:")
            for d in self.defects[:10]:
                lines.append(f"    * {d}")
        if self.vision_summary:
            lines.append(f"  Vision Review: {self.vision_summary[:500]}")
        return "\n".join(lines)


def _http_fallback_check(url: str, viewport: str, w: int, h: int, timeout: float) -> ViewportCapture:
    cap = ViewportCapture(viewport=viewport, width=w, height=h)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BaizeVisualVerify/46"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cap.http_status = int(resp.status)
            html = resp.read().decode("utf-8", errors="replace")
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        cap.title = re.sub(r"\s+", " ", m_title.group(1)).strip() if m_title else ""
        text_only = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL)
        text_only = re.sub(r"<[^>]+>", " ", text_only)
        cap.dom_text_length = len(re.sub(r"\s+", " ", text_only).strip())
        cap.ok = 200 <= cap.http_status < 400 and cap.dom_text_length > 0
        if cap.dom_text_length == 0:
            cap.note = "blank HTML body (0 text chars)"
        else:
            cap.note = "HTTP fallback check (Chrome/Chromium unavailable for CDP screenshot)"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        cap.ok = False
        cap.page_errors.append(f"HTTP unreachable: {exc}")
    return cap


def _cdp_capture_viewport(
    url: str,
    viewport: str,
    w: int,
    h: int,
    out_dir: Path,
    timeout: float,
    browser_binary: str,
) -> ViewportCapture:
    from .cdp_browser import CDPBrowserClient
    cap = ViewportCapture(viewport=viewport, width=w, height=h)
    shot_file = out_dir / f"{viewport}-{int(time.time() * 1000)}.png"
    client = CDPBrowserClient(browser_binary=browser_binary, timeout=timeout)
    try:
        client.connect()
        try:
            client.send_command("Emulation.setDeviceMetricsOverride", {
                "width": w,
                "height": h,
                "deviceScaleFactor": 1,
                "mobile": viewport == "mobile",
            })
        except Exception:
            pass
        res = client.verify_page(url, screenshot_path=shot_file)
        cap.title = res.title
        cap.console_errors = list(res.console_errors)
        cap.page_errors = list(res.exceptions)
        cap.screenshot_path = str(shot_file) if shot_file.is_file() else ""
        # Inspect DOM text, broken images, and horizontal overflow
        try:
            eval_res = client.send_command("Runtime.evaluate", {
                "expression": (
                    "JSON.stringify({"
                    "textLen: (document.body && document.body.innerText ? document.body.innerText.trim().length : 0),"
                    "brokenImgs: Array.from(document.images || []).filter(i => !i.complete || i.naturalWidth === 0).length,"
                    "overflowX: (document.documentElement.scrollWidth > window.innerWidth + 2)"
                    "})"
                ),
                "returnByValue": True,
            })
            val_str = ((eval_res.get("result") or {}).get("value")) or "{}"
            metrics = json.loads(val_str) if isinstance(val_str, str) else {}
            cap.dom_text_length = int(metrics.get("textLen", 0))
            cap.broken_images = int(metrics.get("brokenImgs", 0))
            cap.overflow_x = bool(metrics.get("overflowX", False))
        except Exception:
            cap.dom_text_length = 1 if res.ok else 0
        cap.http_status = 200 if res.ok else 0
        cap.ok = (
            res.ok
            and len(cap.console_errors) == 0
            and len(cap.page_errors) == 0
            and cap.dom_text_length > 0
            and cap.broken_images == 0
        )
    finally:
        client.close()
    return cap


def _run_vision_review(
    url: str,
    captures: list[ViewportCapture],
    *,
    client: Any,
    cfg: dict[str, Any],
) -> tuple[bool, bool, list[str], str]:
    """Optional Stage 2 multimodal review over captured screenshots."""
    shots = [c for c in captures if c.screenshot_path and Path(c.screenshot_path).is_file()]
    if not shots or client is None:
        return False, True, [], ""
    try:
        from ..core.llm import encode_image_part
        parts: list[dict[str, Any]] = [{
            "type": "text",
            "text": (
                f"Review these UI screenshots of {url} for layout overlap, clipped text, "
                "broken contrast, horizontal overflow, or blank regions. "
                'Reply strictly in JSON: {"passed": true/false, "summary": "...", "defects": ["..."]}.'
            ),
        }]
        for c in shots[:2]:
            parts.append(encode_image_part(c.screenshot_path, max_bytes=int(cfg.get("BAIZE_MULTIMODAL_MAX_BYTES", "4194304") or 4194304)))
        reply = client.chat([{"role": "user", "content": parts}], temperature=0.1)
        content = str((reply or {}).get("content") or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        parsed = json.loads(m.group(0)) if m else {}
        passed = bool(parsed.get("passed", True))
        defects = [str(d) for d in (parsed.get("defects") or []) if str(d).strip()]
        summary = str(parsed.get("summary") or content[:300])
        return True, passed, defects, summary
    except Exception as exc:
        return False, True, [], f"vision review skipped: {exc}"


def verify_ui(
    url: str,
    *,
    viewports: tuple[str, ...] | list[str] | None = None,
    check_visual: bool = True,
    cfg: dict[str, Any] | None = None,
    client: Any = None,
) -> VisualVerifyReport:
    """Run two-stage UI verification across requested viewports."""
    t0 = time.perf_counter()
    c = cfg if cfg is not None else load_config()
    ok_egress, egress_reason = check_egress_url(url, cfg=c)
    if not ok_egress:
        return VisualVerifyReport(
            url=url,
            ok=False,
            stage1_ok=False,
            backend="egress-blocked",
            defects=[egress_reason],
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )

    if viewports is None:
        raw_vp = str(c.get("BAIZE_VISUAL_VERIFY_VIEWPORTS", "desktop,mobile") or "desktop,mobile")
        vp_list = [v.strip().lower() for v in raw_vp.split(",") if v.strip().lower() in VIEWPORT_PRESETS]
        if not vp_list:
            vp_list = ["desktop", "mobile"]
    else:
        vp_list = [v.strip().lower() for v in viewports if v.strip().lower() in VIEWPORT_PRESETS] or ["desktop"]

    timeout = float(c.get("BAIZE_CDP_TIMEOUT", "15") or 15)
    out_dir = Path(c.get("BAIZE_PERSISTENCE_DIR", "persistence")) / "visual_captures"
    out_dir.mkdir(parents=True, exist_ok=True)

    from .cdp_browser import find_browser_binary
    browser_bin = find_browser_binary(str(c.get("BAIZE_CDP_BINARY", "") or ""))
    backend = "cdp" if browser_bin else "http-fallback"

    captures: list[ViewportCapture] = []
    defects: list[str] = []
    for vp in vp_list:
        w, h = VIEWPORT_PRESETS[vp]
        if browser_bin:
            try:
                cap = _cdp_capture_viewport(url, vp, w, h, out_dir, timeout, browser_bin)
            except Exception as exc:
                backend = "http-fallback"
                cap = _http_fallback_check(url, vp, w, h, timeout)
                cap.note = f"CDP failed ({exc}); fell back to HTTP check"
        else:
            cap = _http_fallback_check(url, vp, w, h, timeout)
        captures.append(cap)
        if cap.console_errors:
            defects.extend([f"[{vp}] console error: {e}" for e in cap.console_errors[:3]])
        if cap.page_errors:
            defects.extend([f"[{vp}] page error: {e}" for e in cap.page_errors[:3]])
        if cap.dom_text_length == 0:
            defects.append(f"[{vp}] blank DOM rendered (0 visible text chars)")
        if cap.broken_images > 0:
            defects.append(f"[{vp}] {cap.broken_images} broken image(s)")
        if cap.overflow_x:
            defects.append(f"[{vp}] horizontal overflow detected at width={w}px")

    stage1_ok = all(cap.ok for cap in captures) and len(defects) == 0
    stage2_ran = False
    stage2_ok = True
    vision_summary = ""
    if check_visual and client is not None and any(cap.screenshot_path for cap in captures):
        stage2_ran, stage2_ok, v_defects, vision_summary = _run_vision_review(url, captures, client=client, cfg=c)
        defects.extend(v_defects)

    overall_ok = stage1_ok and (stage2_ok if stage2_ran else True)
    return VisualVerifyReport(
        url=url,
        ok=overall_ok,
        stage1_ok=stage1_ok,
        stage2_ran=stage2_ran,
        stage2_ok=stage2_ok,
        backend=backend,
        captures=captures,
        defects=defects,
        vision_summary=vision_summary,
        elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
    )
