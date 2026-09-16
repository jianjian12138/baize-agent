# AICoding 架构设计 · 资料摘要

> 本文档做一件事：**精读主理人转交的全部原始资料，逐份、逐章节做出摘要**——后面任何人拿到这份摘要，都能通过章节号快速定位回原始文件的对应位置。

> 上游输入：主理人转交的 Baize Agent V24.0.0 项目自身原始资料（`/f/TC/baize-agent-main` 下的 README / manifest / pyproject / baize 源码 / openspec / docs / tests / assets / examples / Dockerfile / CI / .env.example）。
> 产出者：`knowledge-ingest-engineer`（知识摄入工程师 - 闻资料），经 G1 校验与人工审核通过后交付。
> 任务上下文：用户诉求为「启动 AICoding 架构专家团，分析我们 agent，并给出升级计划」——本摘要为下游「升级计划」服务，在 §2 末按用户诉求专项萃取出现状能力 / 差异化护城河 / 已识别缺口 / 约束红线。

---

## 0. 元信息

```yaml
标题: Baize Agent V24.0.0 - 资料摘要 v0.1
版本: v0.1
状态: Draft（待 G1 结构检查 + 等价合规检查 + AskUserQuestion 人工审核）
创建日期: 2026-08-19
整理人: knowledge-ingest-engineer（闻资料）
审核人:
  - 齐构成（team-lead，G1 人工审核待执行）

原始资料清单:
  - README.md: 项目定位 / 对比表 / 架构图 / 目录 / V25 路线 / 核心原则 / 状态验证
  - baize.manifest.json: 流水线门禁与证据（phase 状态 + evidence 物理核验）
  - pyproject.toml: 版本 / 依赖（空）/ 工具配置
  - baize/ : 运行时 40 个纯 stdlib 模块（源码树）
  - openspec/ : 代表性规格子集（8 模块 spec + README）
  - docs/VERIFICATION_V24.md: V24 瘦身与统一化验收报告
  - docs/baize-agent-V25升级计划.md: V25 生态接入 + 可见性计划（完整版）
  - docs/V25-专家评审.md: P2-P5 三线专家评审
  - docs/COMPARISON-四引擎对比.md: 白泽 vs hermes/pi/deepseek-harness
  - docs/baize-agent-操作手册与功能清单.md: 操作手册 + 功能清单（V19，已陈旧）
  - docs/baize-设计思想溯源.md: 卡帕西准则 → 白盒诚实门禁思想溯源
  - docs/SKILL-LIBRARIES.md: 三技能库结构与功能层去重机制
  - docs/tutorials/ : 10 篇上手教程（抽样 01、08）
  - tests/ : 真实测试套件（422 passed / 1 skipped）
  - assets/skills/ : 三技能库 + 外部技能中心结构
  - examples/ : 可运行示例（logged_sandbox.py）
  - Dockerfile: 镜像定义
  - .github/workflows/ci.yml: 跨 OS × Python 3.10-3.13 CI
  - .env.example: 环境配置样例
  - benchmarks/COMPARISON.md: V19 版对标基准（已陈旧）
```

| 版本 | 日期 | 作者 | 变更内容 |
| --- | --- | --- | --- |
| v0.1 | 2026-08-19 | knowledge-ingest-engineer | 初稿：逐份精读 Baize Agent V24.0.0 项目原始资料，产出 G1 结构化摘要 |

---

## 1. 资料清单

> 列出全部原始资料，每份标注解析状态。解析失败或跳过的必须注明原因。

| 编号 | 文件名 | 类型 | 来源 | 解析状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| D1 | `README.md` | md | 项目根 | 已解析 | 项目主文档（V24.0.0） |
| D2 | `baize.manifest.json` | json | 项目根 | 已解析 | 流水线门禁与证据 |
| D3 | `pyproject.toml` | toml | 项目根 | 已解析 | 版本 / 依赖 / pytest 配置 |
| D4 | `baize/`（40 个 `.py` 模块） | src | 项目运行时 | 已解析 | 按 README §架构图层职责 + 抽样模块 docstring（llm.py/agent.py）+ openspec 行为规约归纳；未逐行读全部实现 |
| D5 | `openspec/`（README + 抽样 4 份 spec） | md | 规格中心 | 已解析 | 已读 README + baize-agent / baize-llm / baize-orchestrator / baize-tools 共 4 份 spec；doctor / manifest / memory / skill-index 4 份 spec 本轮未逐份读（见下方跳过说明） |
| D6 | `docs/VERIFICATION_V24.md` | md | 验收文档 | 已解析 | V24 瘦身与统一化验收 |
| D7 | `docs/baize-agent-V25升级计划.md` | md | 计划文档 | 已解析 | V25 生态接入 + 可见性（完整版） |
| D8 | `docs/V25-专家评审.md` | md | 评审文档 | 已解析 | P2-P5 三线专家评审 |
| D9 | `docs/COMPARISON-四引擎对比.md` | md | 对比文档 | 已解析 | 白泽 vs hermes/pi/deepseek-harness（数据采集于 V20） |
| D10 | `docs/baize-agent-操作手册与功能清单.md` | md | 操作手册 | 已解析 | 版本声明 V19.0.0，测试/覆盖率数字已陈旧（见 §3 X2） |
| D11 | `docs/baize-设计思想溯源.md` | md | 设计文档 | 已解析 | 卡帕西准则思想溯源 |
| D12 | `docs/SKILL-LIBRARIES.md` | md | 技能库文档 | 已解析 | 三技能库结构与去重 |
| D13 | `docs/tutorials/`（抽样 01、08） | md | 教程 | 已解析 | 10 篇中抽样 01（认识引擎）、08（写组件）；其余 8 篇未逐份读 |
| D14 | `tests/`（39 个 `.py` 测试文件） | src | 测试套件 | 已解析 | 422 passed / 1 skipped / 0 failed（junit tests=423） |
| D15 | `assets/skills/`（三技能库） | dir | 技能库 | 已解析 | 顶层 14 个技能集；skills/ 外部中心约 240 目录未全枚举 |
| D16 | `examples/logged_sandbox.py` | src | 示例 | 已解析 | 自定义组件最小可运行示例 |
| D17 | `Dockerfile` | dockerfile | 部署 | 已解析 | 镜像定义（LABEL 版本号陈旧，见 §3 X3） |
| D18 | `.github/workflows/ci.yml` | yaml | CI | 已解析 | 跨 OS × Python 3.10-3.13 |
| D19 | `.env.example` | env | 配置样例 | 已解析 | 环境配置样例（头部注释陈旧，见 §3 X3） |
| D20 | `benchmarks/COMPARISON.md` | md | 对标基准 | 已解析 | V19 版对标（69 测试 / 91% 覆盖率，已陈旧） |

**关联但本轮未逐份精读（非用户指定摄入清单，标注跳过原因，供下游按需取用）**

| 编号 | 文件名 | 类型 | 解析状态 | 原因 |
| --- | --- | --- | --- | --- |
| — | `AGENT.md` / `SKILL.md` / `START-HERE.md` | md | 跳过（非指定） | 用户指定摄入清单未含；属 README 所述「第一层规约」，下游 business/system 架构师可按需读取，不在 G1 摘要范围内 |
| — | `docs/VERIFICATION_V23.md` / `docs/baize-agent-V23升级路线图.md` | md | 跳过（历史版本） | 历史版本交付物，不与 V24 现行冲突，下游追溯用 |
| — | `docs/archive/*`（V18-V22 交付/验收/计划） | md | 跳过（历史归档） | 历史归档，README 已说明移入 archive 便于追溯但不干扰当前阅读 |
| — | `openspec/specs/baize-doctor`、`baize-manifest`、`baize-memory`、`baize-skill-index` 的 spec.md | md | 跳过（本轮未抽样） | D5 已抽样 4 份核心 spec（agent/llm/orchestrator/tools），其余 4 份为代表性子集内文档，下游可按需读取 |
| — | `docs/tutorials/02-07、09-10` 及 `tutorials/README.md` | md | 跳过（未抽样） | D13 已抽样 01、08 覆盖「总览」与「组件扩展」两端，其余 8 篇为同类上手教程 |

**类型枚举**：`md` / `json` / `toml` / `src` / `dir` / `dockerfile` / `yaml` / `env`（本项目原始资料均为代码/文档类，无 docx/pdf/pptx/xlsx 二进制格式）

---

## 2. 资料内容摘要

> 逐份文档按自身章节结构做摘要。每条摘要标注章节号（`D编号，§章节`），后面任何人想核实某个点，直接定位回原文对应位置即可。

### D1：README.md

> 项目主文档，定义 Baize Agent V24.0.0 的定位、差异化、架构、目录、V25 路线、核心原则与验证状态 — 来源：项目根

