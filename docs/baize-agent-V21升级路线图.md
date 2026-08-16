# Baize V21 升级路线图（主流开源 Agent 竞争格局 + 卡帕西指导思想）

> 编写日期：2026-08-14（v4，经独立 agent 专家评审后并入高优先升级点与验收加固：P0-1 补受限 git 原语 + 绕过测试、P0-2 不可信隔离注入、P0-4 修正不实表述并扩脱敏范围、P1-4 补 rag 调用点前置、P3-1 内置本地 bench 用例、阈值统一 85%、manifest 阶段改名与门禁加固；思想溯源见 `docs/baize-设计思想溯源.md`）
> 基线：baize-agent V20.0.0（本地交付物）
> 调研对象（公开资料，截至 2026-08-14）：
> - **baize V20**（内部/个人，纯 stdlib 零依赖）
> - **hermes-agent**（Nous Research，MIT，~108k★）
> - **pi-agent**（pi.dev / earendil-works，MIT，~80k★，TypeScript/Bun）
> - **deepseek-harness / dsh**（deepseek-ai，MIT 预览，~33–40k★，TypeScript/Cordis）
> - **OpenAI Codex CLI**（openai/codex，Apache-2.0，Rust，~90k★，完全开源）
> - **Claude Code**（Anthropic，**闭源商业产品**，npm 可装但源码未完全公开）
> - 参照：Aider（开源 coding agent）、OpenClaw（基于 pi 的通讯 Agent 平台）

---

## 0. 指导思想：卡帕西准则内核

白泽 V21 的每一项升级，都不是为堆功能而堆功能，而是把 Andrej Karpathy 在 2025 年系统化的 Agent 工程原则，从哲学变成更完备的工程能力（详细溯源见 `docs/baize-设计思想溯源.md`）。贯穿本路线的三条内核：

- **奥卡姆 / 无聊栈（Occam's Razor）**：任何新增能力优先纯 stdlib；MCP、Hooks、OS 沙箱等系统接口必须作为**可选适配层、默认不启用**，绝不污染零依赖白盒核心。
- **Guard-railed execution（围绕 LLM 调用加验证环）**：因为 LLM 是「锯齿智能」（某些领域超人、某些领域不及儿童，会幻觉、会在未澄清假设下编码），每次模型调用必须被验证器包裹——这正是白泽 NO FAKE DONE 的理论根基。
- **Observability for cognition（可审计）**：记录 agent 为何行动，让团队可回溯、可核验。

辅助思想：**部分自主 + keep AI on the leash**（自治滑块、逐步扩展自治边界）、**Benchmaxxing 警示**（评测不可游戏化、拒绝刷分）、**本地 agent 秘密管理/审计**。这些分别映射到 P2-1、P3-1、P0-1。

---

## 1. 竞争态势快照（能力矩阵扩展版）

| 维度 | baize V20 | hermes | pi | dsh | Codex | Claude Code |
|------|-----------|--------|----|----|-------|-------------|
| 开源状态 | **未声明** | MIT | MIT | MIT(预览) | Apache-2.0 | **闭源产品** |
| 语言/依赖 | **Python stdlib 零依赖** | Py+JS+native | TS/Bun | TS/Cordis | Rust | TS(闭源) |
| OS 级沙箱 | 逻辑层 deny-list | 提及 | 无 | **Landlock/Seatbelt/ACL** | **Seatbelt/Landlock+bwrap** | 平台隔离 |
| MCP 集成 | **无** | optional | 无(哲学) | 插件可做 | **原生** | **原生** |
| Hooks 生命周期 | plugin 钩子(弱) | 弱 | 扩展事件 | 插件事件 | / | **7 类事件体系** |
| Subagents | 三角色(Verifier) | 子 Agent | 无内置 | 标准模式 | worktree 并行 | **.claude/agents 体系** |
| Plan mode | 反思规划(无入口) | 无 | 扩展 | 创造模式 | /plan | **显式 plan mode** |
| 多 provider | OpenAI 兼容 | 模型无关 | 15+ provider | 适配器插件 | **oss mode 本地** | Anthropic(限) |
| Automations | 无 | cron | 无 | 无 | **定时自动化** | 无 |
| 会话分叉/压缩 | JSONL resume | FTS5 | 树形 | trajectory | 分页/分叉/压缩 | 压缩 |
| Skills 自进化 | save_skill(显式) | **自主闭环** | 静态包 | 社区包 | 市场+自动化 | skills |
| 量化基准对标 | 自有 BTS(未公开) | 无 | 无 | 无 | **Terminal-Bench 第一 83.4%** | 评审质量 2:1 |
| 诚实/核验门禁 | **NO FAKE DONE(独有)** | 无 | 无 | 无 | 无 | 无 |
| token/缓存优化 | 渐进披露(未显式cache) | 未强调 | **渐进披露不撑爆cache** | 未强调 | 大窗口+高效调用 | **subagents隔离+cached前缀** |

