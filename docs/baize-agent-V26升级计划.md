# Baize Agent V26 升级计划：闭环内核强化 + 生态能力收敛

> **定位**：V26 不推倒 V25，也不把 Baize 改造成重依赖的通用聊天平台。它以
> 「研发闭环可执行化」为主线，同时有节制地补齐向量、渠道、UI、角色和模型生态。
>
> **版本**：v1.0（规划稿）  
> **前置版本**：V25.0.0  
> **状态**：待用户批准后进入规格设计；本计划本身不授权开始编码、提交或发布。

---

## 1. 北极星与边界

### 1.1 北极星

> **让 Baize 的每一次研发行动，都能从目标出发，经受控执行和独立验证，留下可复用经验，并在中断后无歧义地继续。**

Baize 是「规约与技能层 + 零依赖 Agent 运行时」组成的研发操作系统。V26 的成功
不以工具数量、角色数量或榜单数字判断，而以闭环是否真实运行判断。

### 1.2 必守红线

| 编号 | 红线 | V26 约束 |
| --- | --- | --- |
| A | 零依赖核心 | `baize/` 继续只使用 Python stdlib；可选能力只放 `baize/ext/`，延迟导入、缺失 fail-closed。 |
| B | NO FAKE DONE | 一切“完成/支持/兼容”都有测试、命令输出或 evidence；未知即明确标 `UNKNOWN` / `reserved`。 |
| C | manifest 唯一项目事实 | 项目 phase 状态只由 manifest 表达；其他记录只能补充证据，不能形成并行状态源。 |
| D | 最小演进 | 复用 `orchestrator`、`ToolRegistry`、`Session`、`skill_index`、`get_backend()`，不新造平行框架。 |
| E | 受控自主 | 角色、工具、模型、记忆写入和技能沉淀都须经过显式策略或验证门。 |

---

## 2. 矛盾分析与总策略

### 2.1 主要矛盾：闭环尚未完全运行时化

现有 Baize 已拥有调查/澄清、Director→Executor→Verifier、manifest、memory、
skills、session、doctor、gate 等关键部件；但它们之间仍有一部分靠协议文本和模型自觉
衔接。V26 的首要任务是把下列因果链变成运行时可执行、可恢复、可审计的状态链：

```text
目标与约束
  → 澄清/侦察
  → 原子任务与验收检查
  → 最小权限执行
  → 独立验证与 evidence
  → manifest 状态迁移
  → 事实/经验/技能沉淀
  → 下一次任务的检索与复用
```

**主策略**：不另起 workflow engine；以 manifest 为项目状态源，给现有会话、计划、
验证和记忆增加可关联的契约与事件证据。

### 2.2 次要矛盾：生态与交互能力仍需补齐

以下能力确实影响 Baize 的工业可用性，但只能服务于主闭环，不能反客为主：

| 次要矛盾 | V26 处理原则 |
| --- | --- |
| 稠密向量/语义检索缺失 | 复用现有 `vector.get_backend()`，做可选 ext 后端；TF-IDF 仍是零依赖默认。 |
| 聊天渠道不足 | 做统一会话适配契约；CLI/REST 继续是核心，渠道仅是外层输入输出。 |
| UI 对项目过程呈现不足 | 不重做前端；强化既有 Dashboard/TUI 的“任务—证据—verdict—学习”可视化。 |
| 角色与协作深度不足 | 不盲增常驻 Agent；把现有角色真正策略化，并按任务临时派生受限专长角色。 |
| 模型供应商广度/能力不透明 | 统一真实 capability 合约、路由与降级证据；优先正确性与可诊断性，而非供应商名单。 |

### 2.3 当前阶段的主次关系

闭环未打通时，向量、UI、渠道、角色、模型只会制造更多没有证据的“入口”和“输出”。
因此资源比例固定为：**70% 主矛盾、20% 次要矛盾的最小闭环接入、10% 质量与文档收口**。
任何次要能力若不能回写任务、证据、verdict 或学习记录，即不进入 V26。

---

## 3. 目标架构：一个事实源，四类记录

### 3.1 记录职责

| 载体 | 职责 | 是否可改变项目状态 |
| --- | --- | --- |
| `manifest.json` | P1–P12 phase、evidence、当前项目事实 | **是，唯一来源** |
| `task_decomposition.json` | P4 的原子任务、依赖、验收检查；作为 manifest evidence | 否 |
| `persistence/runs/<run-id>.jsonl` | 目标、计划、工具、验证、状态迁移的 append-only 运行账本 | 否，只能证明迁移 |
| `persistence/sessions/*.jsonl` | 模型交互原文、恢复上下文、审计 | 否 |
| memory / skill index | 已验证事实与可复用流程 | 否 |

