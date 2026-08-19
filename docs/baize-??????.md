# Baize 设计思想溯源：从卡帕西准则到白盒诚实门禁

> 编写日期：2026-08-14
> 目的：回答"我们最初做这个 agent 的思想从哪来"，并把卡帕西（Andrej Karpathy）在公开场合的思想系统化整理、提炼出对 baize 有用的部分。
> 来源：
> - **项目内**：`assets/skills/karpathy_coding/SKILL.md`（白泽落地的卡帕西编码准则）、`README.md` 核心原则、`docs/baize-agent-V20交付文档.md`。
> - **卡帕西公开场合**：YC AI Startup School 2025-06 演讲《Software in the era of AI》；2025 LLM Year in Review（karpathy.bearblog.dev）；个人 LLM 辅助编码工作流（2025-08 公开）。

---

## 1. 白泽初始思想溯源（项目内落地的卡帕西准则）

白泽不是凭空设计的。它在立项之初就把卡帕西的 Agent 开发哲学提炼成一份可执行的技能文件 `karpathy_coding`，再由核心原则贯穿到全局。

### 1.1 karpathy_coding 技能的三条核心规约 + 验证锚点

| 规约 | 原文要义 | 工程含义 |
|------|----------|----------|
| **澄清本位（Clarification First）** | 需求模糊时严禁假设，必须列出备选方案（Options）与用户确认 | 不脑补需求，先对齐再动手 |
| **奥卡姆剃刀（Occam's Razor）** | 优先最简、无依赖、易于测试的实现路径 | 能不引入依赖就不引入；最小复杂度 |
| **Git 纯净化（Minimal Diff Side-effects）** | 严禁改无关代码行 / 缩进 / 空格 / 注释 | 外科手术式变更，diff 可被审计 |
| **验证锚点** | Diff 核销（自审计 git diff 无冗余波动）；逻辑闭环（每处变更在 task.md 有原子验证项） | 变更可验证、可追溯，反对"假完成" |

文件收尾语：*"Precision is the final sovereignty over hallucination."*（精确，是对幻觉的最终主权。）

### 1.2 这些规约如何写进 README 核心原则

- 核心原则第 **2** 条「调查先行」← 澄清本位（决策前先调查，不假设）。
- 核心原则第 **3** 条「外科手术式变更」← 直接引用 `karpathy_coding`，要求最小 diff、无关代码零改动。
- 核心原则第 **1** 条「NO FAKE DONE」← 验证锚点的工程化放大：manifest 的 phase 标记 done 必须有物理存在的 evidence；Verifier 独立核验，失败自动重试。

### 1.3 思想 → 最初架构选择

| 卡帕西思想 | 白泽最初的对应架构选择 |
|------------|------------------------|
| 奥卡姆剃刀 / 最简无依赖 | **纯 stdlib 零运行时依赖**——不引入任何第三方包，可移植、可审计、无供应链攻击面 |
| 外科手术式变更 | 双层架构：第一层"规约与技能"（可被外部客户端加载，也可自主运行），第二层"真实运行时"——变更边界清晰、可被独立核验 |
| 精确对抗幻觉 | **Verifier 独立核验 + manifest 证据物理核验 + fail-closed 安全观**——这就是白泽后来区别于所有主流竞品的"诚实门禁"的思想根源 |

> 一句话：**白泽最初的灵魂，是用卡帕西式的"精确 / 最小 / 不假设"，去对抗 Agent 交付中最常见的"幻觉式假完成"。**

---

## 2. 卡帕西公开思想整理归纳（按主题）

以下归纳来自卡帕西 2025 年的公开表达（演讲、博客、X），按主题归类，并标注原始语境。

### 2.1 软件范式 1.0 / 2.0 / 3.0
- 软件 1.0 = 显式代码（Python/C++）；2.0 = 神经网络权重（数据优化出来）；**3.0 = 提示词（自然语言，"最热门的新编程语言是英语"）**。
- LLM 是"可编程的神经网络"，推理时用自然语言"编程"。

