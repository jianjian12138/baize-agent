# Baize Agent V25 升级计划 — 生态接入 + 可见性（完整版）

- **计划日期**：2026-08-19
- **目标版本**：维持 `23.0.0`（V25 为「接入 + 可见性」维护里程碑；若 P2–P4 规模过大再评估跃迁 `24.0.0`）
- **驱动背景**：GitHub 调研显示 `jianjian12138/baize-agent` 当前 `stargazers=1`、`forks=0`、`topics=[]`、repo 描述仍写「V19」。技术资产（零依赖 + NO FAKE DONE + 插件化 + skills 三库）稀缺但不可见，连 GitHub 发现机制都没进。
- **设计红线（贯穿全程）**：
  1. **运行时零第三方依赖**：核心 `baize/` 永远纯 stdlib；所有生态接入放 `baize/ext/`，核心调用链**不得默认 import** 任何外部库，缺失时 fail-closed 提示。
  2. **不假绿**：覆盖率要么真跑 `coverage run -m pytest` 给实数，要么如实标 UNKNOWN。
  3. **外科手术式变更**：最小 diff、无关代码零改动。
- **门禁沿用**：NO FAKE DONE + `baize doctor` / `baize gate` / 全量 pytest；每阶段独立门禁，未过不标 done。

---

## 执行顺序与依赖

```
P0(元数据,零代码) ─┐
                   ├─► P1(README重写) ─► P6(文档/基准) ─► P7(验收)
P2(MCP兼容) ───────┤
P3(供应商广度) ────┼─ 互相独立，可并行；均依赖 P1 确立的接口约定
P4(向量后端) ──────┤
P5(多智能体) ──────┘
```
- **必须串行先行**：P0 → P1（可见性的两个最高杠杆，零/低代码）。
- **P2–P5 为接入层**，彼此独立，按 ROI 排期（建议 P2 优先）。
- **P6/P7 收尾**。

---

## P0 · 可见性止血（GitHub 元数据，零代码，当天可做）

**目标**：把「被发现」的开关打开，让 baize 进入 GitHub 的 topic 发现流与搜索。

**具体任务**
1. 仓库 `topics` 设为：`agent`, `ai-agents`, `llm-agent`, `autonomous-agents`, `python`, `zero-dependency`（可选追加 `llm`, `rag`, `multi-agent`）。
2. 仓库 `description` 改为：
   `Baize Agent V23.0.0 · zero-dependency autonomous agent runtime (NO FAKE DONE verified)`
3. `About` 区补 `Homepage`（指向仓库或未来文档站）、相关社交链接。
4. 开启 `Discussions`（当前 `has_discussions=false`）作为社区入口；`Issues` 已开。
5. 记录 before/after（topics 空→有、description V19→V23、star 1→）。

**如何应用**
- 方式 A（Web UI）：仓库 Settings → General 改 description / About；Topics 在 About 区 `+`。
- 方式 B（`gh`，需登录）：
  ```bash
  gh repo edit jianjian12138/baize-agent \
    --description "Baize Agent V23.0.0 · zero-dependency autonomous agent runtime (NO FAKE DONE verified)" \
    --add-topic agent --add-topic ai-agents --add-topic llm-agent \
    --add-topic autonomous-agents --add-topic python --add-topic zero-dependency
  gh repo edit jianjian12138/baize-agent --enable-discussions
  ```

**门禁**：无代码门禁（纯元数据）。
**验收**：`topics` 非空且含 `agent` 类；description 显示 V23.0.0；Discussions 开启。

---

## P1 · README 重写（中英双语 + 卖点前置 + 修正失实数）★必修

**目标**：把首屏变成「访客 10 秒懂、国际可读、不假绿」的门面。

**必须修正的硬伤（当前 README 第 151 行）**
- `448 passed / 87.6%` → 实际 **`422 passed / 1 skipped / 0 failed`**，覆盖率如实标 `UNKNOWN`（无 `.coverage` 数据）或真跑后给实数。
- 完全未提及 V24（瘦身/统一化）→ 补 `docs/VERIFICATION_V24.md` 链接与一句话说明。

**新 README 结构（建议）**
```
# Baize Agent — zero-dependency autonomous agent runtime   [EN hero]
> 一句话定位 + 3 步 Quick Start + badges(tests/license/python)

## Why Baize（差异化，前置）
- Zero third-party runtime deps · NO FAKE DONE verified · Plugin & skills architecture
## 与头部框架对比（新增强表，涨 star 杠杆）
## 架构（保留现有 ASCII 图）
## Quick Start（3 步 hero + 完整命令折叠）
## 安装 / 配置
## Skills & 插件化（链接 SKILL-LIBRARIES.md）
## 生态接入（V25 路线：MCP / 多供应商 / 向量后端，链接 P2–P4）
## 文档导航（补 V24）
## 核心原则（NO FAKE DONE 等 8 条）
## 状态与验证（422 passed / 1 skipped，覆盖率诚实）
## License (MIT)
--- 中文详述（定位/架构/快速开始 全文）---
```

