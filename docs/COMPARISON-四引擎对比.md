# 四引擎对比：白泽引擎 vs hermes-agent vs pi-agent vs deepseek-harness

> 编写日期：2026-08-14
> 数据时效：白泽数据来自本地 V20 交付物（README / 交付文档）；hermes / pi / deepseek-harness 数据来自公开网络资料（GitHub、官网、第三方评测），截至 2026-08-14，Star 等社区指标波动较大，仅作方向性参考。
> 一句话定位：**白泽 = 吸收 hermes 自主循环 + pi 极简内核后的"白盒工程化"运行时；hermes = 自我进化的全能 Agent 基础设施；pi = 极简可懂的 harness 内核；deepseek-harness = 一切皆插件的 Agent 运行时底座。**

---

## 0. 执行摘要（TL;DR）

| 引擎 | 一句话定位 | 语言 / 栈 | 运行时依赖 | 成熟度 |
|------|-----------|-----------|-----------|--------|
| **白泽引擎 (baize-agent) V20** | 白盒工程化研发操作系统：方法论技能包 + 真实 Agent 运行时双层，零依赖、强门禁 | Python 3.10–3.13（纯 stdlib） | **0（仅测试期需 pytest）** | V20.0.0，144 测试，个人/内部仓库 |
| **hermes-agent** | "会自我进化的 Agent"——技能闭环 + 持久记忆 + 跨平台网关 | Python + 部分 JS + native(C) 扩展 | 需 pip + 原生扩展 | ~108k★（2026-04），v0.8.0+，MIT |
| **pi-agent (pi.dev / pi-agent-core)** | 极简 harness："Primitives, not features"，4 工具内核 + TS 扩展 | TypeScript（运行于 Bun） | 需 Bun / Node | ~80k★，周下载 1.3M，MIT |
| **deepseek-harness (dsh)** | "一切皆插件"的 Agent 运行时底座（Model + Harness = Agent） | TypeScript（Node 22.19+/24+，pnpm） | 需 Node / pnpm + 系统沙箱 | 33k–40k★（2026-08-13 开源），预览版，MIT |

**核心结论：** 四者并非简单替代关系。hermes 与 pi 是白泽的**设计上游**（白泽 README 明确写"吸收 hermes 的自主循环/模型无关客户端/自进化技能 与 pi 的极简内核/原语工具/JSONL 会话持久化"）；deepseek-harness 是**同赛道最新竞品**，把"可重组"做到极致。白泽的不可替代性在于：**纯 stdlib 零依赖的白盒 + 可证明的诚实门禁（NO FAKE DONE / Verifier 独立核验）**。

---

## 1. 它们之间的关系图谱

```
                设计理念来源（被吸收）
   hermes-agent ─────────────┐
   (自主循环/模型无关/自进化技能)  ├──►  白泽引擎 baize-agent V20
   pi-agent ─────────────────┘        (融合 + 工程化门禁 + 零依赖)
   (极简内核/原语/JSONL 会话)
                                      │
                                      同赛道竞品（不同技术路线）
                                      │
                          deepseek-harness (dsh)
                          (一切皆插件 / Cordis / OS 级沙箱)
```

- **白泽 ↔ hermes / pi**：基因同源、理念继承。白泽不做"重新造轮子式的框架"，而是把两者被验证的核心设计吸收进自己的双层架构，再叠加 hermes/pi 都没有的**工程门禁**（Verifier 独立核验、manifest 证据物理核验、doctor 环境门禁）。
- **白泽 ↔ deepseek-harness**：同处"Agent 运行时/底座"赛道，但技术路线相反——白泽走 **Python stdlib 零依赖白盒**，dsh 走 **TypeScript + Cordis 插件内核**。dsh 的"可重组"胜在灵活，白泽的"零依赖白盒"胜在可控、可审计、可移植。

---

## 2. 能力总矩阵（关键维度一览）

