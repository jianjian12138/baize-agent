"""Model-agnostic LLM client (OpenAI-compatible chat completions) — V20.

Design borrowed from hermes-agent: no vendor lock-in. Any endpoint speaking the
OpenAI chat-completions dialect works (OpenAI, OpenRouter, Ollama, vLLM ...).

V20 additions over V19:
- Multi-model router with weighted selection and cross-model fallback.
- Streaming output (SSE) via ``chat(..., stream=True)``.
- Rate limiting (requests/min and tokens/min) with bounded backoff.

Stdlib only; the transport is injectable so the agent loop can be tested
deterministically with a scripted fake model — request-building, retry,
fallback and response-parsing are always exercised for real.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import http.client
from dataclasses import dataclass
from random import shuffle
from typing import Callable, Iterator

from .config import load_config
from .logging_setup import get_logger
from .observability import obs
from .chaos import Chaos

log = get_logger("llm")

Transport = Callable[[str, dict, dict], dict]
StreamTransport = Callable[[str, dict, dict], Iterator[dict]]


class LLMError(RuntimeError):
    """Raised when the model endpoint cannot produce a usable response."""


@dataclass
class ModelSpec:
    name: str
    base_url: str
    api_key: str = ""
    weight: float = 1.0
    provider: str = "openai"   # openai | anthropic | ollama | deepseek
    max_tokens: int = 4096      # per-model cap; env BAIZE_MAX_TOKENS overrides at load


class RateLimiter:
    """Sliding-window rate limiter for requests/min and tokens/min (stdlib)."""

    def __init__(self, rpm: int, tpm: int) -> None:
        self.rpm = rpm
        self.tpm = tpm
        self._reqs: list[float] = []
        self._tokens: list[tuple[float, int]] = []

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def acquire(self, tokens: int = 0) -> None:
        now = time.time()
        self._reqs = [t for t in self._reqs if now - t < 60]
        self._tokens = [(t, n) for (t, n) in self._tokens if now - t < 60]
        if self.rpm and len(self._reqs) >= self.rpm:
            wait = 60 - (now - self._reqs[0])
            if wait > 0:
                time.sleep(min(wait, 5))
        if self.tpm and sum(n for _, n in self._tokens) + tokens > self.tpm:
            time.sleep(1)  # simple backoff
        self._reqs.append(time.time())
        if tokens:
            self._tokens.append((time.time(), tokens))


def _infer_provider(base_url: str) -> str:
    """Best-effort provider detection from the endpoint URL (zero deps)."""
    u = (base_url or "").lower()
    if "anthropic" in u or "claude" in u:
        return "anthropic"
    if "ollama" in u or ":11434" in u:
        return "ollama"
    return "openai"


def _http_transport(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    convo = [{"role": m["role"], "content": m["content"]}
             for m in messages if m.get("role") in ("user", "assistant")]
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
    try:
        conn.request("POST", parsed.path, body=body, headers=headers)
        resp = conn.getresponse()
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
    try:
        conn.request("POST", parsed.path, body=body, headers=headers)
        resp = conn.getresponse()
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
        from . import prompt_cache
        return prompt_cache.cacheable_prefix(system_prompt, tool_schemas)

    @staticmethod
    def build_messages(system_prompt: str, tool_schemas: list[dict] | None,
                       conversation: list[dict]) -> list[dict]:
        from . import prompt_cache
        return prompt_cache.build_cacheable_messages(
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
        order = specs[:]
        shuffle(order)
        return order

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
                        from . import prompt_cache
                        req_msgs = prompt_cache.mark_cacheable(messages, "anthropic")
                    raw = self.transport(
                        _endpoint(spec),
                        self._headers(spec),
                        _build_request(spec, req_msgs, tools, temperature),
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
                    if attempt < self.max_retries:
                        time.sleep(1.5 * (attempt + 1))
        raise LLMError(
            f"model call failed after {self.max_retries + 1} attempts across "
            f"{len(self.models)} model(s): {type(last_err).__name__}: {last_err}")

    def _stream(self, messages: list[dict], tools: list[dict] | None,
                temperature: float | None) -> Iterator[dict]:
        spec = self._select()[0]
        # Anthropic uses a different SSE dialect; route it through the real
        # Anthropic SSE transport (which yields OpenAI-shaped chunks). This is a
        # genuine stream, not the previous single non-streamed fallback.
        transport = (_anthropic_stream_transport
                     if spec.provider == "anthropic" else self.stream_transport)
        self.rate.acquire(self.rate.estimate_tokens(json.dumps(messages)))
        url = _endpoint(spec)
        try:
            for chunk in transport(
                url, self._headers(spec),
                _build_request(spec, messages, tools, temperature),
            ):
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content") is not None:
                    yield {"delta": delta["content"]}
            obs.inc("llm_streams")
        except Exception:  # defensive: fall back to non-stream
            obs.record_error("llm_stream_errors")
            full = self.chat(messages, tools, temperature, stream=False)
            yield {"delta": full.get("content") or ""}

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
