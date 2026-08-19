# Baize Agent V22 · 插件化架构计划（含 deepseek-harness / Cordis 对标）

> 状态：计划阶段（plan-first）。已交付"agent 工程师"评审（结论 **Approve-with-changes**），8 项设计补全已折回 §三/§七；待最终批准实施后从 **#95 V22-0 统一插件契约 + 组合内核** 起逐步落地。
> 适用铁律：**纯 stdlib 零依赖白盒不可破**；**NO FAKE DONE（诚实门禁）不可破**；新能力默认关闭、显式启用；宿主 runtime 无 pytest（用隔离 venv 跑测试）。
> 调研日期：2026-08-16（deepseek-harness v0.1 教程研读 + baize 现有 `plugin.py`/`agent.py`/`serve.py` 源码核对）。

---

## 一、对标结论：deepseek-harness「万物皆可插件」（Cordis）

| 维度 | DeepSeek Harness (Cordis) | baize 现状（源码核对） | 差距 / 判断 |
|---|---|---|---|
| 插件本质 | 统一可组合单元；模型/工具/技能/会话/沙箱/存储/Loop/调度/UI **全是同类插件**，由配置组合 | `baize/plugin.py` = 生命周期**钩子**模型（`on_load/on_agent_start/on_tool_call/on_error/on_unload`），从 `baize/plugins/` + `BAIZE_PLUGINS_DIR` 发现，失败隔离 | baize 插件**不能替换** LLM/Loop/沙箱/UI/存储——这些是 `agent.py`/`serve.py` 的**硬编码 import**。缺统一组合内核 |
| 配置装配 | 换大脑/界面只换插件，不改源码 | Plan Mode + 自治滑块（标量），无"模式 = 插件集" | harness「四模式 = 预设插件集」思想可落地 |
| 默认安全 | 读/文件/联网/进程约束**松**；第三方插件**默认可信**；创造模式**执行模型生成的 JS** | fail-closed + 作用域子 Agent registry + 密钥脱敏 + 沙箱 | **baize 更严，是护城河，绝不抄 harness 的弱点** |
| 依赖 / 可审计 | Node/JS、v0.1 破坏式更新、MIT | 纯 stdlib 白盒、MIT | **baize 零依赖是压倒性优势** |
| Provider 广度 | 38 条路由 | 3 条（OpenAI/Anthropic/Ollama，urllib） | 广度可增量补，不破零依赖 |

**关键事实（来自 2026-08-16 教程研读 + 源码核对，非臆测）：**
1. **Cordis = 插件元框架**，只负责插件的加载/卸载/依赖解析；具体能力全由插件提供，插件间通过"服务 + 事件"协作，由配置决定如何组合。换模型、换界面、加工具都只是换/装插件，不改 Harness 源码。
2. **harness 四模式 = 预设插件集**：标准（日常编程）、PTC（模型生成代码编排多轮工具调用）、极简（仅 shell+文件编辑，专为最小环境基准测试）、创造（直接执行模型生成 JS，高危默认不推荐）。选错模式体验差很多。
3. **harness 默认权限松 + 第三方插件默认可信 + 创造模式执行模型 JS**——三处均为已知安全弱点（教程第 10 篇自己警告）。
4. **harness 是 Node/JS、v0.1 开发者预览、明确破坏性更新**——其具体实现只能当灵感，不能当蓝图。