| 章节 | 内容摘要 |
| --- | --- |
| D1,§标题/定位 | V24.0.0；白盒工程化自主 Agent 运行时；**纯 Python 标准库、零第三方运行时依赖**；以 **NO FAKE DONE** 门禁（manifest 证据 + doctor/gate/pytest）保证「不假绿」。V24 完成系统瘦身与文件/文档/代码风格/文件夹统一化（D1, L1-11） |
| D1,§Why Baize（差异化） | 5 点差异化：①零第三方运行时依赖（stdlib，空气隔离/可审计/可嵌入）；②NO FAKE DONE 已验证（done 必须有物理证据 + Verifier 独立核验 + chaos 注入真实故障）；③插件与技能架构（component/modes 组合内核 + 3 技能库，配置驱动，fail-closed）；④自主 + 多智能体（反思规划/自循环/orchestrator Director→Executor→Verifier/team+team_memory）；⑤可服务化（baize serve 内建 REST，无额外网关）（D1, L15-22） |
| D1,§对比头部框架 | 维度对比表（V24.0.0）：baize 在「运行时第三方依赖=0 / 审计面=tiny(~468KB stdlib) / 验证门禁=yes(manifest+gate)」三项碾压；诚实标注落后项：可视化仅 Web dashboard（无拖拽）、RAG 仅 TF-IDF 词法（稠密后端 *planned*）、多智能体为 yes（orchestrator+team）、内建 HTTP serve=yes。明确不与 LangChain/CrewAI 拼生态广度，niche 为「零依赖 + 可验证」安全/审计/嵌入敏感场景（D1, L23-37） |
| D1,§Quick Start | 3 步 hero：①`python -m baize doctor`（环境门禁）②`python -m baize run "<目标>"` ③`python -m baize serve --port 8787`；完整 10 步折叠含 index build/team/rag/dash/bench/manifest/memory/pytest/组件扩展（D1, L41-98） |
| D1,§架构 | 双层 ASCII 架构图：**第一层 规约与技能**（AGENT.md/SKILL.md/assets/skills/外部技能库 249 唯一技能）；**第二层 baize 运行时（纯 stdlib）**分六子层——内核(llm/agent/tools/orchestrator/team_memory)、数据层(vector/rag/graph/bench)、交互层(ui/dashboard+serve)、组合内核(component/modes)、工程化(observability/logging_setup/chaos/plugin/config_schema)、校验与记忆(doctor/skill index/manifest/memory)（D1, L102-151） |
| D1,§目录结构 | baize/ 40+ 模块（纯 stdlib，含 V22 组合内核 component/modes）；tests/ 422 pytest 1 skip；examples/（含 logged_sandbox.py）；assets/skills/；install/；persistence/；openspec/；benchmarks/；docs/；ci.yml；Dockerfile（D1, L153-167） |
| D1,§文档导航 | `docs/` 给人看（叙事）；`openspec/` 给机器与评审看（结构化、可校验），先立规格→manifest validate→再写代码（D1, L169-181） |
| D1,§Skills&插件化 | 内置 assets/skills/ + 外部技能库（SKILL_LIBRARY_PATHS，249 唯一技能，索引器动态去重）；组件扩展经 BAIZE_COMPONENTS 显式注册（`module:Class`），无需改调用点；component/modes 配置驱动装配、fail-closed（D1, L183-187） |
| D1,§生态接入路线（V25） | V25 聚焦「生态接入 + 可见性」，**不破坏零依赖红线**：所有生态接入放 `baize/ext/`，核心调用链延迟 import，缺失 fail-closed。P2 MCP 兼容（stdio JSON-RPC 纯 stdlib，既能调外部 MCP server 也能暴露 baize skills 给 Claude Desktop/Cursor）；P3 模型供应商广度（核心已有 OpenAI/Anthropic/Ollama 适配器，V25 补缺口接非 OpenAI 兼容厂商）；P4 RAG/向量后端（默认 TF-IDF 零依赖，可选 llama_index/chromadb，规划中）；P5 多智能体增强（在 orchestrator 上做薄配置层，复用 Verifier+team_memory）（D1, L189-198） |
| D1,§核心原则 | 8 条：①NO FAKE DONE（done 须有物理 evidence，Verifier 独立核验，失败自动重试）；②调查先行；③外科手术式变更；④技能不复制（SKILL_LIBRARY_PATHS 配置化引用）；⑤沙箱默认开启（BAIZE_WORKSPACE_DIR 限制 + deny-list fail-closed）；⑥会话即事实（JSONL 转录，崩溃不丢、可续跑）；⑦防御式设计可证明（chaos 注入真实故障）；⑧零运行时依赖（仅测试期 pytest/pytest-cov）（D1, L200-209） |
| D1,§状态与验证 | 当前 V24.0.0（顶层文档/manifest/__version__ 同步）；测试 422 passed / 1 skipped / 0 failed；**覆盖率 UNKNOWN**（未采集 .coverage，不声称数字）；第三方运行时依赖 0；V24 关键点=系统瘦身（删 mcp.py/context.py 死代码 + 收敛 manifest 证据）+ 统一化，全量门禁 doctor + gate(manifest PASS, quality 0.875) 通过（D1, L211-218） |

### D2：baize.manifest.json

> 流水线门禁（NO FAKE DONE）的 phase 清单与物理证据 — 来源：项目根

| 章节 | 内容摘要 |
| --- | --- |
| D2,§元信息 | project=baize-agent，version=24.0.0；phases 数组为各版本能力交付记录（D2, L1-3） |
| D2,§phases（V68-V108） | 关键 phase：V68 Hooks 生命周期事件体系（done, evidence hooks.py/test_hooks.py）；**V69 MCP 客户端 = skipped**，备注「已于 V24 系统瘦身中移除（真孤儿、零接线、无运行时引用）」，evidence 为空（D2, L11-16）；V70 子 Agent 声明+隔离（done）；V71 诚实技能自进化 rubric+SkillRunner（done）；V72 Plan Mode+自治滑块（done）；**V73 多 Provider 模型广度 OpenAI/Anthropic/Ollama（done，evidence llm.py/test_multi_provider.py）**；V74 Automations 定时任务（done）；V75 会话分叉/压缩 UI（done）；V76 公开基准+本地 bench（done）；V77 上下文/长程管理增强（done，evidence 收敛至 agent.py）；V78 NO FAKE DONE 门禁产品化 cli gate/徽标/manifest 校验（done）；V79 prompt cache + token 效率（done） |
| D2,§phases（V47-V50 早期验收） | V47-V50 由 #68-#79 实质覆盖收口，均为 done（D2, L78-100） |
| D2,§phases（V95-V108 V22/V23） | V95 统一插件契约+组合内核（done）；V96 Agent Loop 抽成可替换策略（done）；V97 命名模式=插件集（done）；V98 沙箱/存储/UI 统一暴露为组件（done）；V99 组件发现/市场机制增强严格隔离（done）；V100 文档/规格升级+写组件教程（done）；V101 测试验证+诚实门禁收口（done）；V102 根基加固 F1-F5（done）；V103 V23.1 技能库治理去重+index v2+audit（done）；V104 V23.2 技能自创建 create_skill+user_skills（done）；V105 V23.3 索引审计 audit_index（done）；V106 V23.4 方案侦察 pre-flight recon（done）；V107 V23.5 阶段路由强化 Director clarifier+render_prd（done）；V108 V23.6 多维质量门禁五维+阈值（done）（D2, L102-221） |

### D3：pyproject.toml

> 构建/依赖/测试配置 — 来源：项目根

| 章节 | 内容摘要 |
| --- | --- |
| D3,§build-system | requires setuptools>=61.0，build-backend setuptools.build_meta（D3, L1-3） |
| D3,§project | name=baize-agent，version=24.0.0，description 强调 pure stdlib zero third-party dependencies，requires-python >=3.10，license MIT，keywords agent/autonomous-agent/llm/ai/multi-agent；classifiers 含 Development Status :: 4 - Beta、OS Independent、Microsoft :: Windows（D3, L5-25） |
| D3,§dependencies | **`dependencies = []`** —— 零第三方运行时依赖，注释明确「the runtime is Python standard library only」（D3, L26-27） |
| D3,§scripts/urls | `[project.scripts]` baize = "baize.cli:main"；Homepage/Repository 指向 GitHub jianjian12138/baize-agent（D3, L29-34） |
| D3,§tool.setuptools | packages.find include=["baize*"]（D3, L36-37） |
| D3,§tool.pytest.ini_options | testpaths=["tests"]；norecursedirs=["assets","examples","skills","install","benchmarks","docs",".github"] —— 使裸 pytest 只收集 tests/，避免误收集 skills/ 下含第三方依赖（yaml）的技能脚本导致 collection 中断（D3, L39-43） |

### D4：baize/ 运行时源码（40 个纯 stdlib 模块）

> 运行时模块树，按 README §架构图的六子层归纳职责；责任描述依据 README §架构图层职责 + 抽样模块 docstring（llm.py L1-14、agent.py L1-18）+ openspec 行为规约；未逐行读全部实现 — 来源：baize/

