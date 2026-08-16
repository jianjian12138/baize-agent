# Baize Agent V21 · P1–P3 实施计划（含开源对标）

> 状态：计划阶段（plan-first）。本文档待审阅批准；批准后从 **#68 P1-1 Hooks** 起逐步落地。
> 适用铁律：**纯 stdlib 零依赖白盒不可破**；**NO FAKE DONE（诚实门禁）不可破**；新能力优先纯 stdlib，系统接口走可选适配层默认关闭；宿主 runtime 无 pytest（用隔离 venv 跑测试）。
> 调研日期：2026-08-14（Web 实测 + 既有 V21 路线图研究）。

---

## 一、开源对标结论（2026-08-14 调研）

| 能力 | Claude Code | Codex CLI | hermes-agent | pi-agent | deepseek-harness | baize 现状 |
|---|---|---|---|---|---|---|
| Hooks 生命周期 | **30+ 事件 / 5 handler / exit 码语义** | 有 hooks(7 类事件) | 无（靠规约） | 无 | 无 | `on_event` 雏形（仅 phase 事件） |
| MCP 客户端 | 官方 stdio/http/sse | 无 | 无 | 无 | 有（Cordis 一切皆插件） | **无（本期补 #69）** |
| 子 Agent 定义 | markdown frontmatter（tools/disallowedTools/model/permissionMode） | subagents | 角色协议 | 角色协议 | 插件式 | Orchestrator 内 Agent(role=) |
| Plan Mode | 只读探索→审批 | 无（autonomy） | 无 | 无 | 无 | 无（本期补 #72） |
| 多 Provider | 单 Anthropic | 多（oss 本地） | 模型无关 | 模型无关 | 多 | LLMClient 多模型路由（OpenAI 兼容） |
| Automations | 无内建 | 无 | 无 | 无 | 无 | 无（本期补 #74） |
| 自进化技能 | skills 市场 | 无 | 技能自改进 | 技能自改进 | 无 | rag.record_skill_outcome（零调用点） |
| 诚实门禁 | 无强调 | 无 | 无 | 无 | 无 | **NO FAKE DONE / Verifier / manifest（护城河）** |

**关键事实（来自 2026-08-14 Web 调研，非臆测）：**
1. **Hooks 是"模型无法违背的硬规则"**：CLAUDE.md 是建议，PreToolUse hook 是担保。事件分五拍：session / turn / tool(agentic loop) / subagent / file。handler 类型：command（shell，stdin 收 JSON、exit 码出决策）、HTTP（POST 决策）、MCP、prompt（让模型判）、agent（起子 agent 核验）。`PreToolUse` 退出码 **2=阻断**（stderr 回显），其他非 0=非阻断。
2. **MCP 纯 stdlib 可行**：`subprocess.Popen([cmd], stdin=PIPE, stdout=PIPE)` + NDJSON（每行一条 JSON-RPC 2.0）。握手顺序：`initialize`(protocolVersion "2025-03-26" 或 "2024-11-05") → `notifications/initialized` → `tools/list` → `tools/call`。传输：stdio（本地进程）/ http / sse（远程）。**零依赖即可实现客户端**。
3. **子 Agent frontmatter**：`name/description/tools/disallowedTools/model(sonnet|opus|haiku|inherit)/permissionMode(default|acceptEdits|dontAsk|bypassPermissions)/skills/hooks`，隔离上下文窗口，只回摘要。
4. **Plan Mode + 自治滑块**：Claude Code 用只读探索后请用户批；autonomy 即 `permissionMode` 梯度。Cursor/Codex 类似。
5. **多 Provider 标准解 litellm 但非 stdlib**：零依赖路线必须自写薄抽象——OpenAI 兼容 HTTP（urllib）+ 原生 Anthropic/local(Ollama) 适配，已有 `LLMClient` 多模型路由可扩展。
6. **诚实自进化**：hermes/pi 有技能自改进，但常陷"假绿"。baize 必须在 `verify_skill_draft` rubric + `rag.record_skill_outcome` 真实调用点（专家评审高优先项）之上做，禁止无数据声称成功率提升。