| 维度 | 白泽引擎 V20 | hermes-agent | pi-agent | deepseek-harness |
|------|-------------|--------------|----------|------------------|
| 运行形态 | 规约包 + 自带运行时（双模式） | 独立运行时 + 网关 | 独立 harness | 插件化运行时（web/headless profile） |
| LLM 调用循环 | 自带（反思规划 + 自主循环） | 自带 | 自带 | 自带（loop 本身是可换插件） |
| 模型中立性 | OpenAI 兼容任意端点 | 模型无关（`hermes model` 切换） | 15+ provider，会话内切换 | 模型适配器即插件（含 Claude/OpenAI/Gemini） |
| 工具系统 | 9 原语 + SDK 扩展（单例注册表） | 内置工具集 + skills | 4 原语（read/write/edit/bash）+ 扩展 | 工具注册表即插件；4 模式 |
| 工具沙箱 | 工作区限制 + deny-list（**fail-closed**） | sandbox / TEE（细节少） | **无内置权限**（需自建） | **OS 级沙箱**（Landlock/Seatbelt/Windows ACL） |
| 会话持久化 | append-only JSONL，`--resume` 续跑 | FTS5 搜索 + LLM 摘要跨会话召回 | 树形单文件多分支（/tree /fork） | append-only event stream（trajectory，可 fork/replay） |
| 记忆体系 | 持久记忆 + 长程压缩 + RAG | 持久记忆 + Honcho 用户建模 | compaction 自动摘要 + 扩展式记忆 | 会话日志即事实，可搜索回放 |
| 多 Agent 编排 | **Director→Executor→Verifier（独立核验）** | 子 Agent 并行 | 无内置（扩展实现） | 标准模式含 subagents / planning |
| 技能/扩展 | 249 唯一技能可索引 + 渐进披露；`save_skill` 自进化 | skills 闭环自进化（agentskills.io 兼容） | TS 扩展 + Pi Packages（npm/git） | 一切皆插件，社区包与官方同等 |
| 独立核验门禁 | **NO FAKE DONE（Verifier + manifest 物理核验）** | 无 | 无 | 无（但有 trajectory 可审计） |
| 环境门禁 | `baize doctor`（真实探测 + exit code） | 启动检查 | 启动检查 | 启动检查 |
| 数据层 | vector(TF-IDF)/rag/graph 内置 | 无显式 | 无（扩展可做 RAG） | 无显式（插件可做） |
| 交互形态 | TUI + Web 仪表盘 + REST serve | 全功能 TUI + 多平台网关 | 四类模式（TUI/print-JSON/RPC/SDK） | Web UI（:3080）/ headless |
| 工程化 | 144 pytest + 80% 覆盖 + CI + Docker + chaos | 2万+ commits，测试体系 | MIT，社区活跃 | 1.2万 commits，CI 覆盖多 Node 版 |
| 第三方运行时依赖 | **0** | 有（pip + native） | 有（Bun/Node） | 有（Node/pnpm + 系统沙箱） |
| 许可 | 未公开声明（内部/个人） | MIT | MIT | MIT（开发者预览，暂不接受外部 PR） |

---

## 3. 分维度深度对比

### 3.1 架构哲学与语言栈

- **白泽**：**双层架构**是第一性原理——第一层是"规约与技能"（AGENT.md / SKILL.md / assets/skills，可被 Claude Code / Codex / WorkBuddy 等外部客户端直接加载）；第二层是"纯 stdlib 运行时"（llm / agent / tools / orchestrator / team_memory / vector / rag / graph / ui / dashboard / observability / chaos … 26 模块）。哲学是**白盒 + 可证明**。
- **hermes**：**大而全的 Agent 基础设施**。gateway 单一进程同时承载终端、长期记忆、skill 沉淀、子代理、定时任务、消息平台。混合技术栈（Python + JS + native FTS5 C 扩展 + nix），复杂度高但能力全。
- **pi**：**极简内核 + 扩展 API**。默认只有 4 个工具，核心小到"可以完全读懂"。所有高级能力（sub-agents、plan mode、permission gates）都通过 TypeScript 扩展实现，而非硬编码。哲学是"Primitives, not features"。
- **deepseek-harness**：**极致插件化**。基于 Cordis 元框架（北大 + DeepSeek 联合论文），"no privileged core to patch"——模型适配器、工具注册表、会话日志、agent loop 本身都是插件。profile 分层（dsh-base → web/headless）+ cordis.patch.yml 补丁，配置即拼装。

> 光谱：**pi（极简可懂）← 白泽（零依赖白盒+门禁）← hermes（全能基础设施）**，而 **dsh 在"可重组"维度单独拉满**。

### 3.2 模型适配与中立性

四者都宣称"模型无关"，但实现层级不同：
- 白泽：单文件 `llm.py` 封装 OpenAI 兼容端点，带速率限制/退避，**未配置模型则 fail-closed（exit 2）**。
- hermes：`hermes model` 命令行切换，无需改代码；覆盖 Nous/OpenRouter/OpenAI/自定义。
- pi：15+ provider、数百模型，**会话内可 `/model` 实时切换**（最灵活的用户体验）。
- dsh：模型适配器是插件，甚至连 Claude Code / Codex 都能作为 subagent provider 接入——**赌的是"基础设施层 > 模型层"**。

