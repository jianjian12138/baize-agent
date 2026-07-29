# Baize Engine (白泽引擎) V19.0.0

一套面向 AI Agent 的工程化研发操作系统：**方法论技能包 + 真实 Agent 运行时** 双层架构。
V19 在 V18「规约 + 校验工具」的基础上，吸收 hermes-agent（自主循环 / 模型无关客户端 /
自进化技能）与 pi（极简内核 / 原语工具 / JSONL 会话持久化）的核心设计，升级为可独立
运行的 Agent 系统：既可驱动单 Agent 自主完成开发工作，也可编排 Director→Executor→Verifier
多 Agent 团队执行任务。

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
│  ◆ Agent 内核（V19 新增）                                │
│    llm          模型无关 OpenAI 兼容客户端（任意端点）    │
│    tools        工具注册表：9 内置工具 + 沙箱 + deny-list │
│    agent        自主循环：思考→工具→观察→迭代             │
│                 JSONL 会话持久化，崩溃可 --resume 续跑    │
│    orchestrator Director→Executor→Verifier 多 Agent 编排 │
│                 验证失败自动带 issues 重试（NO FAKE DONE）│
│                                                          │
│  ◆ 校验与记忆（V18 保留）                                │
│    doctor       环境门禁（真实探测，真实退出码）          │
│    skill index  技能索引与检索（3 来源去重）              │
│    manifest     流水线门禁（证据文件必须物理存在）        │
│    memory       跨会话持久记忆（多关键词+tags+相关性评分）│
└──────────────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 1. 配置环境
cp .env.example .env        # 配置 SKILL_LIBRARY_PATHS 与模型端点

# 2. 环境门禁（任何工作开始前必须通过）
python -m baize doctor

# 3. 构建技能索引
python -m baize index build
python -m baize index search tdd

# 4. 运行自主 Agent（V19，需在 .env 配置模型端点）
python -m baize run "为 utils.py 补齐单元测试"
python -m baize run "继续上次任务" --resume <session_id>

# 5. 多 Agent 团队（Director 规划 → Executor 执行 → Verifier 核验）
python -m baize team "实现用户登录接口并验证"

# 6. 会话管理
python -m baize sessions                # 列出全部会话
python -m baize sessions <session_id>   # 查看会话转录

# 7. 校验与记忆
python -m baize manifest validate projects/simple-shopping-platform/manifest.json
python -m baize memory log "今日事件" --tags dev
python -m baize memory recall 关键词

# 8. 运行测试
python -m pytest tests/
```

## 目录结构

| 目录 | 职责 |
|------|------|
| `baize/` | 运行时 10 模块（agent/llm/tools/orchestrator + doctor/index/manifest/memory + config/cli），零第三方依赖 |
| `tests/` | 运行时真实测试套件（69 个 pytest，脚本化 transport 驱动，无 mock 屏蔽） |
| `assets/skills/` | 本地方法论技能（毛选战略 11 项、卡帕西编码、picasso-dev 系列） |
| `assets/docs\|prompts\|templates/` | 文档、提示词与模板资产 |
| `projects/` | 项目工作区（示例：simple-shopping-platform，Go+Vue3） |
| `persistence/` | 持久记忆（logs/*.jsonl、notes.md、skill_index.json、sessions/） |
| `openspec/` | 规格库（每个运行时模块一份 spec + 测试映射） |
| `benchmarks/` | 与 hermes-agent / pi 的对标基准 |
| `legacy/` | V17 归档（旧 engine 与旧配置，仅供追溯） |

## 核心原则

1. **NO FAKE DONE** — manifest 的 phase 标记 done，其 evidence 文件必须物理存在；
   多 Agent 编排中 Verifier 独立核验，验证失败自动重试（`orchestrator.py` 强制执行）。
2. **调查先行** — 决策前先调查（见 `assets/skills/strategic/maozx-investigation`）。
3. **外科手术式变更** — 最小 diff、无关代码零改动（见 `assets/skills/karpathy_coding`）。
4. **技能不复制** — 外部技能库通过 `SKILL_LIBRARY_PATHS` 配置化引用，索引器动态发现。
5. **沙箱默认开启** — Agent 工具限制在 `BAIZE_WORKSPACE_DIR` 内，危险命令 deny-list
   fail-closed 拦截。
6. **会话即事实** — 每次 Agent 运行都产生 JSONL 转录，崩溃不丢状态，可审计可续跑。

## 版本

- 当前版本：**V19.0.0**（所有顶层文档与 `baize.__version__` 同步）
- V17 时代资产已归档至 `legacy/`，其中的验证逻辑含模拟通过，禁止在生产流程中引用。