> 关键观察：**OS 沙箱、MCP、系统级 Hooks、Subagents 定义格式、Plan mode、多 provider 广度、Automations、公开量化基准**——这 8 项是主流已具备而 baize 缺失/薄弱的"必备能力"；**零依赖白盒 + 诚实门禁 + 可证明的 Verifier** 是 baize 独有、主流不具备的护城河。token/缓存优化维度上 baize 处于中游（有渐进披露理念，未显式 cache），由 P1-3 / P3-2 / P3-4 补齐。

---

## 2. Baize V20 的 SWOT（基于对标）

- **Strengths（优势）**：纯 stdlib 零运行时依赖（可移植/可审计/无供应链面）；NO FAKE DONE（Verifier 独立核验 + manifest 物理核验）是信任刚需；双层架构可外挂给 Claude Code/Codex 作规约/技能包；fail-closed 安全观；144 测试 + 80% 覆盖 + chaos 韧性验证。
- **Weaknesses（劣势）**：无 OS 级沙箱（仅逻辑 deny-list）；无 MCP 生态接入；无系统化 Hooks；Subagent 定义/隔离体系弱；无显式 Plan mode 入口；模型 provider 偏窄；无定时自动化；许可未公开声明；量化基准未公开对标；**skill 自进化偏显式调用、缺自动闭环与版本演进**；**token/缓存未显式优化**。
- **Opportunities（机会）**：主流都在走向"插件化/可重组"，baize 的白盒零依赖正好切差异化；AGENTS.md/CLAUDE.md 已成通用规范，baize 第一层规约可直接互操作；AI 交付"假绿/不可信"痛点下，诚实门禁是强卖点。
- **Threats（威胁）**：Codex/dsh 的 OS 沙箱 + 大厂背书建立安全信任；Claude Code 生态锁定；若长期不补安全/扩展地基，会被视为"玩具"而非"底座"。

---

## 3. 升级总原则

1. **对齐"必备能力"，深化"独有护城河"，不为堆功能而堆功能。**
2. **零依赖白盒不可破**：新增能力优先纯 stdlib；OS 沙箱等系统接口走"可选适配层"，不污染核心运行时。
3. **每个升级项必须有可验证验收**（延续 NO FAKE DONE，禁止假完成）。
4. **优先补"安全 + 互操作 + 可扩展"三地基**，再谈生产力与量化。
5. **测试纪律不可破**：每个 P0–P3 升级项须扩展测试套件（V20 基线 144 测试），并保持 **≥85% 覆盖率**（与 `config.TEST_COVERAGE_THRESHOLD=85` 对齐，消除路线图/CI 门禁阈值冲突）；覆盖率或关键门禁（manifest 物理核验、Verifier 独立核验）回退，视为 NO FAKE DONE 未过关，禁止假绿。

### 3.1 卡帕西派生三原则（每项升级必过）

每个 P0–P3 升级项在交付前必须自答（对应第 0 节三条内核）：

1. **奥卡姆过关？** 是否引入新的第三方运行时依赖？若是，是否隔离在可选适配层且默认关闭？核心 `baize/` 是否仍为纯 stdlib？（MCP/Hooks/OS 沙箱均须答「是，已隔离」）
2. **Guard-rail 过关？** 是否围绕 LLM 调用增加了验证环？是否可能出现「未澄清假设下编码 / 幻觉式假完成」的缺口？是否经 Verifier / manifest 物理核验兜底？
3. **Observability 过关？** 该能力是否可被审计（日志记录、可回溯、CI 可复用）？是否强化而非削弱 NO FAKE DONE？