### 2.2 锯齿智能（Jagged Intelligence）/ Ghosts vs Animals
- LLM 智力像"召唤来的幽灵"而非"进化出的动物"：某些领域超人、某些领域不及学龄儿童，**性能极不均匀（锯齿状）**。
- 会幻觉、会过度复杂化问题、**会在未澄清假设下直接编码**、缺乏长任务的"耐力"。
- 基准测试常是可验证环境，容易被针对性优化（"benchmaxxing"），分数不可全信。

### 2.3 部分自主 + 人类监督（钢铁侠战衣，非机器人）
- 用"钢铁侠战衣"（增强版你）而非"钢铁侠机器人"（全自动）作隐喻；**自治滑块（autonomy slider）**控制 AI 行动范围。
- **Keep AI on the leash**（把 AI 拴在绳上）：紧范围、增量发布、human-in-the-loop。
- "信任但验证（trust but verify）"——AI 可能持续 30 分钟不懈工作，也可能陷在错误假设循环里。

### 2.4 Software 3.0 工程五支柱
1. **Prompt-oriented architecture**：提示词纳入版本控制，像代码一样测试。
2. **Guard-railed execution**：每次模型调用包验证器（正则、单测、类型检查）。
3. **Tight generate/verify cycles**：延迟预算要包含自动批判 / 人工审查的"绕路"。
4. **Agent-friendly infrastructure**：llms.txt、结构化 markdown、自描述 API，让 bots 也能消费你的产品。
5. **Observability for cognition**：记录 token 流与系统消息，检视 agent "为何行动"而非仅"返回了什么"。

### 2.5 上下文工程 + DAG 编排 + 垂直 GUI + 自治滑块（Cursor 启示）
- 深度 LLM 应用不只是模型接口，而是四类职能：**(1) 上下文工程、(2) 多次调用的 DAG 编排、(3) 垂直化 GUI、(4) 自治度控制**。
- 模型厂商提供"通才大学生"，垂直应用把它组织成"职场专业人士"（私有数据 + 反馈闭环）。

### 2.6 本地 agent（Claude Code 启示）
- 第一个令人信服的本地 agent：直接在用户电脑（localhost）运行，**靠近私有上下文、低延迟**。
- 重点不是"云 vs 本地"，而是"哪个环境已有启动好的上下文/数据/低延迟交互"。
- 本地 agent 须有严格的**秘密管理、权限控制、审计日志**。

### 2.7 Vibe Coding（氛围编码）
- 用自然语言直接生成有用程序，代码变得"短命、可丢弃、可迭代"。
- 让 LLM 做"建筑工人"而非"建筑师"；把架构与关键设计决策留给人类审查。
- 风险：vibe 产出可能"看似合理但含隐蔽错误"——**必须把自动化测试融入生成流程**。

### 2.8 Benchmaxxing 警示（不可游戏化的评测）
- 实验室在基准测试嵌入空间附近构建微小环境人为"长能力锯齿"覆盖测试集，即"新的艺术"。
- 即使横扫榜单，也可能未触及真实能力；需构建**不可游戏化、跨域、长尾**的评测。

### 2.9 个人 LLM 编码工作流四层（按频率递减）
- L1 Tab 自动补全（75%）→ L2 高亮修改（15%）→ L3 并排助手/agent（10%，多文件重构/修复/测试，需信任但验证）→ L4（更高自治）。
- 关键洞察：**代码比自然语言更直接，能最小化沟通开销**；高自治任务需要信任但验证。

---

## 3. 对 Baize 有用的提炼（思想 → 落地映射）

