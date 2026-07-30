# Baize Engine (白泽引擎) V20.0.0

一套面向 AI Agent 的**白盒工程化研发操作系统**：**方法论技能包 + 真实 Agent 运行时** 双层架构。
V20 在 V19「规约 + 校验工具 + 自主运行时」基础上，吸收 hermes-agent（自主循环 / 模型无关客户端 /
自进化技能）与 pi（极简内核 / 原语工具 / JSONL 会话持久化）的核心设计，并**全量解决甲方 8 角色
专家团队验收报告中的 P0/P1/P2 问题，新增反思规划、长程记忆压缩、RAG 数据层、TUI/Web 仪表盘、
协作记忆、混沌韧性、CI/Docker 工程化**，同时保持**零第三方运行时依赖**。

> 交付文档：`docs/baize-agent-V20-交付文档.md`（操作手册 / 功能清单 / hermes·pi 对比 / 特有功能 / 升级说明）
> 验收基线：`docs/baize-agent-V19甲方专家团队验收报告.md`　量化对标：`benchmarks/COMPARISON.md`

## 架构

```
┌──────────────────────────────────────────────────────────┐
│  第一层：规约与技能（被 AI 客户端加载，或注入 Agent 提示词）│
│  AGENT.md（操作协议） SKILL.md（流水线规约）              │
│  assets/skills/（本地方法论技能）                         │
│  外部技能库（SKILL_LIBRARY_PATHS，249 唯一技能）          │
├──────────────────────────────────────────────────────────┤
│  第二层：baize 运行时（纯 stdlib，零第三方依赖）          │
│                                                          │
│  ◆ Agent 内核（V20 增强）                               │
│    llm          模型无关 OpenAI 兼容客户端（速率限制/退避）│
│    agent        反思规划 + 自主循环 + 长程记忆压缩        │
│    tools        9 原语工具 + SDK 扩展（进程级单例注册表） │
│    orchestrator Director→Executor→Verifier（Verifier 硬化）│
│    team_memory  协作记忆白板（跨角色共享上下文）          │
│                                                          │
│  ◆ 数据层（V20 新增）                                   │
│    vector       TF-IDF 向量检索（embedding 接口预留）     │
│    rag          技能+记忆统一 RAG 检索增强 + 技能评分      │
│    graph        知识图谱三元组存储                       │
│    bench        确定性核心基准套件                       │
│                                                          │
│  ◆ 交互层（V20 新增）                                   │
│    ui           TUI 进度渲染（阶段/工具/反思/计划）       │
│    dashboard + serve  Web 仪表盘 + REST 服务             │
│                                                          │
│  ◆ 工程化（V20 新增）                                   │
│    observability  span+指标+Prometheus 导出              │
│    logging_setup  结构化 JSON 日志 + 脱敏                │
│    chaos         故障注入韧性验证                        │
│    plugin        可插拔验证钩子 / 指标插件               │
│    config_schema 强类型配置校验                           │
│                                                          │
│  ◆ 校验与记忆（保留并增强）                              │
│    doctor       环境门禁（真实探测，真实退出码）          │
│    skill index  技能索引与检索（3 来源去重）              │
│    manifest     流水线门禁（证据物理核验）                │
│    memory       跨会话持久记忆 + 长程压缩                │
└──────────────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 0. 安装（类 hermes/pi 的一键体验）
python install/bootstrap.py        # 或：cp .env.example .env

# 1. 环境门禁（任何工作开始前必须通过）
python -m baize doctor

# 2. 构建技能索引
python -m baize index build
python -m baize index search tdd

# 3. 运行单 Agent（V20：反思规划 + TUI 进度；需 .env 配置模型端点）
python -m baize run "为 utils.py 补齐单元测试"
python -m baize run "继续上次任务" --resume <session_id>

# 4. 多 Agent 团队（Director 规划 → Executor 执行 → Verifier 核验）
python -m baize team "实现用户登录接口并端到端验证"

# 5. RAG 检索增强（V20）
python -m baize rag search "deploy to prod" --top-k 5

# 6. Web 仪表盘（V20）
python -m baize serve --port 8787

# 7. 核心基准（V20）
python -m baize bench

# 8. 校验与记忆
python -m baize manifest validate projects/simple-shopping-platform/manifest.json
python -m baize memory log "今日事件" --tags dev
python -m baize memory recall 关键词
python -m baize memory compress --days 30

# 9. 运行测试
python -m pytest tests/
```

## 目录结构

| 目录 | 职责 |
|------|------|
| `baize/` | 运行时 26 模块（零第三方依赖） |
| `tests/` | 真实测试套件（144 个 pytest，脚本化 transport 驱动） |
| `assets/skills/` | 本地方法论技能（毛选战略、卡帕西编码、picasso-dev 系列） |
| `install/` | 一键引导脚本（bootstrap.py / setup.sh / install.bat） |
| `persistence/` | 持久记忆（gitignored：logs/*.jsonl、notes.md、skill_index.json、sessions/） |
| `openspec/` | 规格库（每个运行时模块一份 spec） |
| `benchmarks/` | 与 hermes-agent / pi 的对标基准 |
| `docs/` | 交付文档（V20 交付文档 / V19 验收报告 / 重构报告） |
| `.github/workflows/ci.yml` | CI（跨 OS × Python 3.10–3.13、零依赖校验、覆盖率门禁、Docker） |
| `Dockerfile` | 镜像（非 root、/data 可写、健康检查） |

## 核心原则

1. **NO FAKE DONE** — manifest 的 phase 标记 done，其 evidence 文件必须物理存在；Verifier 独立核验，失败自动重试（`orchestrator.py` 强制执行）。
2. **调查先行** — 决策前先调查（见 `assets/skills/strategic/maozx-investigation`）。
3. **外科手术式变更** — 最小 diff、无关代码零改动（见 `assets/skills/karpathy_coding`）。
4. **技能不复制** — 外部技能库通过 `SKILL_LIBRARY_PATHS` 配置化引用，索引器动态发现。
5. **沙箱默认开启** — Agent 工具限制在 `BAIZE_WORKSPACE_DIR` 内，危险命令 deny-list fail-closed 拦截。
6. **会话即事实** — 每次运行产生 JSONL 转录，崩溃不丢状态，可审计可续跑。
7. **防御式设计可证明** — 混沌注入真实故障验证 Agent 不崩溃（`chaos.py`），而非声称。
8. **零运行时依赖** — 运行时纯标准库；工程化只靠 pytest / pytest-cov（仅测试期）。

## 版本

- 当前版本：**V20.0.0**（所有顶层文档与 `baize.__version__` 同步）
- 测试：**144 passed**，覆盖率 **80%**（防御式 fail-closed 分支为主，阈值 80%）
- 第三方运行时依赖：**0**