任一不过，则该升级项视为未完成（延续 NO FAKE DONE，禁止假绿）。

---

## 4. V21 分阶段路线图

### P0 地基：安全与互操作对齐（必做，不可跳过）

| 编号 | 工作项 | 对标 | baize 现状 / 差距 | 验收标准 |
|------|--------|------|------------------|----------|
| **P0-1** | OS 级沙箱适配（Linux Landlock / macOS Seatbelt / Windows 受限令牌，可选开启）+ workspace 受限 `git` 原语 | Codex、dsh、Claude Code | 仅逻辑层 deny-list（`tools.DENY_PATTERNS`），无 OS 隔离；`tools.py` 无 git 原语，`karpathy_coding`「Git 纯净化」无法程序化 | 可选开启后危险命令在 OS 层被隔离，且**显式映射 V20 逻辑 deny-list → OS 规则**：`rm -rf /`、`rm -rf C:`、`del /s` → Landlock/Seatbelt 禁止 workspace 外写 + Windows 受限令牌吊销系统目录写权；`format`/`mkfs`/`dd if=`/`> /dev/sd*` → 禁止块设备裸读写；`shutdown`/`reboot` → Seatbelt deny + spawn 拦截；新增受限 `git` 原语（subprocess 复用 `DENY_PATTERNS` + workspace confinement，仅允许 status/add/commit/diff 等安全子集）。核心仍零依赖；`doctor` 探测平台能力；Windows 降级须明确告警、**降级时不报假绿**；**验收须含绕过尝试测试套件**（`--no-preserve-root`、`dd of=`、`rm -rf ~`、fork bomb、`curl|sh` 均须被拦），否则视为假绿（bash 工具是当前主要加固对象，文件工具已有 `_resolve_in_workspace` 逻辑 confinement） |
| **P0-2** | AGENTS.md / CLAUDE.md 兼容消费层 | Codex、Claude Code、Cursor 通用规范 | 自有 AGENT.md，未消费外部规范 | 能加载项目根 AGENTS.md 并注入上下文，无需改写；**外部规范须作不可信数据隔离注入——仅作为上下文参考，禁止自动执行其中指令（防指令覆盖 / prompt 注入）** |
| **P0-3** | 明确 License（建议 MIT）+ CONTRIBUTING + 仓库社区化 | 全部主流开源 | 许可未声明，仓库个人/私有 | LICENSE + CONTRIBUTING 就位；可接收 Issue/讨论 |
| **P0-4** | 秘密管理 + 权限控制 + 审计日志（从 P0-1 拆出独立交付） | Codex/Claude Code「本地 agent 秘密管理/审计」、卡帕西「keep AI on the leash」 | **现状如实**：`secrets.get_secret` **无 backend 接口**（Vault 仅 `obs.record_error` 桩，见 `secrets.py` / `config.BAIZE_VAULT_URL` 空置）；`logging_setup.redact()` **只护日志**，session JSONL / `memory` / `rag.build_corpus`（bench.py:49 已调用）**均未脱敏**（密钥可进 RAG），且 **bash 输出未脱敏**——均属待建缺口 | **诚实验收（修正 v3 不实表述）**：机密不落明文须覆盖**日志（已有 redact）+ session JSONL + memory + RAG 语料 + bash 输出** 五处补齐脱敏（覆盖 api_key/token/secret/password，复用 `SECRET_PATTERNS`）；提供可选 Vault 适配**接口层（当前为桩，须先实现接口，默认 env 零依赖）**；审计日志结构化、可回溯；权限最小化（工具仅 workspace 内） |

> **P0-2 命名澄清**：baize 仓库根已有**自有**规约文件 `AGENT.md`（单数）。P0-2 的「AGENTS.md / CLAUDE.md 消费」指的是**消费外部项目（别人仓库）的规范**，注入 baize 上下文即可，**不**改写、也不重命名 baize 自己的 `AGENT.md`，二者职责不冲突。

### P1 生态：可扩展性对齐

