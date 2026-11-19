"""Live SSE streaming handler for /run/stream."""
from __future__ import annotations

import json
import queue
import threading
from typing import Any


def handle_run_stream(handler, data: dict, deps: dict[str, Any]) -> None:
    goal = (data.get("goal") or "").strip()
    if not goal:
        return handler._send(400, {"error": "missing goal"})

    llm_cls = deps["LLMClient"]
    agent_cls = deps["Agent"]
    has_real_key = deps["has_real_key"]
    obs = deps["obs"]

    client = llm_cls()
    if not client.configured:
        return handler._send(422, {"error": "model endpoint not configured"})
    if not has_real_key(client):
        return handler._send(422, {"error": "model API key not set (placeholder in .env)"})

    evt_queue: queue.Queue = queue.Queue()

    def _on_agent_event(ev_kind: str, detail: str) -> None:
        evt_queue.put(("event", ev_kind, str(detail)))

    agent = agent_cls(role="executor", client=client, on_event=_on_agent_event)
    obs.inc("serve_run")

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.close_connection = True
    handler._emit_cors()
    handler.end_headers()

    def emit(event_type: str, payload: dict) -> bool:
        msg = f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        try:
            handler.wfile.write(msg.encode("utf-8"))
            handler.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _worker() -> None:
        try:
            res = agent.run(goal)
            evt_queue.put(("result", res, None))
        except Exception as exc:  # noqa: BLE001
            evt_queue.put(("result", None, exc))

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    emit("think", {"content": f"正在解析任务意图与沙箱上下文: {goal}"})

    res = None
    err = None
    while True:
        try:
            item = evt_queue.get(timeout=15.0)
        except queue.Empty:
            try:
                handler.wfile.write(b": keepalive\n\n")
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                break
            continue

        tag = item[0]
        if tag == "event":
            _, ev_kind, detail = item
            mapped = "think" if ev_kind in ("reflect", "compress") else ev_kind
            if not emit(mapped, {"kind": ev_kind, "content": detail}):
                break
        elif tag == "result":
            _, res, err = item
            break

    if err is not None:
        emit("error", {"error": str(err)})
        return
    if res is None:
        return

    text = res.final_text or "任务执行完毕。"
    chunk_size = 64
    for i in range(0, len(text), chunk_size):
        if not emit("delta", {"text": text[i:i + chunk_size]}):
            return
    emit("done", {
        "final_text": res.final_text,
        "session_id": res.session_id,
        "steps": res.steps,
        "stopped_reason": res.stopped_reason,
    })