**白泽护城河（对标后更坚定）：** 唯一零运行时依赖；唯一把 NO FAKE DONE / Verifier 独立核验 / manifest 物理核验做成门禁；双层架构（规约 + 运行时）可外挂。P1–P3 不堆功能，补"互操作/可扩展/可产品化"三地基，并深化护城河。

---

## 二、P1–P3 总览（#68–#79 映射）

| 阶段 | Task | 标题 | 对标锚点 |
|---|---|---|---|
| P1-1 | #68 | Hooks 生命周期事件体系 | Claude Code 30+ 事件 / exit 码语义 |
| P1-2 | #69 | MCP 客户端（纯 stdlib） | MCP stdio JSON-RPC（零依赖可行） |
| P1-3 | #70 | 子 Agent 定义格式 + 隔离 | Claude Code subagent frontmatter |
| P1-4 | #71 | 诚实版技能自进化增强 | hermes/pi 自改进 + 诚实 rubric |
| P2-1 | #72 | 显式 Plan Mode + 自治滑块 | Claude Code plan mode / permissionMode |
| P2-2 | #73 | 多 Provider 模型广度 | litellm 思路（自写零依赖抽象） |
| P2-3 | #74 | Automations 定时任务 | 无主流内建 → 自研调度 |
| P2-4 | #75 | 会话分叉/压缩 UI 增强 | 会话管理 UI |
| P3-1 | #76 | 公开基准 + 本地 bench 用例 | 防 Terminal-Bench 刷分 |
| P3-2 | #77 | 上下文/长程管理增强 | 压缩/窗口管理 |
| P3-3 | #78 | NO FAKE DONE 门禁产品化 | 本期已建 `scripts/coverage_gate.py` |
| P3-4 | #79 | prompt cache 友好 + token 效率 | 缓存前缀 / token 核算 |

**推进顺序：P1（地基）→ P2（深化）→ P3（收口）。** 每阶段内按编号；每个 task 落地后跑隔离 venv 测试并复测全量覆盖率（门禁 ≥85%，当前 93%）。

---

## 三、各 Task 设计要点 + 验收标准

### P1 — 互操作 / 可扩展地基

#### #68 P1-1 Hooks 生命周期事件体系
- **设计**：在现有 `Agent/Orchestrator.on_event` 上扩成正式生命周期事件总线。事件名（首批，可扩展）：`session_start` / `user_prompt_submit` / `pre_tool_use` / `post_tool_use` / `post_tool_use_failure` / `pre_subtask` / `post_subtask` / `session_end` / `pre_compact`。
  - `HookRegistry` 从 `.baize/hooks.json`（可提交）或 `settings` 加载；每条 = `{event, matcher, handler}`。
  - **handler 类型（零依赖）**：`command`（shell，stdin 收 JSON，exit 0=放行 / 2=阻断 / 其他=非阻断，stderr 回显）为首选；`inline`（baize 内可调用 python callable）作可选。HTTP/MCP handler 留接口但默认关闭（不引入依赖）。
  - **matcher**：工具名 / 正则 / `*`；仅 `pre_tool_use`/`post_tool_use` 吃 matcher。
  - **fail-closed**：hook 抛异常或超时 → 视为"阻断/记录"，绝不静默放行（诚实）。`pre_tool_use` 返回 deny → 工具不执行，Agent 收到 `systemMessage` 原因。
- **验收**：① 事件总线覆盖全部首批事件且单测通过；② `command` hook 退出码 0/2/其他 三态语义正确；③ `pre_tool_use` deny 真实阻断工具（含一个"恶意命令拦截"集成测试，复用 `tools.DENY_PATTERNS` 思路）；④ hook 崩溃 fail-closed 单测；⑤ 不引入任何第三方依赖。