### 3.2 闭环契约（V26 Core Contract）

新增轻量 `ProjectContract` 概念，围绕既有 manifest 实现，不取代它。每个原子任务至少
声明：

- `id`、目标、前置任务、允许角色；
- 允许工具和工作区范围；
- 预期产物与 evidence 路径；
- 机器可执行检查（文件、内容、命令）和人工审查说明；
- Verifier 判据、失败原因和重试上限；
- 可沉淀的事实/技能候选条件。

状态迁移仅允许：`pending → in_progress → verified → done`；其中 `verified` 必须带有
独立 Verifier 的 evidence。写回 manifest 时仍采用现有 `done`，`verified` 作为运行账本
中的过渡记录，避免修改 P1–P12 的事实模型。

### 3.3 角色策略（不是角色堆砌）

| 角色 | V26 强制边界 | 输出 |
| --- | --- | --- |
| Clarifier / Recon | 只调查、澄清和记录假设，不改业务文件 | P1/P2 输入 |
| Director | 只分解任务、声明 checks/evidence，不执行 | P4 原子任务 |
| Executor | 仅当前任务、最小工具集、最小工作区 | 产物 + 执行记录 |
| Verifier | 独立 session/取证，不信任 Executor 总结 | verdict + evidence + issues |
| Memory Curator | 只接收 verified 结论 | 事实/教训记忆 |
| Skill Curator | 只接收通过验证的候选流程 | skill 接纳或拒绝记录 |

现有 `team.py` 的 `system_prompt`、`tools`、`model`、`permission_mode` 必须在构建 Agent
时真实生效；未接线的字段不得继续对外宣传为能力。

---

## 4. V26 战役拆分

### 战役 A：V26.0 闭环事实内核（主矛盾，先做）

**目标**：将“规约”编译为可执行的任务契约与证据链。

| 工作包 | 最小实现 | 复用点 | 验收证据 |
| --- | --- | --- | --- |
| A1 契约 | 定义原子任务 JSON schema、checks、evidence、verifier criterion | manifest / atomic decomposition | 有效/无效 schema 测试 |
| A2 运行账本 | 对 plan、task start、tool result、verification、迁移写入 JSONL | Session | 可重建任务当前状态 |
| A3 状态门 | 只有 verifier pass + declared checks pass 才允许 manifest `done` | orchestrator / manifest | 负例拒绝测试 |
| A4 恢复 | `--resume` 同时恢复 session 和未完成任务，不重复已验证工作 | sessions | 中断恢复端到端测试 |
| A5 闭环报告 | CLI 输出当前任务、阻塞、evidence、下一动作 | cli / TUI | 真实 fixture 报告 |

**不做**：新数据库、分布式调度、复杂 BPMN、第二套项目状态文件。

### 战役 B：V26.1 受控角色与验证闭环（主矛盾）

**目标**：使多 Agent 从提示词分工升级为真实权限与独立核验。

| 工作包 | 最小实现 | 验收证据 |
| --- | --- | --- |
| B1 RolePolicy | `role → prompt + model + allow-list + workspace + memory visibility` 真实注入 | 各字段影响实际 Agent 的端到端测试 |
| B2 原子执行 | Executor 一次只领取一个未完成任务；任务领取写入账本 | 不能越权领取/重复领取的负例 |
| B3 验证执行器 | 优先执行 Director 声明的 machine checks，再让 Verifier 补充判断 | Executor 虚报完成仍被拒绝 |
| B4 失败反馈 | issues 结构化回流并限定重试；失败保留为项目事实 | 重试耗尽后状态正确停止 |
| B5 安全策略 | 将 plan/safe-review 的读写边界与 RolePolicy 合并 | 高风险工具被实际阻断 |

**不做**：默认常驻十几个角色；角色数量由任务契约决定，不由营销定义。

### 战役 C：V26.2 学习闭环与知识质量（主矛盾收口）

**目标**：让记忆和自进化只沉淀已证明的经验。

| 工作包 | 最小实现 | 验收证据 |
| --- | --- | --- |
| C1 记忆分层 | 区分事实、决策、假设、失败教训，保留来源 run/task/evidence | recall 能返回来源链 |
| C2 收尾器 | verified task 自动生成“可记忆项/skill candidate”，但不自动宣告成功 | 候选生成与拒绝测试 |
| C3 Skill 审核 | 复用 `verify_skill_draft`，补来源、依赖、适用边界、验证命令 | 无 evidence 的技能不得入库 |
| C4 复用反馈 | skill 使用后记录成功/失败/原因，支持降权或退役 | audit 输出真实有效性 |
| C5 质量门 | gate 增加闭环完整性维度，不用静态文件存在替代流程事实 | 缺任一关键记录即 fail/unknown |

