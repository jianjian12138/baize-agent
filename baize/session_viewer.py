from __future__ import annotations
import json
from pathlib import Path


def render_session(path, max_content=200):
    path = Path(path)
    if not path.is_file():
        return "ERROR: session file not found: " + str(path)
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        return "(empty session: " + path.name + ")"
    out = ["Session: " + path.stem, "  Records: " + str(len(records)), "-" * 60]
    span_count = 0
    total_ms = 0
    for rec in records:
        kind = rec.get("kind", "message")
        ts = rec.get("ts", "")
        if kind == "message":
            msg = rec.get("message", {})
            role = msg.get("role", "?")
            content = str(msg.get("content") or "")[:max_content]
            ct = content.replace("\n", " ")
            if role == "system":
                out.append("  [" + ts + "] SYSTEM (" + str(len(content)) + " chars)")
            elif role == "user":
                out.append("  [" + ts + "] USER  " + repr(ct[:80]))
            elif role == "assistant":
                tcs = msg.get("tool_calls") or []
                cot = " (thinking)" if "<thinking>" in content else ""
                if tcs:
                    names = ", ".join(tc.get("function", {}).get("name", "?") for tc in tcs)
                    out.append("  [" + ts + "] ASST" + cot + " -> [" + names + "]")
                else:
                    out.append("  [" + ts + "] ASST" + cot + " " + repr(ct[:80]))
            elif role == "tool":
                out.append("  [" + ts + "]   OBS " + repr(ct[:80]))
        elif kind == "span":
            span_count += 1
            elapsed = rec.get("elapsed_ms", 0)
            total_ms += elapsed
            ok = "OK" if rec.get("ok", True) else "FAIL"
            tn = rec.get("tool", "?")
            out.append("  [" + ts + "]   SPAN " + tn + " (" + str(elapsed) + "ms) " + ok)
        elif kind == "compress":
            n = rec.get("message", {}).get("compressed", 0)
            out.append("  [" + ts + "] COMPRESS " + str(n))
        elif kind in ("fork", "rewind"):
            out.append("  [" + ts + "] " + kind.upper())
    out.append("-" * 60)
    out.append("  spans=" + str(span_count) + " total_tool_ms=" + str(total_ms))
    return "\n".join(out)


def find_session_file(session_id, cfg=None):
    if cfg is None:
        from .config import load_config
        cfg = load_config()
    d = Path(cfg.get("BAIZE_SESSIONS_DIR", "persistence/sessions"))
    if not d.is_dir():
        return None
    exact = d / (session_id + ".jsonl")
    if exact.is_file():
        return exact
    matches = sorted(d.glob(session_id + "*.jsonl"), reverse=True)
    return matches[0] if matches else None