#### #69 P1-2 MCP 客户端（纯 stdlib）
- **设计**：新增 `baize/mcp.py`，`MCPClient`（stdio 传输）：`start(cmd,args)` → `initialize` → `notifications/initialized` → `list_tools` → `call_tool`，NDJSON 收发（`subprocess.PIPE` + `json` + 行缓冲）。把发现的 tools 注册进 `ToolRegistry`（前缀 `mcp__<server>__*`），Agent 即可调用。
  - **fail-closed（专家评审高优先风险）**：MCP server 是不可信代码，启用即信任边界。必须对子进程：① 在沙箱/受限环境启动；② 捕获 stderr；③ 崩溃/超时 → 该 tool 返回 `ERROR`，**绝不**冒泡成 Agent 崩溃；④ server 清单白名单（默认空，显式启用）。
  - http/sse 传输留接口默认关闭（避免引入 `httpx` 等依赖；远程走可选适配层）。
- **验收**：① 纯 stdlib（无 `mcp` SDK import）单测通过（用本地回显 mock server 子进程）；② `tools/list`/`tools/call` 真实往返；③ server 崩溃 → tool ERROR 不崩 Agent；④ 注册进 ToolRegistry 且经 `run_checks` 可达；⑤ 默认禁用、需显式启用。

#### #70 P1-3 子 Agent 定义格式 + 隔离
- **设计**：定义子 Agent 声明格式（YAML 或 markdown frontmatter，零依赖用 YAML 解析——stdlib 无 YAML，故用**简单 `key: value` frontmatter** 或 JSON，避免引第三方）。字段：`name/description/tools/disallowed_tools/model/permission_mode/skills`。复用 `Orchestrator._spawn` 生成隔离 `Agent`（独立 `Session`、独立上下文、限定工具集）。
  - 与现有 `TeamMemory` 打通：子 agent 可选择性共享 blackboard。
- **验收**：① 能从声明文件实例化隔离 Agent 并限定工具；② 子 agent 上下文隔离（不污染主会话）单测；③ 与 Orchestrator 编排兼容；④ 零依赖。

#### #71 P1-4 诚实版技能自进化增强
- **设计**：① 先补 `rag.record_skill_outcome` **真实调用点**（专家评审前置条件，否则成功率无数据）；② `verify_skill_draft` rubric（经验质量校验：是否含可执行步骤、是否声明依赖、是否过 `manifest` 核验）；③ 草稿生成 + 真实回放验证，成功率来自实测，禁止无数据声称提升。
- **验收**：① `record_skill_outcome` 在技能执行路径有 ≥1 真实调用点；② `verify_skill_draft` 拒绝低质草稿单测；③ 自进化产出经 Verifier 独立核验；④ 无"假绿"（任何成功率声明都有回放数据支撑）。

### P2 — 深化零依赖白盒护城河

#### #72 P2-1 显式 Plan Mode + 自治滑块
- **设计**：`plan_mode` 旗帜——开启时 Agent 只做只读探索（`read_file`/`list_dir`/`search`），生成计划经 `user_prompt_submit`/审批 hook 请用户确认后再执行。`autonomy` 梯度（映射 `permission_mode`）：`supervised`(每步确认) → `balanced`(危险操作确认) → `autonomous`(仅 fail-closed 拦截)。**自治滑块必须有成本上限**（专家评审风险：token 失控），超阈值强制降级。
- **验收**：① plan mode 下危险写操作被拦单测；② 三档 autonomy 行为差异单测；③ 成本上限触发降级单测；④ 零依赖。

#### #73 P2-2 多 Provider 模型广度
- **设计**：扩展 `LLMClient` 支持 Anthropic 原生、本地 Ollama、OpenAI 兼容网关，统一为 `urllib` HTTP（零依赖）。provider 能力探测（流式/函数调用/多模型）驱动路由。
- **验收**：① 新增 ≥2 个 provider 适配单测（mock transport）；② 路由按能力/配置选择；③ 零依赖；④ 不破坏现有多模型路由。

#### #74 P2-3 Automations 定时任务
- **设计**：轻量调度器（stdlib `threading` + 时间戳，不用 `cron` 依赖）：周期目标（cron rrule 或 interval）、作用域、启用/失效、validFrom/validUntil。触发走 `on_event` + 现有 Agent/Orchestrator 运行。fail-closed：调度器崩溃不影响主循环。
- **验收**：① 周期触发单测（用快 interval 或 mock 时钟）；② 启用/失效/有效期逻辑；③ 崩溃隔离；④ 零依赖。