| 章节 | 内容摘要 |
| --- | --- |
| D4,§内核-llm | `llm.py`：模型无关 OpenAI 兼容 chat-completions 客户端（纯 stdlib）。设计借自 hermes（无厂商锁定）。V20 增：多模型 router（加权选择+跨模型 fallback）、SSE 流式输出、请求/令牌速率限制+有界退避。transport 可注入，脚本化 fake 可确定性驱动整条循环。导入 chaos 做 transport 包裹（D4, 依据 llm.py docstring + D1 §架构图 + D5 baize-llm spec） |
| D4,§内核-agent | `agent.py`：自主循环核心（V20）。V20 增：周期性自我反思检查点、死循环检测优雅中止、长程上下文压缩、plugin hooks、指标。设计综合 hermes（全自主循环/模型无关/自进化技能）+ pi（极简内核/原语/JSONL 会话/渐进披露）+ 白泽legacy（技能索引/manifest门禁/doctor/持久记忆作为一等上下文注入）。MAX_OBSERVATION_CHARS=8000，压缩后 400，保留最近 8 条（D4, 依据 agent.py docstring L1-18 + D5 baize-agent spec） |
| D4,§内核-tools | `tools.py`：9 原语工具 + `ToolRegistry` 进程级单例注册表（修复过「注册进丢弃注册表」bug）。文件工具限 BAIZE_WORKSPACE_DIR，命令 deny-list fail-closed。含 save_skill 自进化（D1 §架构图 + D5 baize-tools spec） |
| D4,§内核-orchestrator | `orchestrator.py`：Director→Executor→Verifier 三角色编排；Verifier 独立取证（不信任 Executor 自述，自行读文件/跑命令），fail 带 issues 重试（D1 §架构图 + D5 baize-orchestrator spec） |
| D4,§内核-team_memory | `team_memory.py`：协作记忆白板（跨角色共享上下文）（D1 §架构图） |
| D4,§数据层-vector | `vector.py`：TF-IDF 向量检索，embedding 接口预留。据 V25 专家评审，vector.py:133 已有 `get_backend()` + `TfidfIndex` + `EmbeddingBackend` 后端工厂（D1 §架构图 + D8 §P4） |
| D4,§数据层-rag | `rag.py`：技能+记忆统一 RAG 检索增强 + 技能评分。据评审 rag.py:23 直接 `from .vector import TfidfIndex` 不走工厂（D1 §架构图 + D8 §P4） |
| D4,§数据层-graph | `graph.py`：知识图谱三元组存储（D1 §架构图） |
| D4,§数据层-bench | `bench.py` / `bench_public.py`：确定性核心基准套件 / 公开基准（D1 §架构图 + D2 V76） |
| D4,§交互层-ui | `ui.py`：TUI 进度渲染（阶段/工具/反思/计划）（D1 §架构图） |
| D4,§交互层-dashboard+serve | `dashboard.py` + `serve.py`：Web 仪表盘 + 内建 REST 服务（`baize serve`）（D1 §架构图 + D1 §Why Baize⑤） |
| D4,§组合内核-component | `component.py`：统一组件契约 `Component` + `CompositionKernel`（9 类 Kind：model/tool/skill/session/sandbox/loop/scheduler/ui/storage；配置驱动装配，fail-closed；结构类型校验 Protocol；循环检测 fail-closed）（D1 §架构图 + D13 教程08 + D2 V95/V98） |
| D4,§组合内核-modes | `modes.py`：命名模式 = 组件集（coding/eval/autonomous/safe-review），显式 BAIZE_MODE 优先于标量自治滑块（D1 §架构图 + D2 V96/V97） |
| D4,§工程化-observability | `observability.py`：span + 指标 + Prometheus 导出（D1 §架构图 + D8 §3.4） |
| D4,§工程化-logging_setup | `logging_setup.py`：结构化 JSON 日志 + 脱敏（redact）（D1 §架构图 + agent.py 导入 redact） |
| D4,§工程化-chaos | `chaos.py`：故障注入韧性验证；V24 P1b 接线到 llm transport（默认禁用、零副作用、仅包裹默认 transport）（D1 §架构图 + D6 §P1b） |
| D4,§工程化-plugin | `plugin.py`：钩子体系（HookRegistry）+ 组件自动发现（baize/plugins/ + BAIZE_PLUGINS_DIR），防御性隔离，绝不默认可信（D1 §架构图 + D13 教程08「自动发现=低信任，记录日志+跳过」） |
| D4,§工程化-config_schema | `config_schema.py`：强类型配置校验（含 BAIZE_COMPONENTS 格式）。V24 P1c 接线 doctor(WARN 项)+cli 非 doctor 命令 fail-fast（return 2）（D1 §架构图 + D6 §P1c） |
| D4,§校验与记忆-doctor | `doctor.py`：环境门禁，真实探测 Python/.env/目录可写性/技能库路径/CLI 工具，真实退出码（D1 §架构图 + D5 baize-doctor spec 未抽样） |
| D4,§校验与记忆-skill_index | `skill_index.py`：技能索引与检索（3 来源去重）；V23.1 去重取最规范副本 + index v2 + audit 字段；V23.2 create_skill + user_skills；V23.3 audit_index（D1 §架构图 + D2 V103-V105 + D12） |
| D4,§校验与记忆-manifest | `manifest.py`：流水线门禁，evidence 文件物理核验（D1 §架构图 + D5 baize-manifest spec 未抽样） |
| D4,§校验与记忆-memory | `memory.py`：跨会话持久记忆 + 长程压缩（D1 §架构图 + D5 baize-memory spec 未抽样） |
| D4,§其他模块（未逐行） | `hooks.py`(V68 生命周期事件)、`subagent.py`(V70)、`skill_runner.py`(V71 诚实技能自进化)、`autonomy.py`(V72 Plan Mode+自治滑块，成本上限降级)、`automations.py`(V74 定时任务)、`sessions.py`(V75 分叉/压缩)、`prompt_cache.py`(V79)、`recon.py`(V106 方案侦察)、`agent_rules.py`、`config.py`、`gate.py`(V78 NO FAKE DONE 门禁 CLI)、`cli.py`(主入口)、`__main__.py`、`__init__.py`(__version__)、`sandbox.py`(deny-list fail-closed)（D2 phases 证据 + D1 §架构图） |

### D5：openspec/ 规格中心

> 代表性规格子集（不被运行时加载），规格先行工作流的事实源 — 来源：openspec/

| 章节 | 内容摘要 |
| --- | --- |
| D5,§README | 本目录是运行时**代表性规格子集**，仅覆盖 specs/ 下 8 个已落地核心模块（agent/doctor/llm/manifest/memory/orchestrator/skill-index/tools），**非全量模块规格库**；各 spec 是评审对齐事实源；真正强制约束由 `gate.py`+`manifest.py`（NO FAKE DONE 证据核验）执行，**本目录不被运行时加载**。工作流：Propose→Review(manifest validate)→Apply→Archive（D5, openspec/README.md L1-37） |
| D5,§baize-agent spec | 自主 Agent 循环（V19 内核，V22 扩展）：思考→工具→观察→迭代；pi 式 append-only JSONL 持久化、崩溃不丢、按 id 续跑；启动注入技能索引+持久记忆（环境感知）。V22 插件化：每核心单元描述为统一 Component 契约，CompositionKernel 从 BAIZE_COMPONENTS 装配；BAIZE_MODE 命名模式优先于标量滑块。接口：Session/Agent/Agent.run/build_system_prompt/CompositionKernel/get_runtime。行为规约 1-9（final/text tool_calls、max_steps 强制停、未知工具不崩、JSONL 即写即落、续跑不重复 system、注入记忆、system 含 NO FAKE DONE、LLM 失败 stopped_reason=error 不伪造）（D5, specs/baize-agent/spec.md） |
| D5,§baize-llm spec | 模型无关 OpenAI 兼容 chat-completions 客户端（纯 stdlib），任何兼容端点可接入，transport 可注入。接口 LLMClient(cfg, transport)/configured/chat。行为规约 1-6：未配置必须抛 LLMError（不静默降级/伪造）；URL={base}/chat/completions；tools 原样放入；失败按 MAX_RETRIES 退避重试；缺 choices[0].message 抛 LLMError；注入 transport 后逻辑真实执行（D5, specs/baize-llm/spec.md） |
| D5,§baize-orchestrator spec | 多 Agent 编排：Director 规划→Executor 执行→Verifier 独立核验；NO FAKE DONE 从口号变可执行门禁。接口 Orchestrator(cfg,client,registry,on_event,max_retries_per_task=1)/plan/run。行为规约 1-6：Director 输出无法解析 JSON 降级单任务；每子任务派生独立 Executor+独立 Verifier 会话；Verifier 输出 verdict/evidence/issues，fail 带 issues 重试（上限 max_retries）；重试耗尽仍 fail 整体 success=False；全 pass 写持久记忆；每会话独立持久化可回溯。边界：Verifier 非法 JSON 按 fail（保守）（D5, specs/baize-orchestrator/spec.md） |
| D5,§baize-tools spec | 工具注册表与沙箱（原语而非固化功能，pi 哲学），JSON schema 注册，运行时可扩展；文件限工作区，shell 经 deny-list（fail-closed）。接口 ToolRegistry.register/schemas/execute、default_registry（9 内置）、command_allowed。行为规约 1-8：未注册工具返 ERROR 观察值不崩；异常转 ERROR 观察值；文件越界 PermissionError（转 ERROR）；bash deny-list 命中拒绝；bash 超时 60s、输出截 8000；save_skill 写 user_skills/<safe-name>/SKILL.md 并即时重建索引（V23.2）；read_file 截断/list_dir 最多 200；V23.4/5/6 CLI：recon/clarify/gate（quality 五维评分，低于阈值整体 FAIL）（D5, specs/baize-tools/spec.md） |

### D6：docs/VERIFICATION_V24.md

> V24 系统瘦身与统一化验收报告（验证日期 2026-08-18）— 来源：docs/