### 3.3 工具系统

- 白泽：**9 原语工具 + SDK 运行时扩展**，注册表为**进程级单例**（修复过"注册进丢弃注册表"的 bug）；默认工作区限制 + 命令 deny-list，fail-closed 拦截危险命令。
- hermes：内置工具集 + toolsets 分发；skills 可调用工具。
- pi：**刻意只给 4 个原语**（read/write/edit/bash），其余靠扩展注册工具——核心越小越可控、越不易出错。
- dsh：工具注册表本身是插件；提供 4 种运行模式裁剪工具集（标准 / PTC 程序化工具调用 / 极简 / 创造）。

### 3.4 会话持久化与记忆

- 白泽：append-only **JSONL 转录**，崩溃不丢状态、`--resume` 续跑；叠加**长程记忆压缩**（`memory compress`）与 RAG 检索增强。
- hermes：FTS5 全文会话搜索 + LLM 摘要实现**跨会话召回**，并做 Honcho dialectic 用户建模（"越来越懂你"）。
- pi：**树形会话**（单文件多分支），`/tree /fork /clone` 可在任意历史点分叉续跑，不影响主上下文——对多 Agent 支线任务尤其有用。
- dsh：**append-only event stream（trajectory）**，一切（系统提示/推理/工具调用/子 Agent 调度/上下文注入）全记录，Web UI 只是它的视图；resume/fork/search/replay 都在同一流上操作。

> 四者都认同"会话即事实、可续跑、可审计"，只是存储形态不同（JSONL / FTS5 / 树文件 / event stream）。

### 3.5 多 Agent 编排

- 白泽：**显式三角色**——Director（规划）→ Executor（执行）→ **Verifier（独立核验，硬化）**，失败自动重试。Verifier 是工程门禁的执行点。
- hermes：子 Agent 并行（spawn 子任务）。
- pi：**无内置**，完全靠扩展实现 sub-agents / plan mode（哲学使然）。
- dsh：标准模式内置 subagents + planning。

### 3.6 扩展与插件机制

- 白泽：外部技能库通过 `SKILL_LIBRARY_PATHS` 配置化引用 + 索引动态发现；`save_skill` 落盘即重建索引（自进化）；本地 assets/skills 方法论（毛选调查、卡帕西编码）。
- hermes：skills 闭环（任务后自动提炼 skill，使用中自我改进）+ plugins + 可选 MCP（optional-mcps），兼容 agentskills.io 开放标准。
- pi：TypeScript 扩展模块（registerTool / registerCommand / on 事件）+ Pi Packages（npm/git 分享）+ skills + prompt templates + themes。
- dsh：**一切皆插件**，挂载即扩展（不 fork 内核）；官方与社区包地位平等；当前暂不接受外部 PR（开发者预览）。

### 3.7 安全与沙箱（差异最显著）

| 引擎 | 安全观 |
|------|--------|
| 白泽 | **fail-closed 优先**：沙箱默认开启、命令 deny-list、未配置模型直接退出；Verifier 独立核验防"假绿" |
| hermes | 提及 sandbox / TEE，公开细节较少 |
| pi | **坦诚"无内置权限系统"**，要求用户自己沙箱；但供应链安全强（--ignore-scripts、依赖冻结、两天最小发布年龄） |
| dsh | **OS 级沙箱最硬核**：Linux Landlock（自定义 Node addon）/ macOS Seatbelt / Windows ACL 受限令牌——浏览器同级别的隔离 |

> 白泽与 dsh 在"安全"上最较真，但路径不同：白泽用**逻辑层 fail-closed + 独立核验**保证"诚实"，dsh 用**OS 级隔离**保证"不越权"。pi 把安全责任交还给用户。

### 3.8 工程化与测试

- 白泽：**144 个 pytest**（脚本化 transport 真实驱动真实循环，非 mock 空转），覆盖率 **80%**（CI 门槛）；CI 跨 OS × Python 3.10–3.13；Docker 非 root + 健康检查；`chaos.py` 故障注入**真实验证韧性**。
- hermes：2 万+ commits，含 tests / tests-js 双栈测试。
- pi：MIT，社区活跃（周下载 1.3M），由 libGDX / Flask 作者维护。
- dsh：1.2 万 commits，CI 覆盖 Node 22.19 / 24 / 26。