#### #75 P2-4 会话分叉/压缩 UI 增强
- **设计**：`dashboard`/TUI 支持会话分叉（branch）与压缩可视化（压缩前后 token、保留摘要）。后端复用 `memory.compress` + `Session`。
- **验收**：① 分叉/压缩 API 单测；② UI 变更（HTML/文本）渲染；③ 零依赖。

### P3 — 产品化 / 收口

#### #76 P3-1 公开基准 + 本地 bench 用例
- **设计**：`bench.py` 内置 **5–10 个本地端到端任务**（自带预期/可重放），防 Terminal-Bench 刷分（专家评审）。结果进 `obs` + 报告。
- **验收**：① ≥5 本地 bench 任务可跑且断言明确；② 与公开基准对照；③ 零依赖；④ 不假绿（任务真实执行）。

#### #77 P3-2 上下文/长程管理增强
- **设计**：增强 `compress_context`（专家评审：截断至 400 字可能销毁 Verifier 证据 → 改为结构化保留证据字段）；长程记忆分层（热/温/冷）。
- **验收**：① 压缩保留 Verifier 证据单测；② 长程分层读取；③ 零依赖。

#### #78 P3-3 NO FAKE DONE 门禁产品化
- **设计**：把本期已建的 `scripts/coverage_gate.py` 升为一等公民：① `baize.cli gate` 子命令；② `dashboard` 显示门禁状态徽标（通过/失败/未达）；③ manifest 门禁补"非空 + 时间戳"校验（专家评审风险 6），杜绝陈旧文件假绿。
- **验收**：① `cli gate` 跑通且低于阈值 exit 1；② dashboard 徽标；③ manifest 非空+时间校验单测；④ 零依赖。

#### #79 P3-4 prompt cache 友好 + token 效率
- **设计**：系统提示分"可缓存前缀"（角色/规约/工具 schema 稳定段）与"易变段"，提升缓存命中；轻量 token 估算（不引 tiktoken，用近似字符/词估算并标注近似）；prompt 模板去冗余。
- **验收**：① 可缓存前缀结构单测；② token 估算函数单测（标注近似）；③ 不引第三方；④ 不降低 Verifier 质量。

---

## 四、刻意不做（呼应路线图 §"刻意不做"）
- 不引入 MCP HTTP/SSE 远程传输依赖（默认关闭，留接口）。
- 不引入 litellm / httpx / yaml / tiktoken 等第三方（保持纯 stdlib）。
- 不堆"功能列表"式特性；每个能力必须有单测 + 真实回放，禁止假绿。
- 不做 Agent 团队去中心化自协调（Claude Code 实验特性）——白泽用 Orchestrator 中心式编排即可。

---

## 五、风险与诚实约束（贯穿 P1–P3）
1. **MCP server 是不可信代码**（专家评审）：启用即信任边界，必须沙箱 + 崩溃隔离 + 白名单。
2. **自治滑块无成本上限 → token 失控**：#72 强制成本上限降级。
3. **压缩截断销毁 Verifier 证据**：#77 改为结构化保留证据字段。
4. **自进化无数据支撑**：#71 先补 `record_skill_outcome` 调用点，任何成功率声明需回放数据。
5. **manifest 门禁只查存在**：#78 补非空 + 时间戳，杜绝陈旧文件假绿。
6. 所有新增能力默认关闭，显式启用；不破零依赖与 NO FAKE DONE。

---

## 六、本次交付 & 下一步
- **本次交付**：本计划文档（含开源对标 + #68–#79 设计/验收）。
- **下一步（待你批准）**：从 **#68 P1-1 Hooks 生命周期事件体系** 起，按"方案 → 实现 → 隔离 venv 单测 → 复测全量覆盖率 ≥85%"逐步推进，每完成一个 task 标记并汇报。
- 文档仍**本地不动**（你此前 `q-1` 决定），未推送 GitHub；GitHub 推送待你另行确认。
