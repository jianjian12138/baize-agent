# baize-llm 规格说明

## 概述

模型无关的 OpenAI 兼容 chat-completions 客户端（纯 stdlib），任何兼容端点
（OpenAI / OpenRouter / Ollama / vLLM / 本地网关）均可接入，transport 可注入以支持确定性测试。

## 接口

- `LLMClient(cfg=None, transport=None)`
- `LLMClient.configured -> bool`：`BAIZE_MODEL_BASE_URL` 与 `BAIZE_MODEL_NAME` 均非空。
- `LLMClient.chat(messages, tools=None, temperature=None) -> dict`：
  返回 `{"role": "assistant", "content": str|None, "tool_calls": [...]?}`。
- 配置项：`BAIZE_MODEL_BASE_URL` / `BAIZE_MODEL_API_KEY` / `BAIZE_MODEL_NAME` / `BAIZE_LLM_MAX_RETRIES`。

## 行为规约

1. 未配置端点时调用 `chat` 必须抛出 `LLMError`，不得静默降级或伪造响应。
2. 请求 URL 为 `{base_url}/chat/completions`；有 api_key 时携带 `Authorization: Bearer`。
3. 传入 `tools` 时原样放入 payload 的 `tools` 字段（OpenAI tools 格式）。
4. 网络/超时/JSON 解析失败按 `BAIZE_LLM_MAX_RETRIES` 重试（退避递增），耗尽后抛 `LLMError` 并携带最后一次错误。
5. 响应缺失 `choices[0].message` 时抛 `LLMError`（malformed response），不返回空对象。
6. transport 可注入：注入脚本化 transport 后，请求构建/解析/重试逻辑仍真实执行。

## 边界与异常

- base_url 末尾斜杠自动剥离。
- `tool_calls` 缺失时返回 dict 不含该键。

## 测试映射

| 规约 | 测试 |
|------|------|
| 1, 5 | `tests/test_llm.py`（未配置报错 / malformed 响应） |
| 2, 3, 6 | `tests/test_llm.py`（payload 构建与脚本化 transport） |
| 4 | `tests/test_llm.py`（重试后成功 / 耗尽抛错） |
