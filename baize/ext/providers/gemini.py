"""V42.0.0 Helios — Native Google Gemini REST Provider Adapter (Pure Python Stdlib).

Speaks the native Gemini ``generateContent`` REST dialect over ``urllib.request``
with zero third-party SDK dependencies. Supports:
  - System instructions + multi-turn role translation (``user`` / ``model``)
  - Multimodal ``inlineData`` image parts alongside text
  - Function calling declarations (``functionDeclarations``) and ``functionCall`` / ``functionResponse``
  - Real usage accounting including ``cachedContentTokenCount``
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class GeminiProviderAdapter:
    """Pure-stdlib native Gemini REST adapter."""

    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: int = 90,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or "gemini-2.5-flash").strip()
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.timeout = int(timeout)

    def build_request_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Translate OpenAI-style messages + multimodal parts + tool schemas into Gemini JSON."""
        sys_parts: list[dict[str, Any]] = []
        contents: list[dict[str, Any]] = []

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content")
            if role == "system":
                if isinstance(content, str) and content.strip():
                    sys_parts.append({"text": content})
                elif isinstance(content, list):
                    for blk in content:
                        if isinstance(blk, dict) and blk.get("text"):
                            sys_parts.append({"text": str(blk["text"])})
                continue

            if role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": m.get("name") or m.get("tool_call_id") or "tool",
                                "response": {"output": str(content or "")},
                            }
                        }
                    ],
                })
                continue

            gem_role = "model" if role == "assistant" else "user"
            parts: list[dict[str, Any]] = []
            if isinstance(content, str) and content:
                parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    itype = item.get("type", "")
                    if itype == "text" and item.get("text"):
                        parts.append({"text": str(item["text"])})
                    elif itype == "image_base64":
                        parts.append({
                            "inlineData": {
                                "mimeType": item.get("mime_type", "image/png"),
                                "data": item.get("data", ""),
                            }
                        })
                    elif itype == "image_url":
                        url = str((item.get("image_url") or {}).get("url") or "")
                        if url.startswith("data:") and ";base64," in url:
                            hdr, b64 = url.split(";base64,", 1)
                            mime = hdr[5:] or "image/png"
                            parts.append({"inlineData": {"mimeType": mime, "data": b64}})

            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments") or "{}"
                try:
                    parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except Exception:
                    parsed_args = {}
                parts.append({"functionCall": {"name": fn.get("name", ""), "args": parsed_args}})

            if parts:
                contents.append({"role": gem_role, "parts": parts})

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": float(temperature)},
        }
        if sys_parts:
            body["systemInstruction"] = {"parts": sys_parts}

        if tools:
            decls: list[dict[str, Any]] = []
            for t in tools:
                fn = t.get("function") or {}
                if not fn.get("name"):
                    continue
                decls.append({
                    "name": fn["name"],
                    "description": fn.get("description") or "",
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                })
            if decls:
                body["tools"] = [{"functionDeclarations": decls}]
        return body

    def parse_response(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Convert Gemini ``generateContent`` JSON into Baize's normalized assistant message."""
        candidates = raw.get("candidates") or []
        text_chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        if candidates:
            parts = ((candidates[0].get("content") or {}).get("parts")) or []
            for idx, part in enumerate(parts):
                if "text" in part:
                    text_chunks.append(str(part["text"]))
                elif "functionCall" in part:
                    fc = part["functionCall"] or {}
                    tool_calls.append({
                        "id": f"gemini_call_{idx + 1}",
                        "type": "function",
                        "function": {
                            "name": str(fc.get("name") or ""),
                            "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False),
                        },
                    })

        um = raw.get("usageMetadata") or {}
        usage = {
            "prompt_tokens": int(um.get("promptTokenCount") or 0),
            "cached_tokens": int(um.get("cachedContentTokenCount") or 0),
            "completion_tokens": int(um.get("candidatesTokenCount") or 0),
        }
        msg: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(text_chunks),
            "_usage": usage,
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")
        body = self.build_request_body(messages, tools=tools, temperature=temperature)
        endpoint = f"{self.base_url}/models/{urllib.parse.quote(self.model, safe='')}:generateContent"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
        return self.parse_response(parsed)