**具体任务**
1. 修正版本段测试数（448→422/1 skip）与覆盖率表述。
2. 补 V24 说明 + `VERIFICATION_V24.md` 链接（文档导航段）。
3. 加英文 hero（标题、定位、3 步 Quick Start、`![tests]`/`![license]`/`![python]` shields 静态 badge）。
4. 加「与头部框架对比」表，维度：`运行时依赖数 / 审计面 / 验证门禁 / 可视化 / RAG / 多智能体`（baize 在依赖/审计/验证三项碾压，其余如实标「规划中/可选」）。
5. 收紧 Quick Start：hero 只留 `doctor → run → serve` 3 步，完整 10 步折叠。
6. 保留中文详述，确保中英关键信息一致。

**门禁**：`doctor` / `gate` / `pytest` 仍绿；复核所有文档链接无断链（`docs/VERIFICATION_V24.md`、`SKILL-LIBRARIES.md`、`tutorials/` 等）。
**验收**：README 中英双语、含对比表、失实数已修正、badges 正常、链接全通。

---

## P2 · 生态接入 · MCP 兼容（可选装，不污染核心）

**目标**：用最小代价接入最大工具生态——baize 既能**调用**外部 MCP server 的工具，也能**暴露**自身 skills 给 Claude Desktop / Cursor 等。

**模块布局（全部在 `baize/ext/mcp/`）**
- `transport.py`：基于 stdlib（`subprocess` + `json` + 管道）实现 **stdio JSON-RPC**（MCP 的 initialize / tools/list / tools/call 最小子集）。核心 `baize/` 不 import 它。
- `client.py`：`MCPClient` 拉起外部 server 进程、列工具、调用，把结果包装成 baize 原语工具。
- `server.py`：`BaizeMCPServer` 把 baize skills / 原语工具暴露为 MCP tools（stdio）。
- `__init__.py`：lazy import 守卫，未安装外部 server 时 fail-closed 提示。

**核心集成点**
- `baize/tools.py` 增加 `register_mcp_client(spec)`：仅在此处 `import baize.ext.mcp`（延迟导入），核心其他路径零触碰。
- `baize/cli.py` 增加 `mcp` 子命令：`mcp serve`（暴露 baize）、`mcp list <url>`（探测外部 server 工具）。

**门禁**
- 新增 `tests/test_mcp_mock.py`：用纯 stdlib 起一个**进程内 mock MCP server**（管道 + JSON-RPC）验证 client 往返；不依赖任何第三方。
- 验证「核心不依赖 ext」：`python -c "import baize"` 后断言 `baize.ext` 未被自动导入（grep/import 烟雾测试）。
- `gate` 绿。

**验收**：`baize mcp list <mock>` 能列出工具并调用；核心 import 不触发 ext；pytest 全绿。

---

## P3 · 生态接入 · 模型供应商广度

**目标**：在保留 OpenAI 兼容客户端（stdlib http）为内核的前提下，预置主流供应商，降低接入摩擦。

**模块布局（`baize/ext/providers/`）**
- `registry.py`：provider 注册表；`baize/llm.py` 的 `BAIZE_MODEL_ROUTER` 改为查此表。
- `openai.py`（核心基类，已有 stdlib 实现，迁此并保留默认）、`anthropic.py`（messages API 适配到统一消息接口）、`deepseek.py`（OpenAI 兼容）、`ollama.py`（本地）、可选 `openrouter.py`。
- 统一抽象：`complete(messages, **kw) -> (text, usage)`，各适配器映射到该接口。

**核心集成点**
- `baize/llm.py` 仅在解析 `BAIZE_MODEL_ROUTER` 时延迟 import `baize.ext.providers`；默认 OpenAI 兼容路径仍纯 stdlib。

**门禁**
- `tests/test_providers.py`：router 解析、provider 选择、降级、错误注入（沿用 `llm.py` 既有 fake-client 模式）。
- `gate` 绿。

**验收**：`BAIZE_MODEL_ROUTER` 可切到 ≥3 个供应商；pytest 全绿；核心无新增默认依赖。

---

## P4 · 生态接入 · RAG / 向量可选后端

**目标**：保留现有 `vector`(TF-IDF)/`rag`/`graph`（已是 stdlib），允许按需接入 llama_index / chromadb 等强力后端，核心不受影响。

**模块布局（`baize/ext/vector_backends/`）**
- `base.py`：`VectorBackend` 接口（`add` / `query`）。
- `tfidf_backend.py`：包装核心 `vector.py` 作为**零依赖默认后端**。
- `llama_index_backend.py`、`chromadb_backend.py`：可选 import，缺失时 skip/提示。

**核心集成点**
- `baize/rag.py` 经配置（如 `BAIZE_VECTOR_BACKEND`）选择后端，默认 tfidf；仅在选非默认时延迟 import ext。

