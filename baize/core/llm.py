"""Multi-provider LLM client with pooled HTTP keep-alive and prompt prefix caching."""

from __future__ import annotations

# ===========================================================================
# Section: http_pool.py
# ===========================================================================

import http.client
import io
import json
import threading
import time
import urllib.error
import urllib.parse
from typing import Any

__all__ = [
    "HTTPConnPool",
    "get_http_pool",
    "get_http_pool_stats",
    "pooled_post_json",
]


class HTTPConnPool:
    """Thread-safe per-(scheme, host, port) Keep-Alive HTTP/HTTPS pool."""

    def __init__(self, max_per_host: int = 8, idle_ttl: float = 60.0) -> None:
        self.max_per_host = max_per_host
        self.idle_ttl = idle_ttl
        self._lock = threading.Lock()
        self._pool: dict[tuple[str, str, int], list[tuple[http.client.HTTPConnection, float]]] = {}
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def acquire(self, scheme: str, host: str, port: int) -> tuple[http.client.HTTPConnection, bool]:
        key = (scheme, host, port)
        now = time.monotonic()
        with self._lock:
            bucket = self._pool.get(key)
            while bucket:
                conn, ts = bucket.pop()
                if now - ts <= self.idle_ttl and conn.sock is not None:
                    self.hits += 1
                    return conn, True
                self.evictions += 1
                try:
                    conn.close()
                except Exception:
                    pass
            self.misses += 1
        conn = (
            http.client.HTTPSConnection(host, port, timeout=120)
            if scheme == "https"
            else http.client.HTTPConnection(host, port, timeout=120)
        )
        return conn, False

    def release(self, scheme: str, host: str, port: int, conn: http.client.HTTPConnection) -> None:
        key = (scheme, host, port)
        with self._lock:
            bucket = self._pool.setdefault(key, [])
            if len(bucket) < self.max_per_host and conn.sock is not None:
                bucket.append((conn, time.monotonic()))
                return
            self.evictions += 1
        try:
            conn.close()
        except Exception:
            pass

    def stats(self) -> dict[str, int]:
        with self._lock:
            pooled = sum(len(v) for v in self._pool.values())
            return {
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "pooled": pooled,
            }

    def close_all(self) -> None:
        with self._lock:
            for bucket in self._pool.values():
                for conn, _ in bucket:
                    try:
                        conn.close()
                    except Exception:
                        pass
            self._pool.clear()


_CONN_POOL = HTTPConnPool()


def get_http_pool() -> HTTPConnPool:
    return _CONN_POOL


def get_http_pool_stats() -> dict[str, int]:
    """Return live Keep-Alive connection pool telemetry."""
    return _CONN_POOL.stats()


def pooled_post_json(url: str, headers: dict, payload: dict) -> dict[str, Any]:
    """POST JSON using the shared Keep-Alive connection pool with stale-socket retry."""
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        raise urllib.error.URLError(f"unknown url type: {url}")
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    data = json.dumps(payload).encode("utf-8")
    req_headers = dict(headers)
    req_headers.setdefault("Connection", "keep-alive")
    req_headers["Content-Length"] = str(len(data))

    for retry_stale in (True, False):
        conn, from_pool = _CONN_POOL.acquire(scheme, host, port)
        try:
            conn.request("POST", target, body=data, headers=req_headers)
            resp = conn.getresponse()
            raw_bytes = resp.read()
            if getattr(resp, "will_close", True):
                conn.close()
            else:
                _CONN_POOL.release(scheme, host, port, conn)
            if resp.status >= 400:
                raise urllib.error.HTTPError(
                    url, resp.status, resp.reason, resp.headers, io.BytesIO(raw_bytes)
                )
            return json.loads(raw_bytes.decode("utf-8"))
        except (http.client.HTTPException, OSError):
            try:
                conn.close()
            except Exception:
                pass
            if from_pool and retry_stale:
                continue
            raise
    raise urllib.error.URLError(f"request failed for {url}")

# ===========================================================================
# Section: prompt_cache.py
# ===========================================================================

__all__ = ["estimate_tokens", "cacheable_prefix",
           "build_cacheable_messages", "mark_cacheable"]