**不做**：自动无限生成技能、将模型猜测写入长期记忆、为“自进化”制造假指标。

### 战役 D：V26.3 次要矛盾的最小接入（在 A–C 通过后）

#### D1 稠密向量与检索

- 只在 `baize/ext/vector/` 提供可选后端，复用既有 `get_backend()`；核心 TF-IDF 不动。
- 后端缺失时返回明确 unavailable，不暗降为“语义检索成功”。
- 检索命中必须携带来源 task/run/evidence，服务学习闭环。

#### D2 聊天渠道

- 定义统一 `ConversationAdapter`：`inbound → run contract → outbound`。
- V26 仅选择 **一个** 高价值渠道做真实闭环联调；CLI/REST 仍是基准入口。
- 渠道不得绕过 workspace、RolePolicy、session、manifest 或 approval。

#### D3 UI / Dashboard

- 不重写前端；在既有 Dashboard/TUI 增加项目流程视图：phase、当前原子任务、checks、
  evidence、verdict、重试、学习候选。
- UI 只呈现账本事实；不提供能绕过状态门的“手动完成”按钮。

#### D4 专长角色

- 提供任务契约驱动的临时 Researcher / Reviewer / Test Engineer 等角色模板。
- 所有专长角色仍须进入 Director→Executor→Verifier 主闭环；不出现平行指挥链。

#### D5 模型与供应商

- 定义 provider capability 合约：stream、tools、reasoning、structured output、context
  limit、错误语义；未知 provider 默认保守声明。
- 路由选择写入运行账本；失败、降级和重试均可审计。
- V26 只补最常用且无法由 OpenAI-compatible endpoint 覆盖的差异能力。

---

## 5. 实施顺序与依赖

```text
A1 契约 ─┬→ A2 账本 ─→ A3 状态门 ─→ A4 恢复 ─→ A5 报告
          │
          └→ B1 RolePolicy ─→ B2/B3/B4/B5
                                      │
                                      └→ C1/C2/C3/C4/C5
                                                   │
                                                   └→ D1–D5（可小批次并行）
```

每个工作包先写 OpenSpec，再写失败测试，再实现；一个工作包的退出条件未满足，不启动依赖
它的下一包。D1–D5 中任何一项都不能阻塞 A–C 的发布。

---

## 6. 测试、评测与发布门禁

### 6.1 必测闭环场景

1. 模糊需求 → 澄清记录 → 计划 → 原子任务 → 实现 → checks → verifier pass → manifest done。
2. Executor 声称完成但未产生 evidence：不得推进。
3. tests/checks 失败：Verifier fail，issues 回流，重试耗尽后项目停在可解释状态。
4. 中断后 resume：只继续未验证任务，已验证 evidence 不被重复核销。
5. memory/skill candidate 无验证来源：必须拒绝或标记待审，不能自动进入长期库。
6. 可选向量、渠道、UI、模型插件缺失：核心闭环仍可运行，能力状态明确为 unavailable。

### 6.2 发布门禁

- `doctor` PASS；manifest VALID；全量 pytest PASS。
- V26 新增闭环 fixture 全绿，且至少包含成功、失败、恢复、拒绝四类物理证据。
- `gate` 的闭环完整性为 PASS；coverage 没有采集时维持 UNKNOWN，不能对外伪称通过。
- 默认核心运行时仍通过 stdlib AST 审计；核心无顶层 `import baize.ext`。
- 所有对外版本号、测试数、技能数、支持矩阵由真实命令输出或 CI 产物生成。
- 每个 D 类能力至少有一个真实联调；未联调项标 `reserved`，不进入 release notes 的“已支持”。

---

## 7. 明确的战略放弃

V26 不做以下事项，避免稀释主矛盾：

- 不迁移为 Node/Electron 或引入重型核心依赖；
- 不构建通用协作平台、云同步、富文本看板；
- 不以 GitHub star、角色数量、模型数量作为完成指标；
- 不为了跑分伪装或选择性披露 benchmark；
- 不新建与 manifest、Session、ToolRegistry 平行的项目状态、会话或工具系统；
- 不把未接线、reserved、mock-only 的能力放进“已完成”宣传。

---

## 8. V26 完成定义

V26 完成，不是“多支持了多少功能”，而是满足下面的可证明陈述：

> 对任一 Baize 管理的项目，维护者可以从 manifest 和运行账本中复原：目标与约束、当前
> 原子任务、谁以何权限执行、产生了什么产物、Verifier 如何独立验证、为什么状态迁移、
> 哪些结论被沉淀、下次如何复用；任一环节缺失时，系统不会把项目报告为完成。

这时向量、渠道、UI、专长角色和模型生态会成为这条闭环的放大器，而不是新的碎片化来源。