| 章节 | 内容摘要 |
| --- | --- |
| D6,§1 范围 | V24 **不做新功能**，只做「砍死重、消除割裂、统一规范」：P0 安全止血→P1 瘦身+增强→P2 版本号统一→P3 文档统一→P4 代码风格→P5 命名/文件夹统一→P6 测试瘦身去重。每阶段配 baize gate + 全量 pytest（D6, L10-16） |
| D6,§2 变更-P0/P1 | P0 安全止血：.gitignore 已含 .env/persistence/projects/*.egg-info/.pytest_cache/*.coverage（已完成）。P1 瘦身：删真孤儿 mcp.py/context.py/secrets.py + 对应 tests；接线 chaos.py 到 llm transport（默认禁用、零副作用）；config_schema.py 接线 doctor(WARN)+cli fail-fast(return 2)；重写 test_f5_gap.py（D6, L22-34） |
| D6,§2 变更-P2~P6 | P2 版本号统一 24.0.0（三处一致）；P3 文档统一（openspec README 标注 8 spec、修复 V20 断链、V22 过期文件移 archive）；P4 代码风格（print→logging_setup.get_logger，保留 CLI/ui/doctor 用户面向 stdout 的 print；pyflakes 清理；保留 # noqa 因 fail-closed 故意）；P5 命名/文件夹统一（三技能库保持现状、skills/ 不批量改名、去重 250 唯一/丢52/30组）；P6 测试瘦身（真重复已删，补充覆盖测试保留）（D6, L36-57） |
| D6,§3 动态测试 | 权威 junit：tests=423, failures=0, errors=0, skipped=1 → **422 passed / 1 skipped**。pyproject testpaths+norecursedirs 使裸 pytest 只收 tests/（D6, L61-65） |
| D6,§4 CLI门禁 | `baize doctor` → PASSED（9×PASS + 3×WARN：git/go 未装、os sandbox logical-only）；`baize gate` → manifest PASS + quality 0.875（threshold 0.7）PASS，其中 runnable 1.0 / coverage_clarity 0.5 / composition 1.0 / locatability 1.0 / maintainability 1.0；coverage UNKNOWN（无 .coverage，设计内）；overall UNKNOWN（设计内）（D6, L69-92） |
| D6,§4 修复记录 | P1a 删 mcp.py 后 V69 证据缺失致 gate manifest FAIL；修正：V69 置 skipped（清空 evidence），V77 context 证据收敛至 agent.py；修复后 manifest PASS/quality 0.875 恢复绿（D6, L94-97） |
| D6,§5 已知环境说明 | doctor WARN 为可选能力不影响核心；gate coverage UNKNOWN 为设计内诚实上报；skills/ 约 240 目录命名混用为上游原始形态（D6, L101-105） |
| D6,§6-7 总结与验收 | V24 三项门禁全绿，正式验收 ACCEPTED（2026-08-18）：pytest 422/1skip/0fail、doctor PASSED、gate manifest PASS+quality 0.875；版本 24.0.0 三处一致；修复 1 个真实回归（manifest 证据与删除不同步）闭环（D6, L109-129） |

### D7：docs/baize-agent-V25升级计划.md

> V25 生态接入 + 可见性计划（完整版，计划日期 2026-08-19，目标版本维持 24.0.0）— 来源：docs/

| 章节 | 内容摘要 |
| --- | --- |
| D7,§驱动背景 | GitHub 调研：jianjian12138/baize-agent 当前 stargazers=1、forks=0、**topics=[]**、repo 描述仍写「V19」。技术资产（零依赖+NO FAKE DONE+插件化+skills 三库）稀缺但不可见，连 GitHub 发现机制都没进（D7, L5） |
| D7,§设计红线 | 贯穿全程：①运行时零第三方依赖（核心 baize/ 永远纯 stdlib；生态放 baize/ext/，核心调用链不得默认 import 外部库，缺失 fail-closed 提示）；②不假绿（覆盖率要么真跑给实数，要么如实标 UNKNOWN）；③外科手术式变更（最小 diff）（D7, L6-9） |
| D7,§执行顺序 | P0(元数据,零代码) → P1(README重写) → P6(文档/基准) → P7(验收)；P2(MCP)/P3(供应商)/P4(向量)/P5(多智能体) 互相独立可并行，均依赖 P1 接口约定；P2-P5 按 ROI 排期（建议 P2 优先）（D7, L14-26） |
| D7,§P0 可见性止血 | 零代码当天可做：topics 设为 agent/ai-agents/llm-agent/autonomous-agents/python/zero-dependency；description 改「Baize Agent V24.0.0 · zero-dependency autonomous agent runtime (NO FAKE DONE verified)」；开 Discussions；记录 before/after（D7, L30-54） |
| D7,§P1 README重写 | ★必修。修正硬伤：当前 README 第 151 行「448 passed / 87.6%」→ 实际 **422 passed / 1 skipped / 0 failed**，覆盖率如实标 UNKNOWN 或真跑给实数；补 V24 说明+链接。新结构：EN hero + Why Baize + 对比表 + 架构 + Quick Start(3步) + 安装/配置 + Skills&插件化 + 生态接入 + 文档导航 + 核心原则 + 状态与验证（D7, L58-95） |
| D7,§P2 MCP兼容 | baize/ext/mcp/：transport.py（stdio JSON-RPC，纯 subprocess+json+管道）、client.py（MCPClient 拉起外部 server、包装为 baize 原语工具）、server.py（暴露 baize skills 给外部）、__init__.py（lazy import，缺失 fail-closed）。集成点：tools.py 增 register_mcp_client(spec) 仅此处 import baize.ext.mcp；cli.py 增 mcp 子命令。门禁：test_mcp_mock.py（进程内 mock，纯 stdlib）、「核心不依赖 ext」烟雾测试、gate 绿（D7, L99-118） |
| D7,§P3 模型供应商 | baize/ext/providers/：registry.py + openai.py(迁此保留默认)/anthropic.py/deepseek.py/ollama.py/openrouter.py；统一抽象 complete(messages,**kw)->(text,usage)。llm.py 仅在解析 BAIZE_MODEL_ROUTER 时延迟 import ext，默认 OpenAI 兼容路径仍纯 stdlib。门禁：test_providers.py（D7, L122-138） |
| D7,§P4 RAG/向量后端 | baize/ext/vector_backends/：base.py(VectorBackend add/query)、tfidf_backend.py(包装核心 vector.py 作零依赖默认)、llama_index_backend.py/chromadb_backend.py(可选 import，缺失 skip)。rag.py 经 BAIZE_VECTOR_BACKEND 选择，默认 tfidf，仅非默认时延迟 import ext。门禁：test_vector_backends.py（D7, L142-158） |
| D7,§P5 多智能体 | modes.py 增 team 模式或新增 baize/team.py：Role 契约(name/goal/backstory/tools)、Crew 装配、顺序/层级交接；复用 component.Kind 作角色单元；交接经 orchestrator Verifier 硬化 fail-closed；cli team 扩展支持角色清单 YAML/JSON。门禁：test_team.py（D7, L162-175） |
| D7,§P6/P7 收尾 | P6：benchmarks/COMPARISON.md 加 baize 行（依赖数/启动时间/审计面/验证门禁/体积468KB）、英文速览、examples 增 mcp_minimal/team_minimal/rag_backend、链接校验。P7：复跑门禁（doctor/gate quality≥0.8/pytest 422/1skip/0fail）、可见性核对清单、写 VERIFICATION_V25.md（D7, L179-215） |
| D7,§风险登记/排期 | 风险：生态破坏零依赖（全走 ext+延迟import+烟雾测试）、覆盖率假绿（不声称或真跑）、重依赖拖慢 CI（ext 测试独立 skip、norecursedirs 已排除）、重写内核偏离范围（V25=接入+可见性，大版本留 V26）、文档/示例腐烂（链接校验+dry-run）。排期：P0+P1 立刻最高 ROI；P2 次之；P3/P4/P5 按需（D7, L218-235） |

### D8：docs/V25-专家评审.md

> V25 计划 P2-P5 三线并行专家评审（评审日期 2026-08-19）— 来源：docs/

| 章节 | 内容摘要 |
| --- | --- |
| D8,§0 三线共识 | 计划核心方向对，但 **P2-P5 严重低估主干已有能力**。表：P2 MCP=真缺口保留；P3 供应商=大半已存在（llm.py 已有 openai/anthropic/ollama 适配器 + BAIZE_MODEL_ROUTER）；P4 向量=双实现腐烂风险（vector.py 已有 get_backend()+TfidfIndex+EmbeddingBackend，rag.py 直连 TfidfIndex）；P5 多智能体=勿重写（orchestrator 已有 Director→Executor→Verifier+TeamMemory，baize team 已存在）。优先级收敛：**P2 > P5 > P3(降级补丁) > P4(推迟 V26)**（D8, L10-23） |
| D8,§统一收口 | 计划漏了既有 plugin.py/component.py 扩展总线。若 P2-P5 各自 import baize.ext.X，会把扩展机制碎成三条平行山头。V25 必须做的一处基础设施改动 = 把生态接入统一收口到 `plugin.discover` + `CompositionKernel.add_component`，而非各阶段自起炉灶（D8, L21） |
| D8,§P2 MCP | approve-with-changes（ROI 最高）。修正：①协议正确性——MCP 是带 Content-Length 头部的 JSON-RPC 2.0 分帧，非纯换行 JSON；initialize 需 protocolVersion 协商+capabilities 交换+初始化后 notifications/initialized，否则真实 server 静默挂起；须对真实参考 server 联调；②集成点错位——register_mcp_client 应把 MCP 工具包装进现有 ToolRegistry（复用 register/execute），而非另立工具表；③门禁假绿——「import baize 后断言 baize.ext 未被自动导入」恒真（__init__ 只设 __version__），真不变量应是静态 grep：baize/*.py 无顶层 import baize.ext（D8, L27-35） |
| D8,§P3 供应商 | approve-with-changes（建议降级为补丁）。修正：①勿搬核心适配器——llm.py:102-201 已内建 anthropic/ollama 适配器（纯 stdlib），BAIZE_MODEL_ROUTER 已在核心解析；把 openai.py「迁 ext 并保留默认」与「核心仅解析 router 时延迟导入」自相矛盾，破零依赖红线；修正：既有 stdlib 适配器留 llm.py 不动，ext 只放非 OpenAI 兼容厂商（gemini/bedrock 薄适配），llm.py 仅 _route_from_config 内延迟 import ext。②补真实缺口而非凑数量：Anthropic 流式未实装降级单次 yield 且 max_tokens 硬编码 4096 易截断；DeepSeek reasoner 的 reasoning_content 未捕获；provider_capabilities 恒返 stream/tools=True 形同虚设（NO FAKE DONE 视角假绿，应如实报 {"stream":False,"tools":True}）。③P3 降级为「补丁+非兼容厂商薄适配」（D8, L39-48） |
| D8,§P4 向量 | approve-with-changes（建议推迟 V26）。修正：①双实现腐烂——vector.py:133 已有 get_backend()+TfidfIndex+EmbeddingBackend 工厂，P4 另起 VectorBackend+tfidf_backend 包装=两层平行抽象，rag.py:23 不走工厂；修正：扩展既有 get_backend() 让其懒探测 ext/vector_backends，勿新造接口，rag.py 改走 get_backend()。②稠密后端被低估——EmbeddingBackend 只有 embed()，无向量索引/ANN；默认 TF-IDF 是真词法检索（非假 RAG）但语义/同义/跨语种弱，README 勿吹语义检索，诚实标 lexical retrieval。③测试崩溃风险——llama_index/chromadb 后端测试须用 pytest.importorskip 守卫，否则缺依赖整批 collection 崩溃威胁 422 基线（D8, L52-58） |
| D8,§P5 多智能体 | approve-with-changes。修正：①概念错位——「复用 component.Kind 作为角色单元」错误（Kind 是封闭枚举粗粒度组件类，Role 是 prompt+工具集的 agent 实例，混用污染契约）；②勿重写——baize team 已存在、orchestrator 已含 TeamMemory 黑板交接+LLM verifier（默认 fail-closed）；新增 baize/team.py 只做薄配置层，把 roles.yaml（role→system_prompt+tools）映射为对现有 Orchestrator 的 Agent(role=...) 调用，复用 Verifier+TeamMemory，挂现有 team 子命令 --roles，角色缺失 fail-closed（D8, L62-69） |
| D8,§跨阶段红线修正 | ①统一扩展总线（全部经 plugin.discover+CompositionKernel.add_component，禁各阶段自起 import baize.ext.X）；②门禁去假绿（静态 grep 门禁 + provider_capabilities 如实上报）；③守住 422 基线（pyproject norecursedirs 补 ext + ext 测试 importorskip 守卫）；④零依赖默认路径（默认启用能力不得触碰 ext，ext 仅按需懒加载）（D8, L73-78） |
| D8,§修订后范围 | 必做进 V25：P0 元数据、P1 README 修正、P2 MCP（修正分帧+握手+接入 ToolRegistry+静态 grep 门禁）、P5 多智能体（薄配置层复用 orchestrator）。降级进 V25：P3 改「补核心适配器缺口+仅加非 OpenAI 兼容厂商薄适配」。推迟 V26：P4 稠密向量后端、P3 的 gemini/bedrock 重后端、ext 大规模扩张。P6/P7 随范围调整聚焦 MCP+team（D8, L82-88） |

### D9：docs/COMPARISON-四引擎对比.md

> 白泽 vs hermes-agent vs pi-agent vs deepseek-harness（编写日期 2026-08-14，白泽数据来自本地 V20 交付物）— 来源：docs/

| 章节 | 内容摘要 |
| --- | --- |
| D9,§0 TL;DR | 白泽引擎 V20：白盒工程化研发操作系统（方法论技能包+真实 Agent 运行时双层），零依赖、强门禁；Python 3.10-3.13 纯 stdlib；**0 运行时依赖（仅测试期 pytest）**；V20.0.0，144 测试，个人/内部仓库。一句话定位：白泽 = 吸收 hermes 自主循环 + pi 极简内核后的「白盒工程化」运行时（D9, L1-18） |
| D9,§1 关系图谱 | hermes/pi 是白泽设计上游（基因同源、理念继承）；deepseek-harness 是同赛道竞品（技术路线相反：白泽 Python stdlib 零依赖白盒，dsh TypeScript+Cordis 插件内核）。白泽不可替代性=纯 stdlib 零依赖白盒 + 可证明诚实门禁（D9, L22-38） |
| D9,§2 能力总矩阵 | 多维度：白泽 运行形态=规约包+自带运行时（双模式）；LLM 循环=自带；模型中立=OpenAI 兼容任意端点；工具=9 原语+SDK 扩展（单例注册表）；工具沙箱=工作区限制+deny-list fail-closed；会话=append-only JSONL --resume；记忆=持久+长程压缩+RAG；多Agent=Director→Executor→Verifier（独立核验）；技能=249 唯一技能+渐进披露+save_skill 自进化；独立核验门禁=NO FAKE DONE；环境门禁=doctor；数据层=vector(TF-IDF)/rag/graph 内置；交互=TUI+Web+REST；工程化=144 pytest+80% 覆盖+CI+Docker+chaos；第三方依赖=0（D9, L42-61） |
| D9,§3 分维度 | 3.1 架构哲学：白泽双层架构第一性（规约+技能 / 纯 stdlib 运行时 26 模块），哲学白盒+可证明；3.2 模型：白泽单文件 llm.py 封装 OpenAI 兼容端点带速率限制/退避，未配置 fail-closed(exit 2)；3.3 工具：9 原语+SDK 运行时扩展，注册表进程级单例，默认工作区限制+deny-list fail-closed；3.4 会话：JSONL+长程压缩+RAG；3.5 多Agent：显式三角色 Verifier 独立核验硬化；3.6 扩展：SKILL_LIBRARY_PATHS 配置引用+动态发现+save_skill 自进化；3.7 安全：白泽 fail-closed 优先（沙箱默认开+deny-list+未配置退出+Verifier），dsh OS 级沙箱最硬核，pi 坦诚无内置权限；3.8 工程化：白泽 144 pytest（脚本化 transport 真实驱动）+80% 覆盖+CI 跨 OS×3.10-3.13+Docker 非 root+chaos 真实验证；3.9 部署：CLI+TUI+Web+REST，也可仅作规约包；3.10 成熟度：白泽个人/内部 V20.0.0，144 测试背书，许可未公开声明（D9, L65-144） |
| D9,§4 白泽护城河 | 6 点：①纯 stdlib 零运行时依赖（唯一）；②可证明诚实（NO FAKE DONE，manifest 物理核验+Verifier）；③双层架构（规约+运行时）；④fail-closed 安全观；⑤防御式设计可证明（chaos 真实验证）；⑥数据层内置（vector/rag/graph 原生，竞品需外部扩展）（D9, L148-155） |
| D9,§5-6 选型/来源 | 选型建议表（零依赖/可审计/可移植/诚实门禁选白泽）；数据来源：白泽以 V20 交付物为权威，hermes/pi/dsh 来自公开网络（Star 等波动大，仅方向性参考）（D9, L159-178） |

### D10：docs/baize-agent-操作手册与功能清单.md

> 操作手册 + 功能清单（文档头声明版本 **V19.0.0**，交付文件）— 来源：docs/

| 章节 | 内容摘要 |
| --- | --- |
| D10,§1 操作手册 | 1.1 安装：纯 stdlib 零依赖（仅测试期 pytest/coverage）；1.2 配置 .env（SKILL_LIBRARY_PATHS / BAIZE_MODEL_* / BAIZE_AGENT_MAX_STEPS=24 / BAIZE_WORKSPACE_DIR / BAIZE_ALLOW_OUTSIDE_WORKSPACE=0 / BAIZE_SESSIONS_DIR）；1.3 命令速查（doctor/index/build/search/manifest validate/memory/run/team/sessions 及退出码）；1.4 run 单 Agent；1.5 team Director→Executor→Verifier；1.6 sessions/--resume；1.7 index 249 技能 3 来源；1.8 manifest validate 证据物理核验；1.9 memory；1.10 9 原语工具；1.11 安全沙箱+deny-list+未配置 fail-closed(exit 2)；1.12 排错（D10, L21-159） |
| D10,§2 功能清单 | A-I 能力域全覆盖：运行形态双模式、LLM 自主循环、多 Agent 编排、工具系统、会话与记忆、技能生态（249 唯一技能）、工程门禁、测试可维护性（**69 个 pytest、91% 覆盖率、阈值 85%**）、方法论内置（毛选+卡帕西）（D10, L162-205） |
| D10,§3 对比 hermes/pi | V19 能力矩阵 + 从两者学到并升级的设计表（D10, L209-244） |
| D10,§4 白泽特有功能 | 9 点差异化：独立核验门禁(Verifier)、流水线证据物理核验(manifest)、环境门禁(doctor)、技能自进化即时生效、双模式运行、大规模技能生态+渐进披露、持久记忆、零依赖+确定性测试、方法论内置（D10, L248-268） |
| D10,§附录 | 验证数据 V19：doctor PASSED、69 passed、91% 覆盖率（阈值 85%）、249 skills/3 sources、manifest VALID、run/team 未配置 exit=2（D10, L272-309） |

> ⚠️ 注意：本文件版本声明 V19.0.0、69 测试、91% 覆盖率，与现行 V24（422 passed / 1 skipped / coverage UNKNOWN）严重错配；属 V25 计划所指「描述陈旧」类缺口（详见 §3 X2/X3）。

### D11：docs/baize-设计思想溯源.md

> 从卡帕西准则到白盒诚实门禁的思想溯源（编写日期 2026-08-14）— 来源：docs/

| 章节 | 内容摘要 |
| --- | --- |
| D11,§1 初始思想 | 白泽立项之初把卡帕西 Agent 开发哲学提炼成可执行技能 karpathy_coding（澄清本位/奥卡姆剃刀/Git 纯净化/验证锚点「Precision is the final sovereignty over hallucination」）；映射到 README 核心原则（调查先行←澄清本位；外科手术式变更←直接引用；NO FAKE DONE←验证锚点放大）；思想→架构选择：奥卡姆→纯 stdlib 零依赖，外科手术式变更→双层架构，精确对抗幻觉→Verifier+manifest+fail-closed（D11, L11-40） |
| D11,§2 卡帕西公开思想 | 归纳：软件 1.0/2.0/3.0（提示词是最热新编程语言）；锯齿智能/Ghosts vs Animals（性能极不均匀、会幻觉、未澄清即编码、缺长任务耐力、benchmaxxing）；部分自主+人类监督（钢铁侠战衣、autonomy slider、keep AI on the leash、trust but verify）；Software 3.0 工程五支柱（Prompt-oriented/Guard-railed/Tight generate-verify cycles/Agent-friendly infra/Obsability for cognition）；上下文工程+DAG 编排+垂直 GUI+自治滑块；本地 agent（秘密管理/权限/审计）；Vibe Coding（须测试把关）；Benchmaxxing 警示；个人 LLM 编码工作流四层（L1 Tab 75%/L2 15%/L3 10%/L4）（D11, L44-89） |
| D11,§3 对 Baize 提炼 | 思想→落地映射表：锯齿智能+Guard-railed→✅Verifier/manifest，🔜不可游戏化基准；部分自主+leash→✅fail-closed/沙箱，🔜OS 沙箱/Plan mode；Prompt-oriented→✅AGENT.md/SKILL.md 版本化；Observability→✅observability；Agent-friendly→✅第一层规约包；Benchmaxxing→🔜真实端到端+证据；本地 agent→✅零依赖 CLI，🔜OS 沙箱+秘密管理；奥卡姆→✅纯 stdlib，🔒升级须保持核心不污染；Vibe Coding→✅save_skill+Verifier；自治滑块→✅orchestrator(TUI/Web GUI)（D11, L93-107） |
| D11,§4 思想闭环 | 白泽 V21 不是背离，而是把卡帕西 2025 系统化原则从哲学变工程能力：锯齿→guard-rail 深化（不可游戏化基准/OS 沙箱）；部分自主→leash（Plan mode/沙箱）；Observability→可审计；奥卡姆→零依赖不可破（MCP/Hooks 必须可选适配层默认不启用）（D11, L110-119） |
| D11,§5 来源 | 项目内 karpathy_coding/SKILL.md/README/V20 交付文档；卡帕西公开 YC 2025-06/LLM Year in Review 2025/个人工作流 2025-08（D11, L123-127） |

### D12：docs/SKILL-LIBRARIES.md

> 三技能库结构与功能层去重机制说明 — 来源：docs/

| 章节 | 内容摘要 |
| --- | --- |
| D12,§1 三技能库 | 三个相互独立技能库：①内置方法论技能 `assets/skills/`（白泽自带，毛选战略/卡帕西编码/picasso-dev 系列等，计数 **23**）；②`picasso-dev-skill/`（独立工程，含 .claude-plugin/vendor/install/profiles，计数 **7**，只是恰好也是技能来源）；③外部技能中心 `skills/`（大型外部引入约 240 目录，计数 **220**，经 SKILL_LIBRARY_PATHS 配置引用不复制）。`picasso-dev-skill/` 保留原始工程结构，白泽侧不重构（D12, L5-13） |
| D12,§2 去重机制(V23.1) | skill_index._dedup：按归一化名称（忽略大小写与 -/_）聚跨库重复组；每组保留最规范副本（优先带真实 frontmatter 描述），丢弃其余。核验结果：**唯一技能 250 个，去重丢弃 52 个副本，跨库重复组 30 个**。磁盘命名变体（api-tester/apitester 等）是预期冗余非缺陷（D12, L15-23） |
| D12,§3 统一化约定(V24) | 三库角色与磁盘命名保持现状（skills/ 保留上游原始命名含 kebab/snake 混用，白泽不批量改名）；白泽自有 assets/skills/ 维持既有；新增技能写 user_skills/（BAIZE_USER_SKILLS_DIR，V23.2 起）与内置收集库解耦；破坏性去重须先确认内容完全一致并用 baize skill audit 评估、保留 git 历史（D12, L25-29） |
| D12,§4 命令 | baize skill audit（去重组/缺失 frontmatter）、baize skill search、baize index build（D12, L31-37） |

### D13：docs/tutorials/（抽样 01、08）

> 10 篇上手教程抽样 2 篇（01 总览、08 组件扩展）— 来源：docs/tutorials/

| 章节 | 内容摘要 |
| --- | --- |
| D13,§01 认识白泽引擎 | 面向小白：一句话定义「白盒工程化研发操作系统」，当前 V24.0.0；解决三痛点（不可信→NO FAKE DONE、不可控→沙箱+deny-list fail-closed、不可复现→会话即事实 JSONL）；双层架构（第一层规约与技能含 249 唯一技能 / 第二层 baize 运行时）；来源 hermes（自主循环/模型无关/自进化技能）+ pi（极简内核/原语/JSONL/渐进披露）；最关键特性零第三方依赖；能/不能做（明确**没有真实向量库后端，当前 TF-IDF 关键词级，生产级语义检索在路线图未落地**、无多模态微调、需自备 OpenAI 兼容端点）；教程路线图 10 篇（D13, 01-认识白泽引擎.md） |
| D13,§08 写一个baize组件 | V22 插件化架构（baize.component 组合内核，零第三方依赖）。组件=元数据+工厂：KIND（9 类封闭枚举 model/tool/skill/session/sandbox/loop/scheduler/ui/storage，新增 kind 须改代码不为第三方开放）+ build(cfg) 工厂 + 可选 provides/requires（拓扑依赖 fail-closed）；build 返回 Any 惰性解析消循环导入。两套隔离语义：**显式覆盖**（BAIZE_COMPONENTS 指定，高信任，整体 fail-closed 启动阻断 exit≠0，绝不静默降级）/ **自动发现**（plugin.py 扫 baize/plugins/+BAIZE_PLUGINS_DIR，低信任，记录日志+跳过，绝不默认可信）。最小示例 logged_sandbox.py（声明 KIND→签名合协议→build 工厂）；BAIZE_COMPONENTS="module:Class" 注册；协议速查表；gate 自检（真实装配+9 类 Protocol 校验+4 模式 bundle）；陷阱（循环导入/忘 KIND/协议形状/插件目录不默认可信）（D13, 08-写一个baize组件.md） |

### D14：tests/ 测试套件

> 真实测试套件（39 个 .py 测试文件，不含 __pycache__）— 来源：tests/

| 章节 | 内容摘要 |
| --- | --- |
| D14,§结构与数量 | 39 个测试文件（含 conftest.py）；权威 junit：tests=423, failures=0, errors=0, skipped=1 → **422 passed / 1 skipped / 0 failed**（D14, 依据 D6 §3 + D1 §状态与验证） |
| D14,§覆盖模块 | 命名映射：test_agent/test_orchestrator/test_tools/test_llm/test_multi_provider/test_component/test_modes/test_plugin_discovery/test_gate/test_manifest/test_skill_index/test_memory/test_sandbox/test_sandbox_coverage/test_sessions/test_bench/test_subagent/test_automations/test_autonomy/test_hooks/test_skill_runner/test_recon/test_clarify/test_prompt_cache/test_observability/test_ui/test_cli/test_config/test_config_schema/test_agent_rules/test_engineering/test_llm_chaos/test_serve/test_serve_coverage/test_orchestrator_coverage/test_f5_gap 等（D14, 目录列举） |
| D14,§测试哲学 | 脚本化 transport（可注入 fake HTTP transport）真实驱动整条 Agent 循环，非 MagicMock 空转；补充覆盖测试（*_coverage.py）命名一致保留；test_f5_gap 重写去 context 依赖（D6 §3/P6 + D1 §核心原则⑦） |

### D15：assets/skills/ 技能库结构

> 三技能库目录结构 — 来源：assets/skills/

| 章节 | 内容摘要 |
| --- | --- |
| D15,§内置方法论技能(assets/skills) | 顶层 14 个条目：atomic_decomposition、karpathy_coding、memory_autodream、methods（含 analytical-requirement-mastery/sovereign-testing-mindset/traceability-sovereignty 3 篇 md）、picasso-dev、picasso-dev-config、picasso-dev-maintainer、picasso-dev-methods、picasso-dev-task、picasso-dev-ui、strategic、universal_harvest、verification_expert、web_harness_e2e（每技能含 SKILL.md）。计数 23（D12 §1 + 目录列举） |
| D15,§外部技能中心(skills/) | 大型外部引入集合约 240 目录（计数 220），经 SKILL_LIBRARY_PATHS 配置引用不复制到项目内；命名含 kebab/snake 混用为上游原始形态（D12 §1 + D6 §5） |
| D15,§picasso-dev-skill/ | 独立工程（含 .claude-plugin/vendor/install/profiles），计数 7，作为技能来源之一被索引（D12 §1） |

### D16：examples/ 可运行示例

> 最小可运行示例 — 来源：examples/

| 章节 | 内容摘要 |
| --- | --- |
| D16,§logged_sandbox.py | 自定义组件最小可运行示例（演示）「声明 KIND=Kind.SANDBOX → 方法签名符合 SandboxProto → 提供 build 工厂」三步，不修改白泽内核调用点；被 tutorials/08 与 manifest V100 引用（D16, 目录 + D13 §08 + D2 V100） |

### D17：Dockerfile

> 镜像定义 — 来源：项目根

| 章节 | 内容摘要 |
| --- | --- |
| D17,§镜像 | FROM python:3.12-slim；注释「Baize Engine V20 - zero runtime dependencies means a tiny, fast image. No pip install step」；COPY baize/ + assets/ + AGENT.md/SKILL.md/README.md；**LABEL version="20.0.0"**（与现行 V24.0.0 不一致，陈旧，见 §3 X3）；ENV BAIZE_PERSISTENCE_DIR=/data、BAIZE_SERVE_HOST/PORT；非 root 用户 baize、/data 可写、VOLUME /data、EXPOSE 8787；HEALTHCHECK /health；ENTRYPOINT python -m baize；CMD serve（D17, L1-39） |

### D18：.github/workflows/ci.yml

> CI 配置 — 来源：项目根

| 章节 | 内容摘要 |
| --- | --- |
| D18,§矩阵 | on push/PR/master；matrix os=ubuntu/windows/macos × python=3.10/3.11/3.12/3.13；fail-fast=false；concurrency 取消进行中（D18, L1-23） |
| D18,§test job | 步骤：checkout → setup-python → Install dev tooling（pip install pytest pytest-cov）→ **Verify zero runtime dependencies**（ast 扫描 baize/ 全部 import，发现非 stdlib 且非 baize 即 exit 1）→ Doctor（python -m baize doctor）→ Tests with coverage（pytest tests/ -q --cov=baize --cov-report=xml）→ Benchmarks（baize bench）→ **Coverage threshold**（解析 coverage.xml line-rate×100，默认阈值 80，env TEST_COVERAGE_THRESHOLD 可覆盖，低于即 exit 1）（D18, L25-85） |
| D18,§install-smoke/docker | install-smoke（bootstrap.py + --version + doctor + index build）；docker（build + --version + doctor 冒烟）（D18, L87-120） |

> ⚠️ 注意：CI 用 `--cov=baize` 强制执行 80% 行覆盖率门槛，与 README/D6 声称「覆盖率 UNKNOWN（未采集 .coverage，不声称数字）」存在口径张力，且阈值默认 80 与 .env.example 的 85 不一致（详见 §3 X4/X5）。

### D19：.env.example

> 环境配置样例 — 来源：项目根

| 章节 | 内容摘要 |
| --- | --- |
| D19,§头部 | 注释「Baize Engine V19 - environment configuration」（与现行 V24 不一致，陈旧，见 §3 X3）（D19, L1） |
| D19,§核心目录 | BAIZE_PERSISTENCE_DIR/PROJECTS_DIR/ASSETS_DIR/INDEX_FILE 默认仓库内相对路径（D19, L5-12） |
| D19,§技能库 | SKILL_LIBRARY_PATHS=./assets/skills,./picasso-dev-skill,./skills（doctor 对缺失路径 fail）（D19, L14-22） |
| D19,§运行时 | BAIZE_MODEL_BASE_URL/NAME/API_KEY/LLM_MAX_RETRIES；BAIZE_AGENT_MAX_STEPS=24；BAIZE_WORKSPACE_DIR；BAIZE_ALLOW_OUTSIDE_WORKSPACE=0；BAIZE_SESSIONS_DIR（D19, L24-45） |
| D19,§质量门禁/示例 | **TEST_COVERAGE_THRESHOLD=85**（与 ci.yml 默认 80 不一致，见 §3 X5）；示例项目 API_KEY/CORS（fail-closed 若未设）；Secrets 须只在 .env（gitignored）（D19, L47-68） |

### D20：benchmarks/COMPARISON.md

> V19 版对标基准（白泽 V19 vs hermes vs pi）— 来源：benchmarks/

| 章节 | 内容摘要 |
| --- | --- |
| D20,§定位/矩阵 | V19 定位：对 hermes/pi 的功能整合与升级（学自主循环/模型无关/自进化技能 + pi 极简内核/原语/JSONL），叠加白泽独有工程门禁与技能生态；非套壳纯 stdlib 自研，69 真实测试+规格背书。能力矩阵（14 维度）与「从两者学到并升级的设计」表，数据均为 V19（69 测试、91% 覆盖率、249 技能）（D20, 头部 + §一/§二） |
| D20,§基准设计 | 三、可执行基准测试设计（BTS-001~005 基准任务，需相同模型/硬件回填真实对标）（D20, §三） |

> ⚠️ 注意：本文件为 V19 基线，69 测试/91% 覆盖率与现行 V24 不一致，属历史基准（见 §3 X2）。

---

### 跨文档萃取（用户诉求专项：为「升级计划」服务）

> 以下为按主理人用户诉求「分析我们 agent 并给出升级计划」专项萃取，跨 D1-D20 综合。交叉文档合成仅在本题明确要求下执行；逐份客观摘要见上，冲突并列保留见 §3。

**① 现状能力清单（V24.0.0 已落地）**
- 运行时：纯 Python 标准库、零第三方运行时依赖（D1/D3/D6/D18 一致）；体积 ~468KB、审计面极小（D1/D9）。
- 自主循环：反思规划 + 自循环 + 长程记忆压缩 + 死循环检测（D4 agent / D1 架构图 / D5 baize-agent）。
- LLM 客户端：模型无关 OpenAI 兼容端点，多模型 router+fallback、SSE 流式、速率限制+退避、未配置 fail-closed(exit 2)、transport 可注入确定性测试（D4 llm / D5 baize-llm / D9 §3.2）。据 D2 V73 + D8 §0，**核心已有 OpenAI/Anthropic/Ollama 适配器与 BAIZE_MODEL_ROUTER**（非 V25 计划假设的「全新」）。
- 工具系统：9 原语工具 + ToolRegistry 进程级单例 + SDK 运行时扩展；工作区沙箱 + 命令 deny-list fail-closed；save_skill 自进化即时重建索引（D4 tools / D5 baize-tools / D10 §1.10）。
- 多智能体：orchestrator Director→Executor→Verifier（Verifier 独立取证、fail 带 issues 重试）；baize team 已存在；team_memory 协作白板（D4 orchestrator/team_memory / D5 baize-orchestrator / D1）。
- 数据层（内置）：vector(TF-IDF 词法，embedding 接口预留，已有 get_backend()+TfidfIndex+EmbeddingBackend)、rag（技能+记忆统一 RAG+技能评分）、graph（三元组）、bench（确定性基准）（D4 数据层 / D8 §P4）。
- 交互层：TUI 进度 + Web 仪表盘 + 内建 REST serve（D4 交互层 / D1 Why Baize⑤）。
- 组合内核：component（9 类 Kind 统一契约 + CompositionKernel 配置驱动装配 fail-closed）+ modes（命名模式=coding/eval/autonomous/safe-review，显式优先于滑块）（D4 组合内核 / D13 教程08 / D2 V95-V97）。
- 工程化：observability(span+指标+Prometheus)、logging_setup(结构化 JSON+脱敏)、chaos(故障注入真实验证)、plugin(HookRegistry+自动发现防御隔离)、config_schema(强类型校验，BAIZE_COMPONENTS 格式 fail-fast)（D4 工程化 / D8 §3.7）。
- 校验与记忆：doctor(环境门禁真实退出码)、manifest(NO FAKE DONE 证据物理核验)、skill_index(3 源去重，D12 计 250 唯一/丢52/30组)、memory(跨会话持久+长程压缩)（D4 校验与记忆 / D5 / D6）。
- 技能生态：三技能库（assets/skills 23 + picasso-dev-skill 7 + skills/ 约220），渐进披露按需加载（D12 / D1）。
- 可服务化与部署：baize serve REST、Docker 非 root+健康检查、CI 跨 OS×Python3.10-3.13（D1 / D17 / D18）。
- 质量门禁：NO FAKE DONE（manifest+gate+doctor+pytest），gate quality 五维（runnable/coverage_clarity/composition/locatability/maintainability），V24 gate 实测 quality 0.875（threshold 0.7）PASS（D1 / D2 V78 / D6 §4）。
- 测试：422 passed / 1 skipped / 0 failed（D1/D6/D14）。

**② 差异化与护城河（来自 D1 Why Baize / D9 §4 / D10 §4 / D11）**
- 唯一纯 stdlib 零运行时依赖的 Agent 运行时（hermes/pi/dsh 均需 Node/native/pip），带来可移植/可审计/无供应链攻击面（D9 §4① / D1 §对比）。
- 可证明的诚实（NO FAKE DONE）：manifest phase done 须有物理 evidence + Verifier 独立核验 + chaos 真实验证，竞品均无（D9 §4② / D1 §核心原则①⑦）。
- 双层架构（规约+技能 / 运行时）：既可自主运行，也可被 Claude Code/Codex/WorkBuddy 作规约包加载（D9 §4③ / D1 §架构）。
- fail-closed 安全观：沙箱默认开、deny-list、未配置退出、Verifier 独立核验（D9 §4④ / D1）。
- 防御式设计可证明：chaos 注入真实故障验证不崩（D9 §4⑤ / D1）。
- 数据层内置：vector/rag/graph 原生提供，竞品需外部扩展（D9 §4⑥）。
- 思想根源清晰：卡帕西「精确对抗幻觉」→ 可证明工程机制（D11）。

**③ 已识别差距 / 缺口（含 README 已声明 V25 路线 + 历史可见性短板，来自 D1 §V25 / D7 / D8 / D9 §数据来源 / D10）**
- **可见性 / GitHub 元数据短板（已确认事实，D7 §驱动背景）**：stargazers=1、forks=0、`topics=[]`、repo 描述仍写「V19」——技术资产不可见，未进 GitHub 发现流。
- **文档 / 版本号陈旧（D7 P1 / D10 / D17 / D19 / D20）**：操作手册仍 V19.0.0（69 测试/91% 覆盖）、Dockerfile LABEL 20.0.0、.env.example 头 V19、benchmarks/COMPARISON.md V19、README 旧版有误数「448 passed/87.6%」（实际 422/1skip、coverage UNKNOWN）；COMPARISON-四引擎对比采 V20 数据（144/80%）。
- **生态接入缺口（README V25 路线 + D7/D8）**：
  - P2 MCP 兼容 = **真缺口**（V24 瘦身已删 mcp.py，V69 skipped），ROI 最高（D2 V69 / D7 P2 / D8 P2）。
  - P3 模型供应商 = 大半已存在，缺口为「非 OpenAI 兼容厂商薄适配 + 核心适配器真实短板」：Anthropic 流式未实装且 max_tokens 硬编码 4096 易截断、DeepSeek reasoner reasoning_content 未捕获、provider_capabilities 恒返 stream/tools=True（NO FAKE DONE 视角假绿）（D8 §P3）。
  - P4 RAG/向量后端 = 默认 TF-IDF 词法可用，**稠密语义后端缺失**（llama_index/chromadb 规划中）；EmbeddingBackend 仅 embed() 无向量索引/ANN；README 须诚实标 lexical retrieval 勿吹语义（D1 §V25 / D8 §P4 / D13 §01）。
  - P5 多智能体增强 = 主干已具备，缺口为「薄配置层 role→system_prompt+tools 映射 + 命名 team 模式」，勿重写（D8 §P5）。
- **测试覆盖诚实口径缺口**：coverage 维度 UNKNOWN（无 .coverage），但 CI 却强制执行 80% 行覆盖率门槛（口径张力，D6/D18/D19，详见 §3 X4/X5）。
- **协议正确性风险（MCP）**：真实 MCP 为 Content-Length 分帧 JSON-RPC 2.0 + initialize 握手，计划初版「管道+换行 JSON」易漏分帧与握手导致真实 server 静默挂起（D8 §P2）。
- **扩展总线碎片化风险**：若 P2-P5 各自 import baize.ext.X 会把 plugin/component 扩展机制碎成平行山头，须统一收口（D8 §统一收口）。

**④ 约束红线（下游升级计划不可突破，来自 D1 §核心原则 / D3 / D6 / D7 §设计红线 / D8 §跨阶段红线）**
- **红线 A — 运行时零第三方依赖**：核心 `baize/` 永远纯 stdlib；所有生态接入放 `baize/ext/`，核心调用链不得默认 import 任何外部库，缺失时 fail-closed 提示（D1 §V25 / D3 dependencies=[] / D7 红线① / D8 红线④）。CI 已用 ast 扫描强制校验（D18 Verify zero runtime dependencies）。
- **红线 B — NO FAKE DONE 门禁**：phase 标记 done 必须有物理存在的 evidence；Verifier 独立核验；不声称覆盖率（要么真跑 coverage run 给实数，要么如实标 UNKNOWN）；provider_capabilities 须如实上报不得恒返 True（D1 §核心原则① / D6 / D7 红线② / D8 红线②）。
- **红线 C — baize/ext/ fail-closed**：ext 模块默认不启用、核心不触碰；仅在不改变默认行为前提下按需懒加载；ext 测试须 importorskip 守卫避免整批 collection 崩溃威胁 422 基线；pyproject norecursedirs 须补 ext（D7 P2-P4 / D8 红线③④）。
- **红线 D — 外科手术式变更 + 显式优先**：最小 diff、无关代码零改动；显式 BAIZE_MODE/BAIZE_COMPONENTS 优先于标量滑块；破坏性去重须保留 git 历史并经 skill audit（D1 §核心原则③ / D7 红线③ / D12 §3）。
- **红线 E — fail-closed 安全观贯穿**：沙箱默认开、deny-list、未配置模型 exit 2、Verifier 保守判定、插件自动发现绝不默认可信（D1 §核心原则⑤⑦ / D9 §3.7 / D13 教程08）。

---

## 3. 冲突记录

> 不同资料对同一事实描述矛盾时，**并列保留两个版本**，不做裁决。

| 编号 | 冲突主题 | 版本 A | 出处 A | 版本 B | 出处 B | 差异说明 |
| --- | --- | --- | --- | --- | --- | --- |
| X1 | 唯一技能数量 | **249** 唯一技能 | D1 §Skills&插件化/§生态接入路线（L109/L185）、D9 §2（249）、D10 §1.7/§2.1F/§4.8/附录A（249）、D13 §01（249） | **250** 唯一技能 | D12 §2（「唯一技能 250 个，去重丢弃 52，跨库重复组 30」）、D6 §P5（「当前 250 唯一技能 / 丢弃 52 副本 / 30 跨库重复组」） | 249 vs 250 数值不一致。可能口径不同（V23.1 去重计 250 为较新核验；README/操作手册/COMPARISON/教程沿用 249 旧数）。待下游确认以哪个为权威计数 |
| X2 | 测试数 / 覆盖率（不同版本快照并存） | **422 passed / 1 skipped / 0 failed；覆盖率 UNKNOWN（设计内）** | D1 §状态与验证、D6 §3/§4/§7（V24 现行） | **69 passed / 91% 覆盖率（阈值 85%）** | D10 §2.1H/附录A、D20（V19）；**144 pytest / 80% 覆盖** | D9 §2/§3.8（V20 数据） | 非同一时间快照的版本错配：V19(69/91%)→V20(144/80%)→V24(422/UNKNOWN)。D10/D20 为历史文档未随 V24 更新，属 V25 计划所指「描述陈旧」类缺口，不与 V24 现行冲突但会误导读者 |
| X3 | 版本号陈旧（文档/镜像声明 vs 现行） | 现行 **V24.0.0**（顶层文档/manifest/pyproject/__version__ 三处一致） | D1、D2、D3、D6 | Dockerfile LABEL `version="20.0.0"`；`.env.example` 头「V19」；操作手册头「V19.0.0」；benchmarks/COMPARISON.md「V19」；COMPARISON-四引擎对比采 V20 数据 | D17 L7、D19 L1、D10 L3、D20、D9 | 镜像/配置样例/部分文档头部版本号未随 V24 统一化更新，与现行 V24.0.0 不一致，属可见性/描述陈旧缺口（D7 P1 已列入必修） |
| X4 | 覆盖率口径（UNKNOWN vs CI 强制门槛） | 覆盖率 **UNKNOWN**（未生成 .coverage，不声称任何数字，NO FAKE DONE 不为 0 依赖项目编造覆盖率） | D1 §状态与验证（L215）、D6 §4/§5（coverage UNKNOWN 设计内） | CI 用 `pytest --cov=baize` 并强制 **80% 行覆盖率门槛**（低于 exit 1）；gate.py 的 coverage 维度也因无 .coverage 标 UNKNOWN | D18 §test job（Coverage threshold 默认 80）、D6 §4（gate coverage UNKNOWN） | 口径张力：本地/README 声称 line coverage UNKNOWN（无 .coverage），但 CI 实际生成 coverage.xml 并强制 80% 行覆盖率；gate.py 的「coverage」维度与 CI 的「行覆盖率」是不同口径（gate 用 coverage_clarity=0.5 五维之一）。下游需确认「覆盖率」究竟指 gate 五维之 coverage_clarity 还是 CI 行覆盖率，避免门禁语义混淆 |
| X5 | 覆盖率 / 质量门禁阈值不一致 | CI 默认阈值 **80**（TEST_COVERAGE_THRESHOLD 默认 80） | D18 §Coverage threshold（env 默认 80） | `.env.example` 写 **TEST_COVERAGE_THRESHOLD=85**；VERIFICATION_V24 记 gate quality 阈值 **0.7**（quality 0.875 PASS）；tutorials/08 提 gate「覆盖率门槛 85%」 | D19 L50、D6 §4（threshold 0.7）、D13 §08（门槛 85%） | 三处阈值不一致：CI 默认 80、.env.example 85、gate quality 阈值 0.7（注意 0.7 是 quality 五维综合阈值，非行覆盖率）。需下游澄清各阈值语义与适用层级 |
| X6 | V25 P3 计划假设 vs 源码实际 | 计划假设 P3 为「**新建 providers 模块**」（openai.py 迁 ext 并保留默认、核心仅解析 router 时延迟导入） | D7 §P3（模型供应商广度，新建 baize/ext/providers/） | 源码实际：`llm.py` **已有 openai/anthropic/ollama 适配器（纯 stdlib）+ BAIZE_MODEL_ROUTER 已在核心解析**；计划「迁 ext 并保留默认」与「核心仅解析 router 时延迟导入」自相矛盾（破零依赖红线） | D8 §0（P3 大半已存在）、D8 §P3（修正：既有适配器留 llm.py 不动）、D2 V73（多 Provider 已 done） | 计划低估主干既有能力（评审已并列记录）。非事实矛盾而是「计划假设 vs 源码实际」不一致，评审结论为 P3 降级为补丁、勿搬核心适配器 |
| X7 | V25 P4 计划假设 vs 源码实际（双实现腐烂） | 计划假设 P4 新建 `VectorBackend(add/query)` + `tfidf_backend` 包装 | D7 §P4（baize/ext/vector_backends/ 新接口） | 源码实际：`vector.py` 已有 `get_backend()` + `TfidfIndex` + `EmbeddingBackend` 后端工厂；`rag.py` 直连 `TfidfIndex` 不走工厂；另起平行抽象=两层抽象腐烂 | D8 §0（P4 双实现腐烂）、D8 §P4（修正：扩展既有 get_backend() 懒探测 ext，rag.py 改走 get_backend()） | 同 X6 性质：计划低估主干既有能力，评审建议 P4 推迟 V26 并扩展既有工厂而非新造接口 |

---

## 4. 硬指标清单

| 章节 | 硬指标 | 状态 |
| --- | --- | --- |
| 模板 | 覆盖模板全部一级标题（0/1/2/3/4/附录A/附录B） | ✅ 已覆盖 |
| §1 | 每份资料有解析状态，失败/跳过注明原因 | ✅ 已覆盖（D1-D20 标注「已解析」；关联未读项（AGENT.md/SKILL.md/START-HERE.md/archive/VERIFICATION_V23/未抽样 4 spec/未抽样 8 教程）单独标注「跳过」并注明原因） |
| §2 | 每份文档按章节逐条摘要，每条标注了 `D编号，§章节` | ✅ 已覆盖（D1-D20 各文档均按自身章节结构建表，行内标注 D编号,§章节） |
| §3 | 冲突信息并列保留，不做裁决 | ✅ 已覆盖（X1-X7 均并列两版+出处+差异说明，未裁决） |
| 全文 | 无残留模板占位符（尖括号占位 / 填写示例前缀 / 待填日期 / 待补标志） | ✅ 无残留（日期用真实值 2026-08-19/2026-08-18；无示例前缀；无待补标志） |
| §2 专项 | 用户诉求萃取齐全（现状能力 / 差异化护城河 / 已识别缺口 / 约束红线） | ✅ 已齐全（「跨文档萃取」块 ①②③④ 全覆盖） |
| §2 | 事实可追溯到原文件位置（D编号,§章节 + 关键行号/段落） | ✅ 已覆盖（摘要均标注 D编号,§章节，关键处附行号如 D1 L109、D6 §4、D8 §P2） |
| §4 | 硬指标逐条核验并明示状态 | ✅ 本条已逐条核验 |

---

## 附录 A：生成流程

### 流程总览

| 步骤 | 动作 | 落入章节 |
| --- | --- | --- |
| Step0 | 读取模板（skills/.../templates/material_digest.md）+ 主理人 Phase 1 任务（G1  Owner/输出路径/用户诉求/资料清单） | — |
| Step1 | 盘点资料清单，标注解析状态（D1-D20 + 关联跳过项） | §1 |
| Step2 | 逐份打开资料，按自身章节结构逐条摘要（D1 README → D20 benchmarks） | §2 |
| Step3 | 交叉比对不同资料，发现并记录矛盾（X1-X7） | §3 |
| Step4 | 按用户诉求专项萃取现状能力/差异化/缺口/红线 | §2（跨文档萃取块） |
| Step5 | 逐项核验硬指标 | §4 |

```mermaid
flowchart LR
    S0[读取模板与任务] --> S1[盘点资料清单]
    S1 --> S2[逐份精读逐章节摘要]
    S2 --> S3[交叉比对记录冲突]
    S3 --> S4[用户诉求专项萃取]
    S4 --> S5[硬指标自检]
```

### 整理原则

1. **逐份精读，不跨文档归并**：§2 逐份摘要按文档自身章节结构组织（D1-D20 各自成节，行内 D编号,§章节）；仅「跨文档萃取（用户诉求专项）」块按主理人明确要求做跨文档综合，与客观摘要分离。
2. **出处即章节号**：每条摘要标注 `D编号，§章节`，直接映射回原文位置（关键处附行号/段落）。
3. **冲突保留**：矛盾信息并列保留两个版本（X1-X7），不擅自裁决。
4. **事实驱动**：以原始资料事实为准；推断类仅在「跨文档萃取」块内基于多源综合并显式标注（如 X1 计数口径推测、X4 门禁语义提示），未添加无据主观结论。
5. **占位符清零**：定稿前全文无尖括号占位 / 填写示例前缀 / 待填日期 / 待补标志残留。

---

## 附录 B：解析 Skill

- `md`：项目文档 / 规格 / 计划 / 评审 / 教程 / README / manifest 说明（本项目主要格式）
- `json`：流水线门禁 manifest（baize.manifest.json，phase 状态 + evidence 物理核验）
- `toml`：构建与依赖配置（pyproject.toml）
- `src` / `dir`：纯 Python stdlib 运行时与技能库目录（baize/、tests/、assets/skills/、examples/）
- `dockerfile` / `yaml` / `env`：部署与 CI 配置（Dockerfile、ci.yml、.env.example）

> 说明：本项目原始资料均为代码/文档类（md/json/toml/src/dockerfile/yaml/env），**无 docx/pdf/pptx/xlsx 二进制格式**，故未启用对应二进制解析 Skill；原则仍一致——逐份精读、章节标注、冲突并列。