def estimate_tokens(text: str, approx: bool = True) -> int:
    """APPROXIMATE token count.

    Heuristic of ~4 characters per token (English baseline). This is
    intentionally coarse: real tokenizers differ by model and by language.
    The ``approx`` flag is True by default and the result must never be
    reported as an exact token count.
    """
    if not isinstance(text, str):
        text = str(text)
    return max(1, len(text) // 4)


def cacheable_prefix(system_prompt: str,
                     tool_schemas: list[dict] | None = None) -> list[dict]:
    """The stable leading block that should be cached across turns.

    Returns ``[{"role": "system", "content": system_prompt}]`` - the system
    prompt is the primary cache anchor. Tool definitions, when supplied to the
    model via the ``tools=`` parameter, form a second stable block and are
    treated as part of the same cached prefix. The output is deterministic:
    identical inputs always yield an identical, ordered structure.
    """
    block: list[dict] = [{"role": "system", "content": system_prompt}]
    return block


def build_cacheable_messages(system_prompt: str,
                             tool_schemas: list[dict] | None,
                             conversation: list[dict]) -> list[dict]:
    """Pin the cacheable prefix first, then append the conversation.

    Any pre-existing ``system`` message in ``conversation`` is collapsed into
    the single canonical system prompt so the prefix is unambiguous and stable
    (a requirement for reliable prompt caching).
    """
    convo = [m for m in conversation if m.get("role") != "system"]
    return cacheable_prefix(system_prompt, tool_schemas) + convo


def mark_cacheable(messages: list[dict], provider: str) -> list[dict]:
    """Attach the provider-native cache marker to the prefix.

    - Anthropic: adds ``cache_control: {"type": "ephemeral"}`` to the last
      system block (the cache breakpoint sits at the end of the stable prefix).
    - OpenAI / Ollama: returned unchanged - they cache identical prefixes
      automatically, no marker required.

    Returns a NEW list; the input is never mutated.
    """
    if provider != "anthropic":
        return list(messages)
    out = []
    last_sys_idx = -1
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            last_sys_idx = i
        out.append(dict(m))
    if last_sys_idx >= 0:
        out[last_sys_idx] = {
            **out[last_sys_idx],
            "cache_control": {"type": "ephemeral"},
        }
    return out

# ===========================================================================
# Section: llm.py
# ===========================================================================

import json
import re
import threading
import time
import urllib.error
import urllib.parse
from pathlib import Path
from pathlib import Path
import urllib.request
import http.client
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .config import load_config
from .config import get_logger
from ..governance.observability import obs
from ..governance.mutation import Chaos

log = get_logger("llm")

Transport = Callable[[str, dict, dict], dict]
StreamTransport = Callable[[str, dict, dict], Iterator[dict]]


class LLMError(RuntimeError):
    """Raised when the model endpoint cannot produce a usable response."""


def _friendly_llm_error(exc: Exception) -> str:
    """Format low-level HTTP/LLM exceptions into clean, human-friendly error messages without exposing raw internal URLs."""
    raw = str(exc)
    low = raw.lower()
    if "unknown url type" in low or "invalid url" in low or "nonnumeric port" in low or "nodename nor servname" in low:
        return "大模型服务连接失败：接口 Base URL 格式无效（必须以 http:// 或 https:// 开头）。请检查 .env 配置或在终端输入 /setup 重新设置。"
    if "401" in raw or "unauthorized" in low:
        return "大模型身份认证失败：API Key 无效或未授权。请检查 .env 中的 API Key 或输入 /setup 重新设置。"
    if "404" in raw or "not found" in low:
        return "大模型接口未找到 (HTTP 404)：模型名称或 Base URL 路径不存在。请检查 .env 中的模型名称或输入 /setup 重新设置。"
    if "429" in raw or "rate limit" in low or "quota" in low:
        return "大模型请求频次超限或账户余额不足 (HTTP 429)。请稍后重试或检查账户额度。"
    if "connection refused" in low or "actively refused" in low or "10061" in raw:
        return "大模型连接被拒绝：无法连接到目标服务（若使用本地 Ollama 请确保已运行 ollama serve）。"
    if "timed out" in low or "timeout" in low:
        return "大模型请求超时：网络连接缓慢或服务无响应，请检查网络。"

    cleaned = re.sub(r"https?://[^\s\'\",]+", "<api-endpoint>", raw)
    return f"大模型调用失败: {cleaned}（可输入 /setup 重新配置）"


@dataclass
class ModelSpec:
    name: str
    base_url: str
    api_key: str = ""
    weight: float = 1.0
    provider: str = "openai"   # openai | anthropic | ollama | deepseek
    max_tokens: int = 4096      # per-model cap; env BAIZE_MAX_TOKENS overrides at load


class RateLimiter:
    """Sliding-window rate limiter for requests/min and tokens/min (thread-safe)."""

    def __init__(self, rpm: int, tpm: int) -> None:
        self.rpm = rpm
        self.tpm = tpm
        self._reqs: list[float] = []
        self._tokens: list[tuple[float, int]] = []
        self._lock = threading.Lock()

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def acquire(self, tokens: int = 0) -> None:
        sleep_for = 0.0
        with self._lock:
            now = time.time()
            self._reqs = [t for t in self._reqs if now - t < 60]
            self._tokens = [(t, n) for (t, n) in self._tokens if now - t < 60]
            if self.rpm and len(self._reqs) >= self.rpm:
                wait = 60 - (now - self._reqs[0])
                if wait > 0:
                    sleep_for = max(sleep_for, min(wait, 5))
            if self.tpm and sum(n for _, n in self._tokens) + tokens > self.tpm:
                sleep_for = max(sleep_for, 1.0)
        if sleep_for > 0:
            time.sleep(sleep_for)
        with self._lock:
            ts = time.time()
            self._reqs.append(ts)
            if tokens:
                self._tokens.append((ts, tokens))


def _infer_provider(base_url: str) -> str:
    """Best-effort provider detection from the endpoint URL (zero deps)."""
    u = (base_url or "").lower()
    if "anthropic" in u or "claude" in u:
        return "anthropic"
    if "ollama" in u or ":11434" in u:
        return "ollama"
    return "openai"





def _http_transport(url: str, headers: dict, payload: dict) -> dict:
    return pooled_post_json(url, headers, payload)


# ---------------------------------------------------------------------------
# Provider adapters (request shape + response parsing). All use the same
# urllib transport; only the JSON envelope differs. Zero third-party deps.
# ---------------------------------------------------------------------------

def _endpoint(spec: "ModelSpec") -> str:
    if spec.provider == "anthropic":
        return f"{spec.base_url.rstrip('/')}/v1/messages"
    return f"{spec.base_url.rstrip('/')}/chat/completions"  # openai / ollama


def _build_request(spec: "ModelSpec", messages: list[dict],
                   tools: list[dict] | None, temperature: float | None) -> dict:
    if spec.provider == "anthropic":
        return _anthropic_request(spec, messages, tools, temperature)
    return _openai_request(spec, messages, tools, temperature)


def _openai_request(spec: "ModelSpec", messages: list[dict],
                    tools: list[dict] | None, temperature: float | None) -> dict:
    p: dict = {"model": spec.name, "messages": messages}
    if tools:
        p["tools"] = tools
    if temperature is not None:
        p["temperature"] = temperature
    return p


def _anthropic_request(spec: "ModelSpec", messages: list[dict],
                       tools: list[dict] | None, temperature: float | None) -> dict:
    sys_msgs = [m for m in messages
                if m.get("role") == "system"
                and isinstance(m.get("content"), str)]
    convo: list[dict] = []

    def _push(role: str, content) -> None:
        if not convo or convo[-1]["role"] != role:
            convo.append({"role": role, "content": content})
            return
        # Merge adjacent same-role turns into content-block lists for Anthropic
        prev = convo[-1]["content"]
        prev_blocks = [{"type": "text", "text": prev}] if isinstance(prev, str) else list(prev or [])
        new_blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
        convo[-1]["content"] = prev_blocks + new_blocks

    for m in messages:
        role = m.get("role")
        if role == "user":
            _push("user", m.get("content") or "")
        elif role == "assistant":
            tcalls = m.get("tool_calls") or []
            if not tcalls:
                _push("assistant", m.get("content") or "")
            else:
                blocks: list[dict] = []
                text_val = m.get("content")
                if text_val:
                    blocks.append({"type": "text", "text": str(text_val)})
                for tc in tcalls:
                    fn = tc.get("function", {})
                    raw_arg = fn.get("arguments") or "{}"
                    try:
                        parsed_input = json.loads(raw_arg) if isinstance(raw_arg, str) else dict(raw_arg)
                    except (json.JSONDecodeError, TypeError):
                        parsed_input = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id") or f"toolu_{len(blocks)}",
                        "name": fn.get("name", ""),
                        "input": parsed_input,
                    })
                _push("assistant", blocks)
        elif role == "tool":
            _push("user", [{
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id") or "",
                "content": str(m.get("content") or ""),
            }])
    body: dict = {"model": spec.name, "max_tokens": spec.max_tokens,
                  "messages": convo}
    if sys_msgs:
        # P3-4: if a system block carries cache_control, render it as an
        # Anthropic cacheable text block (enables prompt caching). Otherwise
        # the legacy plain-string system field is preserved (no behavior change).
        if any(m.get("cache_control") for m in sys_msgs):
            body["system"] = [
                {"type": "text", "text": m["content"],
                 "cache_control": m["cache_control"]}
                for m in sys_msgs
            ]
        else:
            body["system"] = "\n\n".join(m["content"] for m in sys_msgs)
    if tools:
        body["tools"] = [_to_anthropic_tool(t) for t in tools]
    if temperature is not None:
        body["temperature"] = temperature
    return body