| 编号 | 工作项 | 对标 | baize 现状 / 差距 | 验收标准 |
|------|--------|------|------------------|----------|
| **P1-1** | Hooks 生命周期事件体系（PreToolUse / PostToolUse / Stop / SessionStart / PreCompact / PostCompact） | Claude Code | 仅有 plugin 弱钩子 | 可配置 shell hook 拦截危险命令并阻断；事件可被插件订阅 |
| **P1-2** | MCP 工具协议接入（stdio + HTTP 客户端，纯 stdlib 实现） | Codex、Claude Code、hermes、dsh | 无 MCP | 能连接一个 stdio MCP server 并将其工具注册进 baize 工具集（**默认关闭，不污染零依赖核心**） |
| **P1-3** | 子 Agent 定义格式（`*.agent.md` + frontmatter）+ 隔离 context + 帕累记忆 | Claude Code subagents | 仅 orchestrator 三角色硬编码 | 自定义子 agent 在隔离上下文运行，仅返回摘要；支持 memory 持久化（**token 节俭：繁冗输出不占主上下文**） |
| **P1-4** | 技能自进化增强（自动触发提取 + **Verifier 核验门禁** + 版本化 + 统一结构化模板 + 用户/项目上下文建模） | hermes skills 闭环 | 已有 `_tool_save_skill`（写到 `assets/skills/learned/`）+ `rag.record_skill_outcome`（成功率追踪），但**无自动触发、无 Verifier 门禁、无版本化、无去重**；且 `rag.record_skill_outcome` **全库零调用点**——须先在 save/load 路径补调用，否则「不覆盖低 success_rate」无数据支撑 | **诚实版自进化**（前置：先补 `rag.record_skill_outcome` 调用点），缺口逐项补：①「任务成功」信号复用 orchestrator `success`（全 subtask verdict=pass）或 manifest 物理核验通过，作为自动触发条件；②新增 `verify_skill_draft` 用现有独立 LLM Verifier 跑**经验质量 rubric**：(a) 非幻觉——draft 引用的命令/API/路径与该 session 的 tool trace（executor_summary/evidence）交叉核验；(b) 可复现——步骤含确定性命令 + 前置条件；(c) 不重复——`skill_index.search` 语义去重 + 不覆盖低 `success_rate` 旧 skill；(d) 最小特权——不得含硬编码密钥（复用 `SECRET_PATTERNS` 校验）；③版本化：`<skill>/vN/` 目录（或 `@<date>`），结构模板含「步骤/坑点/验证/适用上下文」；④检索上下文感知（用户/项目标签）。未经 Verifier 核验的 draft 不得入库——这是区别于 hermes（可能错误经验自我强化）的关键纪律 |

### P2 生产力：工程体验对齐

| 编号 | 工作项 | 对标 | baize 现状 / 差距 | 验收标准 |
|------|--------|------|------------------|----------|
| **P2-1** | 显式 Plan Mode（只读分析 → 用户确认 → 执行）+ 权限模式（自治滑块） | Claude Code plan mode/权限、Codex /plan、**卡帕西自治滑块/部分自主** | 有反思规划但无显式入口 | `baize plan` 不写盘、只读；确认后执行；暴露自治度（建议↔全自动），高自治操作走人工审查/沙箱（「leash」工程化） |
| **P2-2** | 多 Provider 模型广度（Ollama / LM Studio / Bedrock / 本地端点） | Codex oss mode | 仅 OpenAI 兼容 | provider 切换无需改码；本地模型可跑通端到端任务 |
| **P2-3** | Automations / 定时任务 | hermes cron、Codex automations | 无 | 可注册定时任务并投递到会话/外部 |
| **P2-4** | 会话分叉 / 压缩 UI 增强 | Codex、pi、dsh | 仅 JSONL resume | 会话可从检查点 fork；压缩质量可视化 |

### P3 护城河：量化竞争力

