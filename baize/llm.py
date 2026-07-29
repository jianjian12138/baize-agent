"""Model-agnostic LLM client (OpenAI-compatible chat completions).

Design borrowed from hermes-agent: no vendor lock-in. Any endpoint that
speaks the OpenAI chat-completions dialect works (OpenAI, OpenRouter,
Ollama, vLLM, Nous Portal, local gateways ...).

Stdlib only: urllib for transport. The transport is injectable so the
agent loop can be tested deterministically with a scripted fake model —
the request-building, retry and response-parsing logic here is always
exercised for real.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from .config import load_config

Transport = Callable[[str, dict, dict], dict]
"""Transport signature: (url, headers, payload) -> parsed response dict."""


class LLMError(RuntimeError):
    """Raised when the model endpoint cannot produce a usable response."""


def _http_transport(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


class LLMClient:
    """Minimal chat-completions client with native tool-calling support."""

    def __init__(self, cfg: dict | None = None, transport: Transport | None = None):
        cfg = cfg or load_config()
        self.base_url = cfg.get("BAIZE_MODEL_BASE_URL", "").rstrip("/")
        self.api_key = cfg.get("BAIZE_MODEL_API_KEY", "")
        self.model = cfg.get("BAIZE_MODEL_NAME", "")
        self.max_retries = int(cfg.get("BAIZE_LLM_MAX_RETRIES", "2"))
        self.transport = transport or _http_transport

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float | None = None) -> dict:
        """Send one chat turn. Returns the assistant message dict.

        The returned dict follows the OpenAI shape:
        {"role": "assistant", "content": str|None, "tool_calls": [...]?}
        """
        if not self.configured:
            raise LLMError(
                "model endpoint not configured - set BAIZE_MODEL_BASE_URL "
                "and BAIZE_MODEL_NAME in .env (see .env.example)")

        payload: dict = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.transport(url, headers, payload)
                return self._parse_response(raw)
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, json.JSONDecodeError) as exc:
                last_err = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"model call failed after {self.max_retries + 1} "
                       f"attempts: {last_err}")

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
