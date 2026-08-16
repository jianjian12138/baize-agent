# baize-agent 规格说明

## 概述

自主 Agent 循环（V19 内核，V22 扩展）：思考→工具→观察→迭代，直至给出最终回答或触达步数上限。
会话以 pi 式 append-only JSONL 持久化，崩溃不丢状态、任意会话可按 id 续跑；
启动时自动注入技能索引提示与相关持久记忆（环境感知启动）。

**V22 插件化架构**：每个核心单元（model / tool / skill / session / sandbox / loop /
scheduler / ui / storage）均被描述成统一 `Component` 契约，由 `CompositionKernel`
从 `BAIZE_COMPONENTS` 装配。`Agent` 保留构造注入（`client=`/`registry=`/`session=`/
`loop_strategy=`），`Runtime` 单例仅作可选装配助手——两套路径并存，互不影响可测性。
`BAIZE_MODE` 命名模式（coding / eval / autonomous / safe-review）是预设的
「组件集 + 自治级别 + 工具 allow-list + plan_mode」配置 bundle，显式 `BAIZE_MODE`
优先于标量自治滑块。

## 接口

- `Session(session_id=None, cfg=None)`：JSONL 会话；`append(message, kind)`
  即写即落盘；`Session.list_sessions()` 列出全部会话。
- `Agent(role, cfg, client, registry, session, on_event, loop_strategy=None)`
- `Agent.run(goal, extra_system="") -> AgentResult`
  （`session_id / final_text / steps / tool_calls / stopped_reason / transcript`）。
- `build_system_prompt(role, cfg, registry, extra) -> str`：
  role ∈ {director, executor, verifier}。
- 组合内核：`baize.component.CompositionKernel(cfg).assemble() -> Runtime`；
  `get_runtime()` / `get_kernel()` 进程级单例（装配一次）。
- 命名模式：`baize.modes.resolve_mode(cfg) -> bundle`（autonomy / plan_mode / loop）。
- CLI：`baize run "<goal>" [--resume <id>]`、`baize sessions [<id>]`、`baize gate`。
- 配置项：`BAIZE_AGENT_MAX_STEPS` / `BAIZE_SESSIONS_DIR` / `BAIZE_COMPONENTS`
  （组件覆盖，`module.path:ClassName` 或内置 kind 名）/ `BAIZE_MODE`
  （coding / eval / autonomous / safe-review，显式优先于滑块）/ `BAIZE_PLUGINS_DIR`
  （额外组件/插件根）。

## 行为规约

1. 模型返回纯文本（无 tool_calls）即为最终回答，`stopped_reason="final"`。
2. 模型返回 tool_calls 时逐个执行，观察值以 `role=tool` 消息回填（截断 8000 字符），继续下一轮。
3. 步数达到 `BAIZE_AGENT_MAX_STEPS` 时强制停止，`stopped_reason="max_steps"`——防失控。
4. 未知工具调用不崩溃：ERROR 观察值回填，模型可自行纠正。
5. 每条消息在产生的瞬间写入 JSONL；按 id 重建 `Session` 可还原完整消息序列。
6. 续跑会话不重复注入 system prompt（全程仅 1 条 system 消息）。
7. 新会话首轮自动注入与 goal 相关的持久记忆（`recall_context`）。
8. system prompt 必须包含角色指令、可用工具清单与 NO FAKE DONE（verifier）。
9. LLM 调用失败时 `stopped_reason="error"`，错误写入会话——不伪造成功。

## 边界与异常

- JSONL 中损坏行在加载时跳过，不阻断会话恢复。
- 工具参数 JSON 解析失败按空参数处理（工具层会报 bad arguments）。

## 测试映射

| 规约 | 测试 |
|------|------|
| 1, 2 | `tests/test_agent.py::test_direct_final_answer / test_tool_loop_and_observation_feedback` |
| 3 | `tests/test_agent.py::test_max_steps_guard` |
| 4 | `tests/test_agent.py::test_unknown_tool_becomes_observation_not_crash` |
| 5, 6 | `tests/test_agent.py::test_session_persisted_and_resumable` |
| 7 | `tests/test_agent.py::test_memory_injected_into_first_turn` |
| 8 | `tests/test_agent.py::test_system_prompt_mentions_tools_and_role` |
| V22 组合内核装配 + 协议校验 + 显式 fail-closed | `tests/test_component.py` |
| V22 命名模式解析 + 显式优先于滑块 | `tests/test_modes.py` |
| V22 组件自动发现 + 隔离回退 | `tests/test_plugin_discovery.py` |
| CLI | `tests/test_cli.py`（run/sessions 脚本化端到端） |