**baize 现状核对（已读源码）：**
- `baize/plugin.py` 是**钩子/观察者**模型：插件在 agent 生命周期事件上挂回调，适合横切关注点（日志、遥测、guardrail），但**无法替换核心单元**（LLM 客户端、Agent Loop、沙箱、存储、UI）。
- baize **单体能力已齐**：多 Provider(#73)、工具/技能/子 Agent(#70/#71)、Automations(#74)、Hooks(#68)、沙箱(`sandbox.py`)、密钥管理(`secrets.py`)、fail-closed、作用域子 Agent 隔离。
- **真正缺口**：缺一个**统一组合内核 + 配置驱动装配**。插件模型是"观察者"，不是"可替换核心单元"。

**白泽护城河（对标后更坚定）：** 唯一纯 stdlib 白盒（harness 是 Node/JS）；唯一 fail-closed + 作用域隔离 + 密钥脱敏（harness 默认松 + 插件默认可信）；唯一把 NO FAKE DONE / Verifier / manifest 物理核验做成门禁。V22 吸收 Cordis 的「统一组合」思想，**绝不**吸收其松权限 / 可信插件 / 执行模型 JS。

---

## 二、V22 总览（#95–#101 映射）

| 阶段 | Task | 标题 | 对标锚点 |
|---|---|---|---|
| V22-0 | #95 | 统一插件契约 + 组合内核 | Cordis 内核本土化 |
| V22-1 | #96 | Agent Loop 抽成可替换策略 | harness PTC 模式 |
| V22-2 | #97 | 命名模式 = 插件集（mode = component-set） | harness 四模式 |
| V22-3 | #98 | 沙箱 / 存储 / UI 统一暴露为组件 | Cordis 一切皆插件 |
| V22-4 | #99 | 组件发现 / 市场机制增强（严格隔离） | dsh-plugin 生态（但不可信） |
| V22-5 | #100 | 文档 / 规格升级 + 写一个 baize component 教程 | harness 写 dsh-plugin |
| V22-6 | #101 | 测试验证 + 诚实门禁收口 | 复用 #78 gate |

**推进顺序：V22-0（内核地基）→ V22-1/2/3（核心单元插件化）→ V22-4（生态）→ V22-5/6（文档 + 收口）。** 每阶段内按编号；每个 task 落地后跑隔离 venv 测试并复测全量覆盖率（门禁 ≥85%，当前 89%）。

---

## 三、各 Task 设计要点 + 验收标准

### V22-0 — 统一组合内核地基

#### #95 V22-0 统一插件契约 + 组合内核
- **设计**：引入**统一 `Component` 契约**（dataclass/spec），字段：`kind`（**封闭**枚举：`model`/`tool`/`skill`/`session`/`sandbox`/`loop`/`scheduler`/`ui`/`storage`）、`name`、`provides`/`requires`（能力 id 列表）、`build(cfg) -> Any`（返回类型见下方循环导入处理）。
  - **每 `kind` 定义 `Protocol` 契约（评审修复②）**：`ModelAdapterProto`/`LoopStrategyProto`/`SandboxProto`/`SessionStoreProto`/`UIProto`/… 描述该单元必须的方法签名；`CompositionKernel` 装配后对实例做结构/类型校验，**拒绝 shape 不符的坏实现**。
  - **`CompositionKernel`**：① 内置「默认组件集」——把当前 `agent.py`/`serve.py` 硬编码单元**注册为默认组件**（`DefaultLLMAdapter`/`DefaultToolProvider`/`DefaultSkillProvider`/`DefaultSessionStore`/`DefaultSandbox`/`DefaultLoop`/`DefaultScheduler`/`DefaultWebUI`/`DefaultStorage`）；② 读 `BAIZE_COMPONENTS` 配置（list of `"module.path:ClassName"` 或内置名）**覆盖/新增**；③ 拓扑解析依赖，循环/缺失 → **fail-closed**；④ 装配出 `Runtime` 对象（持有已解析实例），`agent.py`/`serve.py` 改为从 `Runtime` 取用，而非直接 import。
  - **两套隔离语义（评审修复①，关键）**：
    - **显式覆盖组件**（用户经 `BAIZE_COMPONENTS` 指定替换某 `kind` 的内置）——其 `build()` 抛错 / 类型校验失败 → **整体 fail-closed（启动即阻断，exit 非 0）**，绝不静默降级到内置默认（这正是计划反对的 harness 式行为）。
    - **自动发现组件**（`plugin.py` `discover()` 从 `baize/plugins/` + `BAIZE_PLUGINS_DIR` 发现）——`build()` 抛错 → **记录 + 跳过**（沿用既有防御性隔离），不阻断 host。
    - 两者语义严格区分，杜绝静默降级到错误实现。
  - **消除循环导入（评审修复④）**：`Component.build()` 返回类型标注为 `Any`/惰性字符串解析，**不**在 `component.py` 反向 import 核心具体类型（`LLMClient`/`Agent`）；核心模块"注册自己为默认组件"走字符串引用，装配时再惰性解析。
  - **`BAIZE_COMPONENTS` 纳入 `config_schema.validate()`（评审修复③）**：该键与列表元素格式（`module.path:ClassName` 或内置名白名单）fail-fast 校验，绕过既有 `config_schema.py` 的校验属遗漏。
  - **serve 路径 Runtime 注入（评审修复⑤）**：`serve.py` 的 Handler **不得** per-request 重建内核；采用「模块级单例 `Runtime` 或 Handler 子类注入」，在 server 启动（`ThreadingHTTPServer` 构造）时装配一次，Handler 从单例 / 子类属性取用。
  - **保留 `Agent` 构造注入（评审修复⑥）**：**不**让 `Runtime` 成为唯一装配入口——`Agent(client=, registry=, session=, ...)` 的构造注入必须保留（这是 baize 隔离测试可测性的基础，`llm.py` transport 注入同理）；`Runtime` 仅作"可选装配助手"。
  - **不替换** `plugin.py` 的钩子体系——组件解决"核心单元可替换"，钩子解决"横切观察"，superset 关系。
  - **性能**：内核启动时装配一次，serve 路径绝不 per-request 重建。
- **验收**：① 内置集加载后 `agent` 行为不变（全量回归）；② stub 自定义 sandbox 经 `BAIZE_COMPONENTS` 替换内置、无需改 `agent.py`；③ **显式覆盖组件失效 → 启动 fail-closed 阻断**（单测）；④ 自动发现组件失效 → 记录+跳过、host 不崩（单测）；⑤ 每 `kind` 装配后类型校验拒绝坏实现（单测）；⑥ `BAIZE_COMPONENTS` 非法格式被 `config_schema.validate` 拒（单测）；⑦ 循环导入消除（导入测试）；⑧ 保留 `Agent` 构造注入 + serve 单例装配一次（单测）；⑨ 零依赖；⑩ 现有 `plugin.py` 钩子仍触发。

### V22-1 — 核心单元插件化

#### #96 V22-1 Agent Loop 抽成可替换策略（评审降级）
- **设计（评审降级）**：评审指出 Loop 与 Agent 内部（session/hooks/autonomy/plugin/reflection）紧耦合 ~160 行，全量组件化 churn 极高、`ProgrammaticLoop` 收益低。**降级为「策略参数 / 子类」而非 `kind=loop` 组件**：`Agent` 新增 `loop_strategy` 可调用参数或 `Agent` 子类（如 `ProgrammaticAgent`），`ProgrammaticLoop` 先做 **opt-in 分支验证**（经 config 显式启用，默认 `DefaultLoop`）。内核仍把 `DefaultLoop` 注册为默认 loop 单元，但替换路径走构造参数而非全局组件。
- **验收**：① `DefaultLoop` 全量回归不变（**golden/fixture 锁定，非仅断言**，复用 `gate.py`）；② `loop_strategy` 经构造参数可替换；③ `ProgrammaticLoop` opt-in 分支有真实端到端断言；④ 零依赖。

#### #97 V22-2 命名模式 = 插件集（评审降级为收尾项）
- **设计（评审降级）**：评审指出 `mode=插件集` 本质是现有标量自治（`autonomy.py` 的 `READONLY_TOOLS`/`DANGEROUS_TOOLS` + `build_policy`）+ plan_mode 的**配置打包**，价值有限且新增与滑块并行的配置维度（易冲突）。**降级为 V22 收尾小项**：内置模式 `coding`/`eval`/`autonomous`/`safe-review` 作为配置 bundle（`{components, autonomy, tool_allow, plan_mode}`），但**规定与标量滑块冲突时的权威来源 = 显式 `BAIZE_MODE`**（滑块仅当模式未指定时兜底）。`eval` 模式最小（对齐 harness Minimal 供 bench）。新增 `kind` 的开放注册机制（第三方加新 kind 无处注册）留作 #99 范围。
- **验收**：① 模式加载正确组件集 + 自治级别 + 工具 allow-list；② 四种模式行为显著不同；③ `eval` 最小；④ **`BAIZE_MODE` 优先于标量滑块**（单测冲突权威）；⑤ 零依赖。

#### #98 V22-3 沙箱 / 存储 / UI 统一暴露为组件
- **设计**：`sandbox.py`、`persistence` 后端、`serve.py` 传输（web/stdio/none）注册为同类组件。用户可经配置换服务形态（web/stdio/无）或存储后端，不改核心。
- **验收**：① 服务传输可换（web/stdio/none）；② 存储后端可换；③ 默认不变；④ 零依赖。

### V22-2 — 生态

#### #99 V22-4 组件发现 / 市场机制增强（严格隔离）
- **设计**：扩展 `plugin.py` 的 `discover()`，使之也能发现「组件」（不仅是钩子），来源同 `baize/plugins/` + `BAIZE_PLUGINS_DIR`。**第三方组件沿用 plugin.py 防御性隔离（记录 + 跳过），绝不「默认可信」**——这是相对 harness 的关键修正。
- **验收**：① 组件从目录发现；② 有 bug / 恶意组件被隔离（host 不崩）；③ 零依赖。

### V22-3 — 文档 + 收口

#### #100 V22-5 文档 / 规格升级 + 写一个 baize component 教程
- **设计**：`README`/`AGENT`/`SKILL`/`openspec` 反映插件架构；新增「写一个 baize component」教程（对标 harness 写 `dsh-plugin`），含最小 `Component` 子类示例 + `BAIZE_COMPONENTS` 注册。
- **验收**：① 规格文档同步；② 教程含可运行最小示例；③ 零依赖示例。

#### #101 V22-6 测试验证 + 诚实门禁收口
- **设计**：扩展 `bench.py`/`gate.py` 覆盖「组件替换」与「模式切换」真实路径；复测全量覆盖率 ≥85%。
- **验收**：① 组件替换 / 模式切换有真实端到端断言；② 门禁仍 PASS；③ 零依赖；④ 不假绿。

---

## 四、刻意不做（呼应路线图 §"刻意不做"）

- **不引入 Node/JS 运行时或任何第三方依赖**（保持纯 stdlib 白盒）。harness 的 Cordis 是 JS 生态，只能借鉴思想。
- **不采用 harness 的三处安全弱点**：松默认权限、第三方插件默认可信、执行模型生成的 JS。白泽的 fail-closed + 作用域隔离 + 密钥脱敏必须守住。
- **不做 Agent 团队去中心化自协调**——白泽用 `Orchestrator` 中心式编排即可。
- **不做「假插件」**——每个组件必须有真实替换点 + 单测，禁止把现有 import 简单改名伪装成组件（NO FAKE DONE）。
- **不堆功能列表**——V22 是架构重构（让核心单元可组合），不是新增一堆能力。

---

## 五、风险与诚实约束（贯穿 V22）

1. **组合内核重构风险**：解耦 `agent.py`/`serve.py` 的硬编码 wiring 可能引入回归 → #95 必须配套全量回归 + 默认组件集行为不变（回归测试为验收硬门槛）。
2. **依赖解析循环 / 缺失** → 内核 fail-closed（缺依赖不静默降级到错误实现，记录并阻断该组件）。
3. **第三方组件不可信** → 沿用 `plugin.py` 防御性隔离（日志 + 跳过），**绝不**「默认可信」（相对 harness 的关键修正）。
4. **命名模式误配**（如 `eval` 模式误开写权限）→ 模式 bundle 经 `gate` 校验 `tool_allow` 非空且与自治级别一致。
5. **Loop 策略替换改变推理行为** → `DefaultLoop` 必须全量回归锁定；非默认策略 opt-in，不破零依赖与 NO FAKE DONE。
6. 所有新增组件**默认关闭**，显式启用；不破零依赖与 NO FAKE DONE。

---

## 六、本次交付 & 下一步

- **本次交付**：本计划文档（含 Cordis 对标 + #95–#101 设计/验收 + §七 评审意见折回）。
- **评审状态**：已交付资深 agent 工程师评审，结论 **Approve-with-changes**。评审提出的 8 项设计补全（显式/自动两套隔离语义、每 kind Protocol 契约、`BAIZE_COMPONENTS` 入 `config_schema`、惰性返回消环导、serve 单例装配、保留构造注入、Loop 降级为策略参数、mode 降为收尾项）**已全部折回 §三对应 Task 设计与 §七**。
- **下一步（待你批准）**：从 **#95 V22-0 统一插件契约 + 组合内核** 起，按「方案 → 实现 → 隔离 venv 单测 → 复测全量覆盖率 ≥85%」逐步推进，每完成一个 task 标记并汇报。
- 文档仍**本地不动**（与 P1–P3 一致），未推送 GitHub；GitHub 推送待你另行确认。

---

## 七、评审意见与待补设计（Approve-with-changes → 已折回）

> 评审方：资深 agent 系统架构师（agent 工程师），对照 baize 真实源码（`plugin.py`/`agent.py`/`serve.py`/`sandbox.py`/`autonomy.py`/`subagent.py`/`llm.py`/`config.py`/`cli.py`）+ 全包 import 扫描，确认零依赖声明诚实、缺口判断属实。
> 结论：**Approve-with-changes**——方向对，但实施前须补全以下 8 项。本文已逐项折回 §三对应 Task 与下表，修订后可作为 #95 实施基线。

| # | 评审意见 | 折回位置 / 处置 |
|---|---|---|
| 1 | 拆分"显式覆盖组件失效 = fail-closed 阻断"与"自动发现组件 = 记录跳过"两套语义 | #95「两套隔离语义」；验收③/④分测 |
| 2 | 每 `kind` 定义 `Protocol` 契约 + 装配后类型校验，拒坏实现 | #95「每 kind 定义 Protocol 契约」；验收⑤ |
| 3 | `BAIZE_COMPONENTS` 纳入 `config_schema.validate()` fail-fast | #95「BAIZE_COMPONENTS 纳入 config_schema」；验收⑥ |
| 4 | 惰性/`Any` 返回类型消除组件注册循环导入 | #95「消除循环导入」；验收⑦ |
| 5 | serve 路径 Runtime 注入形态（Handler 子类或模块单例，只建一次） | #95「serve 路径 Runtime 注入」；验收⑧ |
| 6 | 保留 `Agent` 构造注入，Runtime 不得唯一入口 | #95「保留 Agent 构造注入」；验收⑧ |
| 7 | Loop 组件化降级为策略参数/子类，ProgrammaticLoop 先 opt-in 分支 | #96「评审降级」；验收②/③ |
| 8 | "模式=插件集"降为收尾项，定与标量滑块冲突的权威来源 | #97「评审降级」；验收④ |

**补充关切（已吸收）**：① 回归须"保证"而非"断言"——`DefaultLoop` 用 golden/fixture 锁定并复用 `gate.py`；② 新增 `kind` 的开放注册机制（第三方加新 kind 无处注册）留作 #99 范围；③ 内核启动时装配一次，serve 路径绝不 per-request 重建（性能）。

**修订后状态**：8 项均已落入设计与验收，计划达到"可进入 #95 实现"的基线；待你最终批准后启动实施。