| 卡帕西思想 | 对 Baize 的启示 | 白泽现有落地 / 对应升级项 |
|------------|----------------|---------------------------|
| **锯齿智能 + Guard-railed execution** | LLM 不可全信，每次调用必须包验证环 | ✅ Verifier 独立核验、manifest 物理核验（NO FAKE DONE）；🔜 P3-1 不可游戏化基准 |
| **部分自主 + keep AI on the leash** | 用绳拴住 AI，逐步扩展自治边界 | ✅ fail-closed deny-list、沙箱默认开；🔜 P0-1 OS 沙箱、P2-1 Plan mode 显式确认 |
| **Prompt-oriented（提示词当代码测）** | 规约/技能应版本化、可测试 | ✅ AGENT.md/SKILL.md 版本化、index 动态发现；🔁 持续 |
| **Observability for cognition** | 记录 agent 为何行动，可审计 | ✅ observability（span+指标+Prometheus）；🔼 增强 |
| **Agent-friendly infra（llms.txt/结构化）** | 自描述规约让 agent/bot 可消费 | ✅ 第一层规约包可被 Claude Code/Codex 加载；🔼 扩 AGENTS.md 兼容（P0-2） |
| **Benchmaxxing 警示** | 评测不可游戏化，拒绝刷分 | 🔜 P3-1 用真实端到端任务 + 证据物理核验，而非 Terminal-Bench 式刷榜 |
| **本地 agent（秘密管理/审计）** | 本地运行 + 严格权限/审计 | ✅ 零依赖本地 CLI/运行时；🔜 P0-1 OS 沙箱 + 秘密管理 |
| **奥卡姆 / 无聊栈** | 最简成熟技术，不堆依赖 | ✅ 纯 stdlib 零依赖；🔒 升级须保持核心不污染（MCP/Hooks 走可选适配层） |
| **Vibe Coding + 防隐蔽错误** | 自然语言生成但须测试把关 | ✅ save_skill 沉淀 vibe 产出；Verifier 对 vibe 结果独立核验 |
| **自治滑块 / Cursor 四职能** | 暴露自治度、DAG 编排、垂直 GUI | ✅ orchestrator（Director→Executor→Verifier）即 DAG；TUI/Web 即垂直 GUI；🔜 P2-1 权限模式即自治滑块 |

---

## 4. 思想闭环：卡帕西准则如何指导 V21

白泽 V21 不是背离初始思想，而是把卡帕西在 2025 年系统化的原则，从"哲学"变成"更完备的工程能力"：

- **锯齿智能 → guard-rail 深化**：V21 的 P3-1（不可游戏化基准）、P0-1（OS 沙箱）都是在 LLM 不可全信的前提下，把"验证环"从 manifest 扩展到运行隔离与公开评测。
- **部分自主 → leash 深化**：P2-1 Plan mode（只读确认后执行）、P0-1 沙箱，都是"把 AI 拴在绳上、逐步扩展自治"的工程实现。
- **Observability → 可审计深化**：P3-3 门禁产品化、CI 门禁插件，让"为何行动"可被团队回溯。
- **奥卡姆 → 零依赖不可破**：所有升级项（尤其 MCP/Hooks）必须作为可选适配层，默认不启用，绝不污染纯 stdlib 核心——这是白泽与 Codex/Claude Code（Rust/TS 重栈）最根本的分野。

> 结论：**白泽的差异化不在"功能数量追上主流"，而在它从第一天起就把卡帕西的"精确对抗幻觉"做成了可证明的工程机制（NO FAKE DONE）。V21 的全部升级，都是这一灵魂的外部扩容。**

---

## 5. 来源与时效

- 项目内：`assets/skills/karpathy_coding/SKILL.md`、`README.md`、`docs/baize-agent-V20交付文档.md`。
- 卡帕西公开：YC AI Startup School 2025-06《Software in the era of AI》；2025 LLM Year in Review（karpathy.bearblog.dev/year-in-review-2025/）；个人 LLM 编码工作流（2025-08 公开访谈/帖）。
- ⚠️ 卡帕西的观点随其公开表达持续演进；本归纳截至 2026-08-14，以原始出处最新状态为准。