### 3.9 部署形态与客户端

- 白泽：CLI（`python -m baize ...`）+ TUI + Web 仪表盘（serve）+ REST；也可仅作为规约包被外部 Agent 客户端复用。
- hermes：跨平台网关（Telegram / Discord / Slack / WhatsApp / Signal / CLI）+ TUI + cron 定时；可跑 $5 VPS 到 GPU 集群。**Windows 原生不支持（需 WSL2）**。
- pi：四类模式（interactive TUI / print-JSON / RPC / SDK）；是火爆的 OpenClaw 通讯 Agent 平台的底层引擎。
- dsh：web（默认 :3080）/ headless 两类 profile；`npx @deepseek-ai/dsh web` 一键起。

### 3.10 成熟度 / 社区 / 许可

- hermes：最成熟（~108k★，v0.8.0+，数百贡献者，MIT）。
- pi：成熟且生态活跃（~80k★，MIT，供应链安全口碑好）。
- dsh：最新但爆发力强（33k–40k★，仅开源数日，**开发者预览、破坏性变更警告、暂不接受 PR**，MIT）。
- 白泽：个人/内部项目，V20.0.0（GitHub 个人仓库 jianjian12138/baize-agent），144 测试背书，**许可未公开声明**。

---

## 4. 白泽引擎的差异化护城河

1. **纯 stdlib 零运行时依赖**：唯一一个运行时不依赖任何第三方包的实现。可移植性、可审计性、无供应链攻击面，是另外三者（hermes 需 native 扩展、pi/dsh 需 Node 生态）都不具备的。
2. **可证明的诚实（NO FAKE DONE）**：`manifest validate` 要求 phase 标记为 done 时，其 evidence 文件必须**物理存在**；Verifier 独立核验，失败自动重试。这是 hermes / pi / dsh 都没有的"防假绿"机制。
3. **双层架构（规约 + 运行时）**：既能自主运行，又能作为 Claude Code / Codex / WorkBuddy 的"方法论规约包"被加载——角色灵活。
4. **fail-closed 安全观**：未配置模型即退出、命令 deny-list、沙箱默认开。把"不出错比出新功能更重要"写进设计。
5. **防御式设计可证明**：`chaos.py` 注入真实故障验证 Agent 不崩，而非口头声称韧性。
6. **数据层内置**：vector(TF-IDF) / rag / graph 作为运行时模块原生提供，hermes/pi/dsh 均需外部扩展才具备。

---

## 5. 选型建议（何时选哪个）

| 场景 | 推荐 | 理由 |
|------|------|------|
| 想要**零依赖、可审计、可移植**的私有 Agent 运行时 | **白泽** | 纯 stdlib，白盒，fail-closed |
| 需要**诚实门禁**（交付物不可"假绿"） | **白泽** | Verifier + manifest 物理核验独一无二 |
| 想要**自我进化 + 跨平台消息网关**的全能基础设施 | hermes | skills 闭环 + Telegram/Discord/Slack 接入 |
| 想要**极简可懂、可完全掌控内核**的 harness | pi | 4 工具内核 + TS 扩展，核心可读 |
| 想要**极致可重组、OS 级沙箱**的插件运行时底座 | deepseek-harness | Cordis 一切皆插件 + Landlock/Seatbelt 隔离 |
| 已有 Node 生态、想嵌入 Agent SDK | pi（SDK 模式）/ dsh（headless） | 原生 TS/Node 集成成本低 |

---

## 6. 数据来源与时效说明

- 白泽引擎：本地 `README.md`（V20.0.0）、`docs/baize-agent-V20-交付文档.md`、`benchmarks/COMPARISON.md`、`tests/`（144 用例）。
- hermes-agent：GitHub `NousResearch/hermes-agent`、官网 `hermes-agent.nousresearch.com`、第三方评测（2026-04 资料）。
- pi-agent：官网 `pi.dev`、GitHub `earendil-works/pi`（及 `badlogic/pi-mono`）、dev.to 评测、zyyo.net 解析。
- deepseek-harness：GitHub `deepseek-ai/deepseek-harness`、singularity.kiwi / subagentic.ai / chinaz 等评测（2026-08-13 开源资料）。
- ⚠️ hermes / pi / dsh 的 Star 数、版本号、功能细节会随时间快速变化；本协议撰写时（2026-08-14）如与上述有出入，以各项目官方仓库最新状态为准。白泽的对照数据以其 V20 交付物为权威来源。
