"""Tests for V21 P2-2 multi-provider model breadth (zero deps)."""
import json

from baize.config import load_config
from baize.llm import LLMClient, _infer_provider, _to_anthropic_tool


def _client_with_models(models, transport):
    cfg = dict(load_config())
    cfg["BAIZE_MODEL_ROUTER"] = json.dumps(models)
    return LLMClient(cfg=cfg, transport=transport)


def test_infer_provider_from_url():
    assert _infer_provider("https://api.anthropic.com/v1") == "anthropic"
    assert _infer_provider("http://localhost:11434") == "ollama"
    assert _infer_provider("https://api.openai.com/v1") == "openai"


def test_anthropic_request_shape_and_parse():
    captured = {}

    def transport(url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        # anthropic-style response with text + tool_use blocks
        return {"content": [
            {"type": "text", "text": "thinking..."},
            {"type": "tool_use", "id": "t1", "name": "read_file",
             "input": {"path": "x.txt"}},
        ]}

    read_tool = {"type": "function", "function": {
        "name": "read_file",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}}}}}
    client = _client_with_models(
        [{"name": "claude", "base_url": "https://api.anthropic.com",
          "api_key": "k", "provider": "anthropic"}], transport)
    assert client.model_count == 1
    msg = client.chat([{"role": "system", "content": "be brief"},
                       {"role": "user", "content": "read x.txt"}],
                      tools=[read_tool])
    # system extracted to top-level, messages mapped to user/assistant only
    assert captured["payload"]["system"] == "be brief"
    assert all(m["role"] in ("user", "assistant")
               for m in captured["payload"]["messages"])
    assert "v1/messages" in captured["url"]
    assert captured["headers"].get("x-api-key") == "k"
    # normalized response
    assert msg["content"] == "thinking..."
    assert msg["tool_calls"][0]["function"]["name"] == "read_file"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"path": "x.txt"}


def test_ollama_uses_openai_shape():
    captured = {}

    def transport(url, headers, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "done", "role": "assistant"}}]}

    client = _client_with_models(
        [{"name": "llama", "base_url": "http://localhost:11434",
          "provider": "ollama"}], transport)
    msg = client.chat([{"role": "user", "content": "hi"}])
    assert "chat/completions" in captured["url"]
    assert msg["content"] == "done"


def test_openai_still_works():
    captured = {}

    def transport(url, headers, payload):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "ok", "role": "assistant"}}]}

    client = _client_with_models(
        [{"name": "gpt", "base_url": "https://api.openai.com/v1",
          "api_key": "k"}], transport)
    msg = client.chat([{"role": "system", "content": "s"},
                       {"role": "user", "content": "u"}], tools=[])
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert msg["content"] == "ok"


def test_capability_routing_prefers_tool_models():
    def transport(url, headers, payload):
        return {"choices": [{"message": {"content": "v", "role": "assistant"}}]}

    # one "legacy" (no tool support) and one "openai" (tool-capable)
    models = [
        {"name": "legacy", "base_url": "https://api.example.com", "provider": "legacy"},
        {"name": "modern", "base_url": "https://api.openai.com/v1", "provider": "openai"},
    ]
    client = _client_with_models(models, transport)
    # simulate a provider that lacks tool support
    client.provider_capabilities = lambda p: {"stream": True, "tools": p != "legacy"}
    order = client._select(tools=[{"type": "function", "function": {"name": "x"}}])
    # tool-capable model is selected; the incapable one is deprioritized
    # (capability-aware routing) when tools are required.
    assert order[0].name == "modern"
    assert "legacy" not in [s.name for s in order]
    # without tools, both remain eligible (weighted shuffle of all models)
    both = client._select(tools=None)
    assert len(both) == 2


def test_to_anthropic_tool_conversion():
    at = _to_anthropic_tool({"type": "function", "function": {
        "name": "f", "description": "d",
        "parameters": {"type": "object", "properties": {"a": {"type": "string"}}}}})
    assert at["name"] == "f"
    assert at["input_schema"]["properties"]["a"]["type"] == "string"


def test_multi_provider_is_stdlib_only():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "baize" / "llm.py"
    text = src.read_text(encoding="utf-8")
    for forbidden in ("import litellm", "import httpx", "import openai",
                      "import anthropic", "from litellm"):
        assert forbidden not in text, f"forbidden import: {forbidden}"