**门禁**
- `tests/test_vector_backends.py`：用 fake backend 验证接口与选择逻辑；可选后端测试在缺依赖时 `skip`。
- 核心 422 测试不受影响（`norecursedirs` 已排除 `skills/` 等；ext 测试独立）。

**验收**：默认 TF-IDF 零依赖可用；配 `llama_index` 后端时能切换；pytest 全绿。

---

## P5 · 多智能体编排增强

**目标**：借鉴 crewAI「角色(role)」、MetaGPT「组织仿真」，在现有组合内核上补 `team` 模式，复用 `coding/eval/autonomous/safe-review` 命名模式。

**具体任务**
- 在 `baize/modes.py` 增加 `team` 模式，或新增 `baize/team.py`：`Role` 契约（name / goal / backstory / tools）、`Crew` 装配、顺序/层级交接。
- 复用 `component` 的 `Kind` 作为角色单元；交接经 `orchestrator` 的 `Verifier` 硬化、fail-closed。
- `baize/cli.py` 的 `team` 子命令扩展支持角色清单（YAML/JSON）。

**门禁**
- `tests/test_team.py`：team 装配、角色缺失 fail-closed、显式 `BAIZE_COMPONENTS` 覆盖生效。
- `gate` 绿。

**验收**：`baize team "<goal>" --roles roles.yaml` 能按角色编排并 Verifier 核验；pytest 全绿。

---

## P6 · 文档与基准（英文 + 对比 + examples）

**目标**：把差异化讲出口、给对比证据、给可抄的最小示例。

**具体任务**
1. `benchmarks/COMPARISON.md` 更新：加 baize 行，与 LangChain / AutoGPT / CrewAI / MetaGPT 在 `依赖数 / 启动时间 / 审计面 / 验证门禁 / 体积(468KB)` 维度对标（数据真实，不编造）。
2. 英文速览：README 已含 EN hero；补 `docs/README-en.md` 或把 `tutorials/01-认识白泽引擎.md` 加英文摘要。
3. `examples/` 增加：`mcp_minimal.py`（P2）、`team_minimal.py`（P5）、`rag_backend.py`（P4）。
4. 链接校验：脚本扫 `docs/**` 与 `README.md` 内部链接，确保无断链（沿用 V24 的链接修复纪律）。

**门禁**：链接校验通过；`pytest` 全绿；examples 可运行（至少 dry-run 不报错）。
**验收**：COMPARISON 有 baize 对标行；examples 三个最小可运行；无断链。

---

## P7 · 收尾与验收

**目标**：闭环 NO FAKE DONE，产出 V25 验收报告。

**具体任务**
1. 复跑门禁：`baize doctor` → PASSED；`baize gate` → manifest PASS + quality ≥ 0.8；全量 `pytest` → 422 passed / 1 skipped / 0 failed。
2. 可见性核对清单：
   - [ ] GitHub `topics` 非空且含 `agent` 类
   - [ ] `description` 显示 V23.0.0 且突出 zero-dependency
   - [ ] README 中英双语 + 对比表 + 失实数修正
   - [ ] 英文文档 / COMPARISON 对标
   - [ ] badges 正常
3. 写 `docs/VERIFICATION_V25.md`：范围、各阶段变更、门禁结果、可见性核对结果、回归记录。

**验收（Definition of Done）**
- [ ] P0–P6 全部 done 且门禁绿。
- [ ] `topics` 非空；`description` 更新；README 修正且双语。
- [ ] MCP client/server 可演示（mock 测试绿）。
- [ ] provider ≥ 3（OpenAI / Anthropic / DeepSeek 或 Ollama）。
- [ ] `pytest` 全绿（422/1skip/0fail）；`doctor` + `gate` 通过。
- [ ] `docs/VERIFICATION_V25.md` 完成。

---

## 风险登记

| 风险 | 缓解 |
|------|------|
| 生态接入破坏零依赖红线 | 全部走 `baize/ext/`，核心延迟 import；`import baize` 烟雾测试纳入门禁 |
| 覆盖率假绿 | 不声称覆盖率，或真跑 `coverage run`；README 如实标 |
| MCP/向量后端引入重依赖拖慢 CI | ext 测试独立标记，缺依赖 `skip`；`norecursedirs` 已排除干扰 |
| 重写内核偏离 V25 范围 | 红线：V25 = 接入 + 可见性；功能大版本留 V26 |
| 文档/示例腐烂 | P6 链接校验 + examples dry-run 纳入门禁 |

---

## 优先级与建议排期

1. **P0 + P1（立刻，最高 ROI）**：零/低代码，直接决定「是否被看见」；顺便修掉 README 自假绿。
2. **P2 MCP（次之）**：最小代价接入最大工具生态。
3. **P3 / P4 / P5（按需）**：不强求全进 V25，按社区反馈排。
4. **P6 / P7（收尾）**：随接入进度推进。