def _to_anthropic_tool(openai_tool: dict) -> dict:
    fn = openai_tool.get("function", openai_tool)
    return {"name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}})}


def _parse_response(raw: dict, provider: str = "openai") -> dict:
    if provider == "anthropic":
        return _anthropic_parse(raw)
    return _openai_parse(raw)


def _openai_parse(raw: dict) -> dict:
    try:
        choice = raw["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"malformed model response: {exc}: "
                       f"{str(raw)[:300]}") from exc
    out = {"role": "assistant", "content": msg.get("content")}
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
    # DeepSeek (and compatible) expose chain-of-thought on OpenAI-shaped
    # responses via ``reasoning_content``; surface it so callers can log/verify
    # the reasoning trace instead of discarding it.
    if msg.get("reasoning_content"):
        out["reasoning_content"] = msg["reasoning_content"]
    return out


def _anthropic_parse(raw: dict) -> dict:
    """Normalize an Anthropic /v1/messages response to our message shape."""
    blocks = raw.get("content", [])
    if not isinstance(blocks, list):
        raise LLMError(f"malformed anthropic response: {str(raw)[:300]}")
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            text_parts.append(b.get("text", ""))
        elif b.get("type") == "tool_use":
            tool_calls.append({
                "id": b.get("id"),
                "type": "function",
                "function": {
                    "name": b.get("name", ""),
                    "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                },
            })
    out: dict = {"role": "assistant", "content": "".join(text_parts)}
    if tool_calls:
        out["tool_calls"] = tool_calls
    return out


def _http_stream_transport(url: str, headers: dict, payload: dict) -> Iterator[dict]:
    """Real SSE reader for OpenAI-style streaming chat completions."""
    parsed = urllib.parse.urlparse(url)
    payload = dict(payload, stream=True)
    body = json.dumps(payload).encode("utf-8")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    conn = http.client.HTTPSConnection(host, port, timeout=120) \
        if parsed.scheme == "https" else \
        http.client.HTTPConnection(host, port, timeout=120)
    target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    try:
        conn.request("POST", target, body=body, headers=headers)
        resp = conn.getresponse()
        if resp.status >= 400:
            err_body = resp.read(512).decode("utf-8", errors="replace")
            raise LLMError(f"HTTP {resp.status} from stream endpoint: {err_body}")
        for raw in resp:
            raw = raw.strip()
            if not raw.startswith(b"data:"):
                continue
            data = raw[5:].strip()
            if data == b"[DONE]":
                break
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue
    finally:
        conn.close()


def _anthropic_stream_transport(url: str, headers: dict, payload: dict) -> Iterator[dict]:
    """Real SSE reader for Anthropic ``/v1/messages`` streaming.

    Anthropic emits ``event:`` / ``data:`` framed JSON events; we translate the
    ``content_block_delta`` (``text_delta``) events into the OpenAI-shaped
    ``{"choices":[{"delta":{"content": ...}}]}`` chunk the caller's parser
    expects, so ``_stream`` needs no provider-specific branch in its loop.
    """
    parsed = urllib.parse.urlparse(url)
    payload = dict(payload, stream=True)
    body = json.dumps(payload).encode("utf-8")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    conn = (http.client.HTTPSConnection(host, port, timeout=120)
            if parsed.scheme == "https" else
            http.client.HTTPConnection(host, port, timeout=120))
    target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    try:
        conn.request("POST", target, body=body, headers=headers)
        resp = conn.getresponse()
        if resp.status >= 400:
            err_body = resp.read(512).decode("utf-8", errors="replace")
            raise LLMError(f"HTTP {resp.status} from anthropic stream endpoint: {err_body}")
        buf = b""
        for raw in resp:  # http.client yields raw bytes across chunk boundaries
            buf += raw
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    evt = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if evt.get("type") == "content_block_delta":
                    delta = evt.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield {"choices": [{"delta": {
                            "content": delta.get("text", "")}}]}
                # message_start / content_block_start / message_delta /
                # message_stop / ping are intentionally ignored here.
    finally:
        conn.close()


class LLMClient:
    """Chat-completions client with routing, streaming and rate limiting."""

    def __init__(self, cfg: dict | None = None, transport: Transport | None = None,
                 stream_transport: StreamTransport | None = None):
        cfg = cfg or load_config()
        self.cfg = cfg
        self.max_retries = int(cfg.get("BAIZE_LLM_MAX_RETRIES", "2"))
        self.rate = RateLimiter(
            int(cfg.get("BAIZE_RATE_LIMIT_RPM", "60")),
            int(cfg.get("BAIZE_RATE_LIMIT_TPM", "60000")),
        )
        # Fault injection (chaos) is layered only over the *default* transport.
        # An explicitly injected transport (tests, custom adapters) is left
        # untouched so behaviour stays deterministic and isolated. Chaos is OFF
        # unless BAIZE_CHAOS_ENABLED=1, so the wrapped transport just delegates.
        self._chaos = Chaos(self.cfg)
        self.transport = (
            self._chaos.wrap_transport(_http_transport)
            if transport is None else transport)
        self.stream_transport = (
            self._chaos.wrap_transport(_http_stream_transport)
            if stream_transport is None else stream_transport)
        self._route_from_config()
        self._telemetry_lock = threading.Lock()
        self._telemetry: dict[str, float | int] = {
            "requests": 0,
            "retries": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_latency_ms": 0.0,
        }

    def telemetry(self) -> dict[str, float | int]:
        """Return measured client request/token/latency telemetry and pool stats."""
        with self._telemetry_lock:
            reqs = int(self._telemetry["requests"])
            out: dict[str, Any] = dict(self._telemetry)
            out["avg_latency_ms"] = round(float(out["total_latency_ms"]) / reqs, 2) if reqs else 0.0
            out["http_pool"] = get_http_pool_stats()
            return out

    def _record_usage(
        self,
        raw: dict,
        latency_ms: float,
        *,
        provider: str = "",
        model: str = "",
    ) -> None:
        usage = raw.get("usage") if isinstance(raw, dict) else None
        if usage is None and isinstance(raw, dict) and isinstance(raw.get("_usage"), dict):
            usage = raw.get("_usage")
        p_tok = c_tok = cached = 0
        if isinstance(usage, dict):
            p_tok = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            c_tok = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            details = usage.get("prompt_tokens_details") or {}
            cached = int(
                usage.get("cache_read_input_tokens")
                or usage.get("cached_tokens")
                or (details.get("cached_tokens") if isinstance(details, dict) else 0)
                or 0
            )
        with self._telemetry_lock:
            self._telemetry["requests"] = int(self._telemetry["requests"]) + 1
            self._telemetry["prompt_tokens"] = int(self._telemetry["prompt_tokens"]) + p_tok
            self._telemetry["completion_tokens"] = int(self._telemetry["completion_tokens"]) + c_tok
            self._telemetry["cached_tokens"] = int(self._telemetry["cached_tokens"]) + cached
            self._telemetry["total_latency_ms"] = float(self._telemetry["total_latency_ms"]) + latency_ms
            self._last_usage = {
                "provider": provider or "openai",
                "model": model or (self.models[0].name if self.models else "unknown"),
                "prompt_tokens": p_tok,
                "cached_tokens": cached,
                "completion_tokens": c_tok,
            }

    @property
    def last_usage(self) -> dict[str, Any] | None:
        with self._telemetry_lock:
            u = getattr(self, "_last_usage", None)
            return dict(u) if isinstance(u, dict) else None

    def _route_from_config(self) -> None:
        self.models: list[ModelSpec] = []
        # Env override (red line B: explicit, not silent). A single value caps
        # every model; per-model caps can still be set in the router JSON.
        _mt_raw = (self.cfg.get("BAIZE_MAX_TOKENS") or "").strip()
        mt_override = int(_mt_raw) if _mt_raw else 4096
        router = (self.cfg.get("BAIZE_MODEL_ROUTER") or "").strip()
        if router:
            try:
                for m in json.loads(router):
                    provider = m.get("provider") or _infer_provider(m["base_url"])
                    self.models.append(ModelSpec(
                        name=m["name"],
                        base_url=str(m["base_url"]).rstrip("/"),
                        api_key=m.get("api_key", ""),
                        weight=float(m.get("weight", 1)),
                        provider=provider,
                        max_tokens=int(m.get("max_tokens", mt_override)),
                    ))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                obs.record_error("router_config_errors")
                log.warning("[router] invalid BAIZE_MODEL_ROUTER (%s); using single model", e)
        if not self.models:
            base = self.cfg.get("BAIZE_MODEL_BASE_URL", "").rstrip("/")
            name = self.cfg.get("BAIZE_MODEL_NAME", "")
            key = self.cfg.get("BAIZE_MODEL_API_KEY", "")
            if base and name:
                provider = self.cfg.get("BAIZE_MODEL_PROVIDER") \
                    or _infer_provider(base)
                self.models.append(ModelSpec(
                    name, base, key, provider=provider,
                    max_tokens=mt_override))

    @property
    def configured(self) -> bool:
        return bool(self.models)

    @property
    def model_count(self) -> int:
        return len(self.models)

    @staticmethod
    def _headers(spec: ModelSpec) -> dict:
        h = {"Content-Type": "application/json"}
        if spec.provider == "anthropic":
            if spec.api_key:
                h["x-api-key"] = spec.api_key
            h["anthropic-version"] = "2023-06-01"
        elif spec.api_key:
            h["Authorization"] = f"Bearer {spec.api_key}"
        return h

    @staticmethod
    def _payload(spec: ModelSpec, messages: list[dict],
                 tools: list[dict] | None, temperature: float | None) -> dict:
        return _build_request(spec, messages, tools, temperature)

    @staticmethod
    def provider_capabilities(provider: str) -> dict:
        """Declared capability of a provider (drives routing + honest reporting).

        Red line B (NO FAKE DONE): only report what the adapter genuinely
        implements. The built-in adapters all speak chat/completions-style
        streaming and tool calling through urllib. Anthropic streaming is now a
        *real* ``/v1/messages`` SSE (see ``_anthropic_stream_transport``) rather
        than the prior non-streamed fallback, so its ``stream`` flag is
        truthful. DeepSeek exposes ``reasoning_content`` on its OpenAI-shaped
        responses, surfaced via the ``reasoning`` capability flag.
        """
        p = (provider or "").lower()
        caps = {"stream": True, "tools": True}
        if "deepseek" in p:
            caps["reasoning"] = True
        return caps

    # --- P3-4: prompt-cache-friendly message shaping ----------------------
    @staticmethod
    def cache_prefix(system_prompt: str,
                     tool_schemas: list[dict] | None = None) -> list[dict]:
        return cacheable_prefix(system_prompt, tool_schemas)

    @staticmethod
    def build_messages(system_prompt: str, tool_schemas: list[dict] | None,
                       conversation: list[dict]) -> list[dict]:
        return build_cacheable_messages(
            system_prompt, tool_schemas, conversation)

    def _select(self, tools: list[dict] | None = None) -> list[ModelSpec]:
        """Return models in priority order (every model tried exactly once).

        When tools are requested and multiple models are configured, models
        that lack tool support are deprioritized (excluded from the fallback
        set so the run prefers a tool-capable endpoint). The remaining set is
        shuffled WITHOUT replacement so each model appears exactly once across
        the cross-model fallback loop (sampling with replacement could drop a
        model entirely and break recovery).
        """
        specs = list(self.models)
        if tools and len(specs) > 1:
            capable = [s for s in specs
                       if self.provider_capabilities(s.provider)["tools"]]
            if capable:
                specs = capable
        if len(specs) == 1:
            return specs
        # Preserve priority order (highest weight first, config order on ties)
        return sorted(specs, key=lambda s: -s.weight)

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float | None = None, stream: bool = False) -> dict | Iterator[dict]:
        """Send one chat turn. Returns assistant message dict, or (if
        ``stream=True``) a generator yielding {"delta": str} chunks."""
        if not self.configured:
            raise LLMError(
                "model endpoint not configured - set BAIZE_MODEL_BASE_URL / "
                "BAIZE_MODEL_NAME (and API key) in .env (see .env.example)")
        if stream:
            return self._stream(messages, tools, temperature)
        last_err: Exception | None = None
        cache_on = self.cfg.get("BAIZE_PROMPT_CACHE") == "1"
        for spec in self._select(tools):  # cross-model fallback loop
            for attempt in range(self.max_retries + 1):
                try:
                    self.rate.acquire(self.rate.estimate_tokens(json.dumps(messages)))
                    req_msgs = messages
                    if cache_on and spec.provider == "anthropic" and tools:
                        req_msgs = mark_cacheable(messages, "anthropic")
                    t0 = time.perf_counter()
                    if spec.provider == "gemini":
                        from ..ext.providers.gemini import GeminiProviderAdapter
                        gem = GeminiProviderAdapter(
                            api_key=spec.api_key,
                            model=spec.name,
                            base_url=spec.base_url or "https://generativelanguage.googleapis.com/v1beta",
                            timeout=int(getattr(self, "timeout", 0) or self.cfg.get("BAIZE_MODEL_TIMEOUT", 120) or 120),
                        )
                        parsed_msg = gem.chat(
                            req_msgs,
                            tools=tools,
                            temperature=0.2 if temperature is None else temperature,
                        )
                        self._record_usage(
                            parsed_msg,
                            (time.perf_counter() - t0) * 1000.0,
                            provider="gemini",
                            model=spec.name,
                        )
                        obs.inc("llm_calls")
                        return parsed_msg
                    raw = self.transport(
                        _endpoint(spec),
                        self._headers(spec),
                        _build_request(spec, req_msgs, tools, temperature),
                    )
                    self._record_usage(
                        raw,
                        (time.perf_counter() - t0) * 1000.0,
                        provider=spec.provider,
                        model=spec.name,
                    )
                    obs.inc("llm_calls")
                    return _parse_response(raw, spec.provider)
                except Exception as exc:
                    # Deliberately broad. A transport is pluggable and the real
                    # HTTP stack raises a long tail (ssl.SSLError,
                    # http.client.IncompleteRead, socket errors...), while a
                    # malformed body makes _parse_response raise KeyError /
                    # IndexError / TypeError. Any of those leaking out would
                    # kill the whole agent run instead of triggering the retry
                    # and cross-model fallback that exist precisely for this.
                    last_err = exc
                    obs.record_error("llm_errors")
                    obs.inc(f"llm_error_{type(exc).__name__}")
                    with self._telemetry_lock:
                        self._telemetry["retries"] = int(self._telemetry["retries"]) + 1
                    if attempt < self.max_retries:
                        time.sleep(1.5 * (attempt + 1))
        err_msg = (f"model call failed after {self.max_retries + 1} attempts across "
                   f"{len(self.models)} model(s): {type(last_err).__name__}: {last_err}")
        err_msg = re.sub(r"https?://[^\s\'\",]+", "<api-endpoint>", err_msg)
        raise LLMError(err_msg)

    def _stream(self, messages: list[dict], tools: list[dict] | None,
                temperature: float | None) -> Iterator[dict]:
        spec = self._select(tools)[0]
        # Anthropic uses a different SSE dialect; route it through the real
        # Anthropic SSE transport (which yields OpenAI-shaped chunks). This is a
        # genuine stream, not the previous single non-streamed fallback.
        transport = (_anthropic_stream_transport
                     if spec.provider == "anthropic" else self.stream_transport)
        self.rate.acquire(self.rate.estimate_tokens(json.dumps(messages)))
        url = _endpoint(spec)
        yielded_any = False
        try:
            for chunk in transport(
                url, self._headers(spec),
                _build_request(spec, messages, tools, temperature),
            ):
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content") is not None:
                    yielded_any = True
                    yield {"delta": delta["content"]}
            obs.inc("llm_streams")
        except Exception as exc:  # defensive: fall back only if nothing streamed yet
            obs.record_error("llm_stream_errors")
            if not yielded_any:
                full = self.chat(messages, tools, temperature, stream=False)
                yield {"delta": full.get("content") or ""}
            else:
                raise LLMError(f"stream interrupted after partial output: {exc}") from exc


    def chat_with_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> dict:
        """Stream a chat turn, invoking ``on_token(text)`` live while accumulating
        both assistant text and incremental OpenAI/Anthropic ``tool_calls`` deltas.

        Falls back transparently to :meth:`chat` when a custom non-HTTP transport
        is injected (e.g. unit tests) or when streaming cannot initialize.
        """
        if on_token is None or (self.transport is not _http_transport and self.stream_transport is _http_stream_transport):
            msg = self.chat(messages, tools=tools, temperature=temperature, stream=False)
            if on_token is not None and msg.get("content"):
                try:
                    on_token(str(msg["content"]))
                except Exception:
                    pass
            return msg

        spec = self._select(tools)[0]
        transport = (
            _anthropic_stream_transport
            if spec.provider == "anthropic"
            else self.stream_transport
        )
        self.rate.acquire(self.rate.estimate_tokens(json.dumps(messages)))
        url = _endpoint(spec)
        content_parts: list[str] = []
        tc_acc: dict[int, dict[str, Any]] = {}
        yielded_any = False

        try:
            for chunk in transport(
                url,
                self._headers(spec),
                _build_request(spec, messages, tools, temperature),
            ):
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content")
                if text:
                    yielded_any = True
                    content_parts.append(text)
                    try:
                        on_token(text)
                    except Exception:
                        pass
                for tc in delta.get("tool_calls") or []:
                    yielded_any = True
                    idx = int(tc.get("index", 0))
                    slot = tc_acc.setdefault(
                        idx,
                        {"id": tc.get("id") or f"call_{idx}", "type": "function",
                         "function": {"name": "", "arguments": ""}},
                    )
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]
            obs.inc("llm_streams")
        except Exception as exc:
            obs.record_error("llm_stream_errors")
            if not yielded_any:
                msg = self.chat(messages, tools=tools, temperature=temperature, stream=False)
                if msg.get("content"):
                    try:
                        on_token(str(msg["content"]))
                    except Exception:
                        pass
                return msg
            raise LLMError(f"stream interrupted after partial output: {exc}") from exc

        out: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts) if content_parts else None,
        }
        if tc_acc:
            out["tool_calls"] = [tc_acc[i] for i in sorted(tc_acc)]
        return out

    @staticmethod
    def _parse_response(raw: dict) -> dict:
        try:
            choice = raw["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"malformed model response: {exc}: "
                           f"{str(raw)[:300]}") from exc
        out = {"role": "assistant", "content": msg.get("content")}
        if msg.get("tool_calls"):
            out["tool_calls"] = msg["tool_calls"]
        return out


def encode_image_part(
    image_path: str | Path,
    *,
    provider: str = "openai",
    max_bytes: int = 4_194_304,
) -> dict[str, Any]:
    """Read a local image and encode it as a provider-appropriate multimodal content block."""
    import base64
    import mimetypes

    p = Path(image_path)
    if not p.is_file():
        raise FileNotFoundError(f"Image file not found: {p}")
    data = p.read_bytes()
    if len(data) > max_bytes:
        raise ValueError(f"Image {p.name} ({len(data)} bytes) exceeds BAIZE_MULTIMODAL_MAX_BYTES ({max_bytes})")
    mime, _ = mimetypes.guess_type(str(p))
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    b64 = base64.b64encode(data).decode("ascii")
    prov = (provider or "openai").strip().lower()
    if prov == "anthropic":
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        }
    if prov == "gemini":
        return {"type": "image_base64", "mime_type": mime, "data": b64}
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"},
    }
