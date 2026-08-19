# Baize Agent — zero-dependency autonomous agent runtime (白泽引擎) · V23.0.0

[![tests](https://img.shields.io/badge/tests-422%20passed%20%2F%201%20skipped-brightgreen)](https://github.com/jianjian12138/baize-agent)
[![license](https://img.shields.io/badge/license-MIT-blue)](https://opensource.org/licenses/MIT)
[![python](https://img.shields.io/badge/python-3.10%2B-3776AB)](https://www.python.org/)
[![runtime deps](https://img.shields.io/badge/runtime%20deps-0-lightgrey)](https://github.com/jianjian12138/baize-agent)
[![version](https://img.shields.io/badge/version-V23.0.0-orange)](https://github.com/jianjian12138/baize-agent)

> **EN** — A white-box, engineering-driven autonomous Agent runtime in **pure Python standard library (zero third-party runtime deps)**. Ships a method-skills layer + a real Agent runtime, verified by a **NO FAKE DONE** gate (manifest evidence + `doctor`/`gate`/pytest). V24 slimmed the system and unified files/docs/code-style/folders.
>
> **中文** — 一套面向 AI Agent 的**白盒工程化研发操作系统**：**方法论技能包 + 真实 Agent 运行时**双层架构，运行时**零第三方依赖**，以 **NO FAKE DONE** 门禁（manifest 证据 + doctor/gate/pytest）保证「不假绿」。V24 完成系统瘦身与文件/文档/代码风格/文件夹统一化。

---

## Why Baize (差异化)

- **Zero third-party runtime deps** — `baize/` is pure `stdlib`; air-gapped / audited / embedded-safe by construction.
- **NO FAKE DONE verified** — a phase marked `done` must have physically-present evidence; Verifier re-checks independently; chaos injects real failures.
- **Plugin & skills architecture** — `component`/`modes` composition kernel + 3 skills libraries, config-driven, fail-closed.
- **Autonomous + multi-agent** — reflection planning, self-loop, `orchestrator` (Director→Executor→Verifier), `team` with shared `team_memory`.
- **Servable** — `baize serve` exposes a REST endpoint built-in; no extra gateway.

## Comparison with leading frameworks (对比头部框架)

Honest, dimension-by-dimension (V23.0.0). baize wins on **deps / audit surface / verification gate**; it is honest where it is behind.

| Dimension | **Baize** | LangChain | AutoGPT | CrewAI | MetaGPT | Dify |
|-----------|-----------|-----------|---------|--------|---------|------|
| Runtime 3rd-party deps | **0** | many | many | many | many | many |
| Audit surface (code to review) | **tiny (stdlib, ~468 KB)** | large | large | large | large | large |
| Verification gate (NO FAKE DONE) | **yes (manifest+gate)** | no | no | no | no | partial |
| Visual / drag-drop UI | Web dashboard only | no | no | no | no | **yes** |
| RAG | TF-IDF lexical (dense backend *planned*) | strong | n/a | n/a | n/a | strong |
| Multi-agent | yes (orchestrator+team) | partial | yes | **strong** | **strong** | partial |
| Built-in HTTP serve | **yes** | no | no | no | no | yes |

> baize does **not** try to beat LangChain/CrewAI on ecosystem breadth. Its niche: **zero-dependency + verifiable** agent runtime for security-/audit-/embedded-sensitive scenarios where the big frameworks cannot go.

---

## Quick Start (3 steps)

```bash
# 1. Environment gate (must pass before any work)
python -m baize doctor

# 2. Run a single agent (needs a model endpoint in .env)
python -m baize run "write unit tests for utils.py"

# 3. Serve a REST endpoint
python -m baize serve --port 8787
```

<details>
<summary>Full quick start (10 steps)</summary>

```bash
# 0. Install (one-click, hermes/pi-style)
python install/bootstrap.py        # or: cp .env.example .env

# 1. Environment gate (must pass before any work)
python -m baize doctor

# 2. Build skill index
python -m baize index build
python -m baize index search tdd

# 3. Run a single agent (reflection planning + TUI progress; needs .env model endpoint)
python -m baize run "write unit tests for utils.py"
python -m baize run "continue last task" --resume <session_id>

# 4. Multi-agent team (Director plans → Executor runs → Verifier checks)
python -m baize team "implement login API and verify end-to-end"

# 5. RAG retrieval augmentation
python -m baize rag search "deploy to prod" --top-k 5

# 6. Web dashboard
python -m baize serve --port 8787

# 7. Core benchmarks
python -m baize bench

# 8. Validate & memory
python -m baize manifest validate projects/simple-shopping-platform/manifest.json
python -m baize memory log "today's event" --tags dev
python -m baize memory recall keyword
python -m baize memory compress --days 30

# 9. Run tests
python -m pytest tests/

# 10. Plugin extension (V22): register custom components via BAIZE_COMPONENTS, no call-site change
#     tutorial: docs/tutorials/08-写一个baize组件.md
export BAIZE_COMPONENTS="your_module:YourComponent"   # optional, explicit override
python -m baize gate          # honest gate: real assembly + protocol check + coverage
```
</details>

---

## 架构 (Architecture)

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
│  ◆ 组合内核（V22 新增）                                 │
│    component     统一组件契约 + CompositionKernel        │
│                  （9 类 Kind，配置驱动装配，fail-closed） │
│    modes         命名模式 = 组件集                       │
│                  （coding/eval/autonomous/safe-review，   │
│                   显式 BAIZE_MODE 优先于标量滑块）        │
│                                                          │
│  ◆ 工程化（V20 新增）                                   │
│    observability  span+指标+Prometheus 导出              │
│    logging_setup  结构化 JSON 日志 + 脱敏                │
│    chaos         故障注入韧性验证                        │
│    plugin        钩子体系 + 组件自动发现                 │
│                  （防御性隔离，绝不默认可信）             │
│    config_schema 强类型配置校验（含 BAIZE_COMPONENTS）    │
│                                                          │
│  ◆ 校验与记忆（保留并增强）                              │
│    doctor       环境门禁（真实探测，真实退出码）          │
│    skill index  技能索引与检索（3 来源去重）              │
│    manifest     流水线门禁（证据物理核验）                │
│    memory       跨会话持久记忆 + 长程压缩                │
└──────────────────────────────────────────────────────────┘
```

## 目录结构 (Directory)

| 目录 | 职责 |
|------|------|
| `baize/` | 运行时 40+ 模块（纯 stdlib，含 V22 组合内核 `component` / `modes`） |
| `tests/` | 真实测试套件（422 个 pytest，1 跳过，脚本化 transport / 组件装配驱动） |
| `examples/` | 可运行示例（含自定义组件最小示例 `logged_sandbox.py`） |
| `assets/skills/` | 本地方法论技能（毛选战略、卡帕西编码、picasso-dev 系列） |
| `install/` | 一键引导脚本（bootstrap.py / setup.sh / install.bat） |
| `persistence/` | 持久记忆（gitignored：logs/*.jsonl、notes.md、skill_index.json、sessions/） |
| `openspec/` | 规格库（每个运行时模块一份 spec） |
| `benchmarks/` | 与 hermes-agent / pi 的对标基准 |
| `docs/` | 面向用户的活文档：当前版本 `VERIFICATION_V24.md`（最新瘦身/统一化验收）、`VERIFICATION_V23.md`、`baize-agent-V23升级路线图.md`、`baize-agent-操作手册与功能清单`、`baize-设计思想溯源`、`COMPARISON-四引擎对比`、`SKILL-LIBRARIES.md`（三技能库结构与去重说明），以及 `tutorials/`（10 篇上手教程）。历史交付 / 验收 / 计划报告统一存放在 `docs/archive/`（V18–V22） |
| `.github/workflows/ci.yml` | CI（跨 OS × Python 3.10–3.13、零依赖校验、覆盖率门禁、Docker） |
| `Dockerfile` | 镜像（非 root、/data 可写、健康检查） |

## 文档导航 (Documentation)

两个目录职责互补，请勿混用：

- **`docs/` — 给人看的文档**（叙事性、可阅读）
  - 操作手册 / 功能清单、设计思想溯源、四引擎对比、10 篇 `tutorials/` 上手教程
  - 当前版本（V24）文档：`VERIFICATION_V24.md`（V24 瘦身/统一化验收）、`VERIFICATION_V23.md`、`baize-agent-V23升级路线图.md`、`baize-agent-操作手册与功能清单`、`baize-设计思想溯源`、`COMPARISON-四引擎对比`、`SKILL-LIBRARIES.md`（三技能库结构与去重说明）留在 `docs/` 根
  - 历史版本（V18–V21）的交付报告、验收报告、升级路线图集中在 `docs/archive/`，便于追溯但不干扰当前阅读
- **`openspec/` — 给机器与评审看的规格事实源**（结构化、可校验）
  - 每个运行时模块一份 spec（V20 自主运行时、LLM 客户端、工具注册表、Orchestrator Verifier 硬化等）
  - 先立规格 → `manifest validate` 校验一致性 → 再写代码，是本项目的「规格先行」工作流

> 一句话：想读懂怎么用 → 看 `docs/`；想确认某能力是否按要求实现、是否被诚实门禁覆盖 → 看 `openspec/`。

## Skills & 插件化 (Skills & Plugin Architecture)

- 内置技能：`assets/skills/` + 外部技能库（`SKILL_LIBRARY_PATHS`，249 唯一技能，索引器动态去重发现）。
- 组件扩展：自定义组件经 `BAIZE_COMPONENTS` 显式注册（`your_module:YourComponent`），无需改调用点；`component`/`modes` 组合内核配置驱动装配、fail-closed。
- 三技能库结构与功能层去重机制见 `docs/SKILL-LIBRARIES.md`。

## 生态接入路线 (V25 Ecosystem Roadmap)

V25 聚焦「生态接入 + 可见性」，**不破坏零依赖红线**：所有生态接入放 `baize/ext/`，核心调用链延迟 import，缺失 fail-closed。

- **P2 MCP 兼容**（stdio JSON-RPC，纯 stdlib）— 既能调用外部 MCP server 工具，也能暴露 baize skills 给 Claude Desktop / Cursor。
- **P3 模型供应商广度** — 核心已有 OpenAI/Anthropic/Ollama 适配器（纯 stdlib）；V25 补缺口并接非 OpenAI 兼容厂商。
- **P4 RAG / 向量后端** — 默认 TF-IDF 零依赖；可选 llama_index / chromadb 后端（规划中）。
- **P5 多智能体增强** — 在现有 `orchestrator` 上做薄配置层，复用 Verifier + `team_memory`。

详见 `docs/baize-agent-V25升级计划.md`，专家评审见 `docs/V25-专家评审.md`。

## 核心原则 (Core Principles)

1. **NO FAKE DONE** — manifest 的 phase 标记 done，其 evidence 文件必须物理存在；Verifier 独立核验，失败自动重试（`orchestrator.py` 强制执行）。
2. **调查先行** — 决策前先调查（见 `assets/skills/strategic/maozx-investigation`）。
3. **外科手术式变更** — 最小 diff、无关代码零改动（见 `assets/skills/karpathy_coding`）。
4. **技能不复制** — 外部技能库通过 `SKILL_LIBRARY_PATHS` 配置化引用，索引器动态发现。
5. **沙箱默认开启** — Agent 工具限制在 `BAIZE_WORKSPACE_DIR` 内，危险命令 deny-list fail-closed 拦截。
6. **会话即事实** — 每次运行产生 JSONL 转录，崩溃不丢状态，可审计可续跑。
7. **防御式设计可证明** — 混沌注入真实故障验证 Agent 不崩溃（`chaos.py`），而非声称。
8. **零运行时依赖** — 运行时纯标准库；工程化只靠 pytest / pytest-cov（仅测试期）。

## 状态与验证 (Status & Verification)

- 当前版本：**V23.0.0**（顶层文档、`baize.manifest.json` 与 `baize.__version__` 同步）
- 测试：**422 passed / 1 skipped / 0 failed**（全量 `pytest tests/`）
- 覆盖率：**UNKNOWN** — 当前未采集 `.coverage`，故不声称任何数字（NO FAKE DONE，不为 0 依赖项目编造覆盖率）
- 第三方运行时依赖：**0**
- V24 关键点：系统瘦身（删除死代码 mcp.py/context.py 并收敛 manifest 证据）+ 文件/文档/代码风格/文件夹统一化；全量门禁 `doctor` + `gate`(manifest PASS, quality 0.875) 通过。详见 `docs/VERIFICATION_V24.md`。
- V22 关键点：统一组件契约 + 组合内核（`component`/`modes`）、`BAIZE_COMPONENTS` 显式覆盖 fail-closed、插件目录自动发现防御性隔离、命名模式 = 组件集

## License

MIT
