# baize/ext — 扩展目录(V25 起步空壳)

本目录是 V25「生态接入 + 可见性」的扩展落点。**W1 仅为空壳**,后续 F3–F6 在此新增子模块。

## 红线(来自 V25 升级计划 §5)

- **A 零依赖**:`baize/ext/` 下每个模块只能用 Python 标准库,禁止任何第三方运行时依赖。
- **C ext fail-closed**:核心 `baize/` **永不**顶层 `import baize.ext`;扩展模块函数体内延迟 import,缺失即 skip,不阻断 422 基线。
- **D 外科手术**:核心运行时(`agent`/`cli`/`serve`/`llm`/`orchestrator`/`plugin`)**不动**,仅新增。

## 计划落点(W1–W4,详见 `docs/baize-agent-V25升级计划.md`)

| 子模块 | 功能 | Week | 状态 |
| --- | --- | --- | --- |
| `mcp/transport.py` | stdio JSON-RPC 2.0 + Content-Length 分帧(纯 stdlib `subprocess`+`json`) | W2–W3 | 待建 |
| `mcp/client.py` | initialize 握手(protocolVersion 协商 + capabilities 交换 + `notifications/initialized`) | W2–W3 | 待建 |
| `mcp/server.py` | 暴露 baize skills 给 Claude Desktop/Cursor,接入既有 `ToolRegistry` | W2–W3 | 待建 |
| `providers/` | 非 OpenAI 兼容厂商薄适配(Anthropic 流式 / DeepSeek reasoning_content / provider_capabilities 如实上报) | W2–W3 | 待建 |
| (总线收口) | 全部经 `plugin.discover` + `CompositionKernel.add_component` | W3 | 待建 |

## 静态门禁(由 F7/W3 接入 CI)

- `baize/*.py` 无顶层 `import baize.ext`(grep 强制)
- `pyproject.toml` `norecursedirs` 含 `baize/ext/`(避免默认发现破坏零回归)
- ext 测试 `importorskip` 守卫(缺失 skip 不阻断 422 基线)

> 本目录当前为空壳(`__init__.py` 仅有文档字符串,无顶层 import),`git ls-files` 可见即视为 W1 起步判据达成。
