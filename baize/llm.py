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
from random import choices
from typing import Callable, Iterator

from .config import load_config
from .observability import obs

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


def _http_transport(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_stream_transport(url: str, headers: dict, payload: dict) -> Iterator[dict]:
    """Real SSE reader for OpenAI-style streaming chat completions."""
    parsed = urllib.parse.urlparse(url)
    payload = dict(payload, stream=True)
    body = json.dumps(payload).encode("utf-8")
    port = 443 if parsed.scheme == "https" else 80
    conn = http.client.HTTPSConnection(parsed.netloc, port, timeout=120) \
        if parsed.scheme == "https" else \
        http.client.HTTPConnection(parsed.netloc, port, timeout=120)
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
        self.transport = transport or _http_transport
        self.stream_transport = stream_transport or _http_stream_transport
        self._route_from_config()

    def _route_from_config(self) -> None:
        self.models: list[ModelSpec] = []
        router = (self.cfg.get("BAIZE_MODEL_ROUTER") or "").strip()
        if router:
            try:
                for m in json.loads(router):
                    self.models.append(ModelSpec(
                        name=m["name"],
                        base_url=str(m["base_url"]).rstrip("/"),
                        api_key=m.get("api_key", ""),
                        weight=float(m.get("weight", 1)),
                    ))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                obs.record_error("router_config_errors")
                print(f"[router] invalid BAIZE_MODEL_ROUTER ({e}); using single model")
        if not self.models:
            base = self.cfg.get("BAIZE_MODEL_BASE_URL", "").rstrip("/")
            name = self.cfg.get("BAIZE_MODEL_NAME", "")
            key = self.cfg.get("BAIZE_MODEL_API_KEY", "")
            if base and name:
                self.models.append(ModelSpec(name, base, key))

    @property
    def configured(self) -> bool:
        return bool(self.models)

    @property
    def model_count(self) -> int:
        return len(self.models)

    def _select(self) -> ModelSpec:
        if len(self.models) == 1:
            return self.models[0]
        return choices(self.models, weights=[m.weight for m in self.models], k=1)[0]

    @staticmethod
    def _headers(spec: ModelSpec) -> dict:
        h = {"Content-Type": "application/json"}
        if spec.api_key:
            h["Authorization"] = f"Bearer {spec.api_key}"
        return h

    @staticmethod
    def _payload(spec: ModelSpec, messages: list[dict],
                 tools: list[dict] | None, temperature: float | None) -> dict:
        p: dict = {"model": spec.name, "messages": messages}
        if tools:
            p["tools"] = tools
        if temperature is not None:
            p["temperature"] = temperature
        return p

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
        for spec in self.models:  # cross-model fallback loop
            for attempt in range(self.max_retries + 1):
                try:
                    self.rate.acquire(self.rate.estimate_tokens(json.dumps(messages)))
                    raw = self.transport(
                        f"{spec.base_url}/chat/completions",
                        self._headers(spec),
                        self._payload(spec, messages, tools, temperature),
                    )
                    obs.inc("llm_calls")
                    return self._parse_response(raw)
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
        spec = self._select()
        self.rate.acquire(self.rate.estimate_tokens(json.dumps(messages)))
        url = f"{spec.base_url}/chat/completions"
        try:
            for chunk in self.stream_transport(
                url, self._headers(spec),
                self._payload(spec, messages, tools, temperature),
            ):
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content") is not None:
                    yield {"delta": delta["content"]}
            obs.inc("llm_streams")
        except Exception as e:  # defensive: fall back to non-stream
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
