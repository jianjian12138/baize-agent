"""V44 Atlas OpenTelemetry-compatible W3C TraceContext tracer & OTLP/HTTP JSON exporter.

Pure Python standard library only — zero third-party telemetry SDK required.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..core.config import load_config
from .dlp import check_egress_url, redact_payload, redact_text

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def format_traceparent(trace_id: str, span_id: str, flags: str = "01") -> str:
    return f"00-{trace_id}-{span_id}-{flags}"


def parse_traceparent(header: str) -> tuple[str, str, str] | None:
    m = _TRACEPARENT_RE.match((header or "").strip().lower())
    if not m:
        return None
    tid, sid, flags = m.group(1), m.group(2), m.group(3)
    if tid == "0" * 32 or sid == "0" * 16:
        return None
    return tid, sid, flags


@dataclass
class OTelSpan:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str = ""
    kind: str = "INTERNAL"
    start_time_ns: int = field(default_factory=time.time_ns)
    end_time_ns: int = 0
    status: str = "OK"
    error_message: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[str(key)] = redact_payload(value)

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({
            "name": str(name),
            "time_ns": time.time_ns(),
            "attributes": redact_payload(attributes or {}),
        })

    def finish(self, *, status: str | None = None, error: str = "") -> None:
        if self.end_time_ns == 0:
            self.end_time_ns = time.time_ns()
        if status is not None:
            self.status = status
        if error:
            self.status = "ERROR"
            self.error_message = redact_text(error)[:400]

    @property
    def duration_ms(self) -> float:
        end = self.end_time_ns or time.time_ns()
        return round(max(0, end - self.start_time_ns) / 1_000_000.0, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "kind": self.kind,
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_message": self.error_message,
            "attributes": self.attributes,
            "events": self.events,
        }

    @staticmethod
    def _otlp_val(v: Any) -> dict[str, Any]:
        if isinstance(v, bool):
            return {"boolValue": v}
        if isinstance(v, int):
            return {"intValue": str(v)}
        if isinstance(v, float):
            return {"doubleValue": v}
        return {"stringValue": str(v)}

    def to_otlp_span(self) -> dict[str, Any]:
        kind_map = {"INTERNAL": 1, "SERVER": 2, "CLIENT": 3, "PRODUCER": 4, "CONSUMER": 5}
        span_obj: dict[str, Any] = {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "name": self.name,
            "kind": kind_map.get(self.kind.upper(), 1),
            "startTimeUnixNano": str(self.start_time_ns),
            "endTimeUnixNano": str(self.end_time_ns or time.time_ns()),
            "attributes": [{"key": k, "value": self._otlp_val(v)} for k, v in self.attributes.items()],
            "events": [
                {
                    "name": ev["name"],
                    "timeUnixNano": str(ev["time_ns"]),
                    "attributes": [{"key": k, "value": self._otlp_val(v)} for k, v in ev.get("attributes", {}).items()],
                }
                for ev in self.events
            ],
            "status": {"code": 2 if self.status == "ERROR" else 1, "message": self.error_message},
        }
        if self.parent_span_id:
            span_obj["parentSpanId"] = self.parent_span_id
        return span_obj


class Tracer:
    """Thread-safe OpenTelemetry tracer with JSONL persistence and OTLP/HTTP JSON export."""

    def __init__(self, *, service_name: str = "baize-agent", cfg: dict[str, Any] | None = None) -> None:
        self.service_name = service_name
        self._cfg = cfg
        self._local = threading.local()
        self._lock = threading.Lock()
        self._pending_otlp: list[OTelSpan] = []

    def _effective_cfg(self) -> dict[str, Any]:
        return self._cfg if self._cfg is not None else load_config()

    def _trace_file(self) -> Path:
        pdir = Path(self._effective_cfg().get("BAIZE_PERSISTENCE_DIR", "persistence"))
        pdir.mkdir(parents=True, exist_ok=True)
        return pdir / "traces.jsonl"

    def _otlp_endpoint(self) -> str:
        return str(self._effective_cfg().get("BAIZE_OTLP_ENDPOINT", "") or "").strip()

    def _stack(self) -> list[OTelSpan]:
        st = getattr(self._local, "stack", None)
        if st is None:
            st = []
            self._local.stack = st
        return st

    def current_span(self) -> OTelSpan | None:
        st = self._stack()
        return st[-1] if st else None

    @contextmanager
    def start_span(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
        kind: str = "INTERNAL",
        traceparent: str = "",
    ) -> Iterator[OTelSpan]:
        parent = self.current_span()
        parsed_tp = parse_traceparent(traceparent) if traceparent else None
        if parent is not None:
            tid = parent.trace_id
            psid = parent.span_id
        elif parsed_tp is not None:
            tid, psid, _ = parsed_tp
        else:
            tid = new_trace_id()
            psid = ""

        span = OTelSpan(
            name=name,
            trace_id=tid,
            span_id=new_span_id(),
            parent_span_id=psid,
            kind=kind,
            attributes=redact_payload(attributes or {}),
        )
        stack = self._stack()
        stack.append(span)
        try:
            yield span
        except Exception as exc:
            span.finish(status="ERROR", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if stack and stack[-1] is span:
                stack.pop()
            span.finish()
            self._record_span(span)

    def _record_span(self, span: OTelSpan) -> None:
        line = json.dumps(span.to_dict(), ensure_ascii=False)
        with self._lock:
            try:
                with self._trace_file().open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass
            if self._otlp_endpoint():
                self._pending_otlp.append(span)
                if len(self._pending_otlp) > 200:
                    self._pending_otlp = self._pending_otlp[-200:]

    def recent_traces(self, limit: int = 40) -> list[dict[str, Any]]:
        path = self._trace_file()
        if not path.is_file():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for raw in reversed(lines[-max(1, min(limit, 500)):]):
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out

    def flush_otlp(self, *, timeout: float = 3.0) -> dict[str, Any]:
        endpoint = self._otlp_endpoint()
        if not endpoint:
            return {"ok": True, "exported": 0, "reason": "BAIZE_OTLP_ENDPOINT not configured"}
        cfg = self._effective_cfg()
        ok_egress, reason = check_egress_url(endpoint, cfg=cfg)
        if not ok_egress:
            return {"ok": False, "exported": 0, "reason": reason}
        with self._lock:
            batch = list(self._pending_otlp)
            self._pending_otlp.clear()
        if not batch:
            return {"ok": True, "exported": 0, "reason": "no pending spans"}
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.service_name}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "baize.governance.telemetry"},
                            "spans": [s.to_otlp_span() for s in batch],
                        }
                    ],
                }
            ]
        }
        headers = {"Content-Type": "application/json"}
        raw_hdrs = str(cfg.get("BAIZE_OTLP_HEADERS", "") or "").strip()
        if raw_hdrs:
            for item in raw_hdrs.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    if k.strip():
                        headers[k.strip()] = v.strip()
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return {"ok": 200 <= resp.status < 300, "exported": len(batch), "status": resp.status}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            with self._lock:
                self._pending_otlp = batch + self._pending_otlp[-100:]
            return {"ok": False, "exported": 0, "reason": str(exc)}


_TRACER_LOCK = threading.Lock()
_TRACER_SINGLETON: Tracer | None = None
_TRACER_PDIR = ""


def get_tracer(cfg: dict[str, Any] | None = None) -> Tracer:
    global _TRACER_SINGLETON, _TRACER_PDIR
    c = cfg if cfg is not None else load_config()
    pdir = str(c.get("BAIZE_PERSISTENCE_DIR", "persistence"))
    with _TRACER_LOCK:
        if _TRACER_SINGLETON is None or _TRACER_PDIR != pdir:
            _TRACER_SINGLETON = Tracer(cfg=c if cfg is not None else None)
            _TRACER_PDIR = pdir
        return _TRACER_SINGLETON