| 编号 | 工作项 | 对标 | baize 现状 / 差距 | 验收标准 |
|------|--------|------|------------------|----------|
| **P3-1** | 公开可复现基准（Terminal-Bench 风格 + **内置 5–10 本地端到端任务（物理核验防刷分）** + 自有 BTS-001~005），相同 LLM 下对标 6 家 | Codex Terminal-Bench | 自有 BTS 未公开对标；`bench.py` 有 `register()` 但**零任务用例** | 一键跑基准并出具 6 家对标表；**须遵循卡帕西 Benchmaxxing 警示：基准不可游戏化**——内置任务须为真实端到端 + 证据物理核验（NO FAKE DONE），`bench.py` 须先落地任务集，拒绝刷分式榜单 |
| **P3-2** | 上下文 / 长程管理增强（大窗口策略、压缩质量、subagents 上下文隔离） | Codex 272K/1M、Claude 压缩/隔离 | 有 memory compress | 长任务上下文不溢出、压缩可回溯；子 agent 隔离降低主上下文 token |
| **P3-3** | NO FAKE DONE 产品化（manifest 可视化、CI 门禁插件、交付报告生成） | —（独有） | 门禁存在但未产品化 | 门禁可作为独立 CI 组件复用；交付报告自动生成 |
| **P3-4** | prompt cache 友好 + token 效率（稳定系统前缀 + 技能索引前置 + 可选 cache_control） | pi/Claude Code（渐进披露不撑爆 cache） | 渐进披露已有，未显式实现 prompt caching | 系统提示/技能索引稳定前置、对话后置；可选启用 `cache_control`，降低 token 成本与延迟（补齐缓存命中短板） |

---

## 5. 刻意不做（保持极简白盒）

- **不内置多模态输入**（截图/设计稿）——除非明确需求，避免膨胀核心。
- **不重造 OS 沙箱内核**——用系统接口适配（Landlock/Seatbelt/ACL），非自研隔离引擎。
- **不追求"功能数量超越 Codex/Claude Code"**——baize 的差异化在白盒 + 诚实，而非功能堆叠。
- **不绑定特定模型厂商**——模型中立是底线（延续 OpenAI 兼容 + P2-2 多 provider）。
- **不让 skill 自进化脱离 Verifier 门禁**——自动提取的经验未经独立核验不得入库（诚实版自进化，区别于 hermes 的可能"错误经验强化"）。

---

## 6. 里程碑与时间线（建议）

> 节奏参考 V20 的 T1–T9 推进经验（每阶段约 1–2 周，含真实验收）。以下为建议，非承诺。**统一退出标准（§3 原则 5）**：每个阶段须扩展测试套件并保持 ≥85% 覆盖率（V20 基线 144 测试，与 `config.TEST_COVERAGE_THRESHOLD` 对齐），否则视为 NO FAKE DONE 未过关。

| 阶段 | 建议周期 | 关键交付 | 退出标准 |
|------|----------|----------|----------|
| P0 | 第 1–2 周 | OS 沙箱适配层（含 deny-list→OS 映射 + 绕过测试）+ 受限 git 原语 + AGENTS.md 消费（不可信隔离）+ LICENSE + 秘密管理/审计（P0-4） | 安全/互操作/秘密三地基可演示；通过 §3.1 三原则校验 |
| P1 | 第 3–5 周 | Hooks 体系 + MCP 客户端 + 子 Agent 格式 + **技能自进化增强** | 扩展三件套 + skill 自进化闭环（Verifier 包裹）真实跑通；MCP 默认关闭不破零依赖 |
| P2 | 第 6–8 周 | Plan mode + 多 provider + Automations + 会话分叉 | 工程体验对齐主流；自治滑块可调控 |
| P3 | 第 9–11 周 | 公开基准对标 + 长程增强 + 门禁产品化 + **cache 友好** | 量化护城河可对外证明；基准不可游戏化；启用 prompt cache 前缀优化 |

---

## 7. 风险与依赖

1. **OS 沙箱跨平台复杂度**：Windows 受限令牌（restricted token）实现难度高于 Linux Landlock；建议 P0-1 先落地 Linux/macOS，Windows 走降级适配并明确告警。
2. **MCP 与零依赖的冲突**：MCP 是 JSON-RPC over stdio/HTTP，协议本身可用纯 stdlib 实现客户端（无需第三方 lib）——**技术上可行**，但须严格评估不引入传输层依赖；若确需，应作为可选适配层（默认不启用）。此条直接受 §3.1 奥卡姆原则约束。
3. **量化基准需稳定 LLM 环境**：Terminal-Bench 风格对标要求相同模型/相同初始代码/不人工干预，需锁定评测环境与成本预算；且须遵守 P3-1 的「不可游戏化」约束。
4. **许可证选择影响生态**：建议 MIT（与 hermes/pi/dsh 一致），便于被 Claude Code/Codex 用户作为规约/技能包消费。
5. **skill 自进化的质量风险**：自动提取若缺乏核验，会沉淀错误经验并自我强化。P1-4 必须用 Verifier 独立核验门禁兜底——这是 baize 区别于 hermes 的关键纪律。
6. **manifest 门禁强度不足**：`manifest.py` 证据仅查「文件存在」，未查非空 / 生成时间，陈旧或空 evidence 文件可致假绿；须加非空 + 时间新鲜度校验（证据须晚于 phase 开始时间）。
7. **Verifier 可被弱 plan 绕过**：director 声明空 `checks` 时仅剩 LLM Gate2，存在「声明无检查」绕过；须强制每 subtask 至少一条确定性 check 或 plan 复核。
8. **manifest 阶段命名碰撞**：`manifest.PHASE_IDS = P1..P12`（manifest.py:24）与路线图 P0–P3 重名，工具 / 文档易混；建议 manifest 阶段改名（如 `M1..M12`）或在文档显式区分。

---

## 8. 核心结论

baize 不必、也不该成为"另一个 Codex 或 Claude Code"。V21 的正确路径是：**先补齐安全（OS 沙箱）、互操作（AGENTS.md / MCP）、可扩展（Hooks / Subagents / 技能自进化）三块地基，使其达到主流"底座"门槛；再用零依赖白盒 + NO FAKE DONE 诚实门禁作为不可替代的差异化护城河，并用量化基准公开证明**。

这背后的统一逻辑来自卡帕西：LLM 是「锯齿智能」，所以必须 guard-rail（Verifier/沙箱/不可游戏化基准）；部分自主所以要 leash（Plan mode/权限滑块/失败重试）；极简所以零依赖不可破。**V21 的全部升级，都是白泽初始灵魂——"用精确对抗幻觉"——的外部扩容，而非功能堆叠。** 这样 baize 既能作为独立运行时，又能作为主流商业 Agent 的"可信规约/技能层"被消费——这是其他竞品都做不到的生态位。

---

## 8.5 讨论衍生的升级项与竞品 token/缓存认知

本路线在讨论中补充了两项升级（P1-4、P3-4），并明确 baize 在 token/缓存上的位置：

- **P1-4 技能自进化增强**：借鉴 hermes 的「任务→经验提取→存储→检索→自我改进」闭环，但用 baize 独有的 **Verifier 独立核验** 包裹自动提取环节，形成「诚实版自进化」——自动生成的经验 draft 须经核验才归档为 skill，规避错误经验自我强化。同步补 skill 版本化与统一结构化模板（步骤/坑点/验证）。
- **P3-4 prompt cache 友好 + token 效率**：补齐讨论暴露的缓存命中短板。baize 已有技能渐进披露（理念与稳定前缀缓存一致），但未显式实现 prompt caching；计划将系统提示/技能索引稳定前置、对话后置，并可选启用 `cache_control`。

**各 agent token/缓存对比结论**（讨论整理）：上下文管理精细度以 Claude Code（subagents 隔离 + skills 共享 budget + cached 前缀）/ pi（极简内核 + 渐进披露）最强；每任务总 token 以 Codex 最低（官方称 ~4x 少于 Claude Code）；明确讨论 prompt cache 命中优化的仅 pi 与 Claude Code。baize 处于中游，靠 P1-3（子 Agent 隔离）+ P3-2（长程增强）+ P3-4（cache 友好）补齐。

---

## 9. 数据来源

- baize：本地 `README.md`（V20.0.0）、`docs/baize-agent-V20交付文档.md`、`benchmarks/COMPARISON.md`、`assets/skills/karpathy_coding/SKILL.md`。
- 思想溯源：`docs/baize-设计思想溯源.md`（卡帕西公开思想归纳与提炼）。
- hermes / pi / dsh：见 `docs/COMPARISON-四引擎对比.md`（2026-08-14 网络资料）。
- Codex：openai/codex（Apache-2.0，Rust）、codegen.com、CSDN/博客评测（2026-06 数据）。
- Claude Code：claude.com 官方博客"Steering Claude Code"、developersdigest、ofox.ai 指南（2026）。
- 卡帕西公开：YC AI Startup School 2025-06《Software in the era of AI》；2025 LLM Year in Review（karpathy.bearblog.dev）；个人 LLM 编码工作流（2025-08）。
- ⚠️ Star、版本、功能细节随时间快速变化；以各项目官方仓库最新状态为准。
