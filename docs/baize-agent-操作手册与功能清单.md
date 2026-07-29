# 白泽引擎 baize-agent · 操作手册与功能清单

> 版本 **V19.0.0** ｜ 交付文件
> 配套文档：`README.md`（架构）、`benchmarks/COMPARISON.md`（对标基准）、`V19重构交付报告.md`（重构说明）
> 参考对标：<https://pi.dev/> ｜ <https://github.com/NousResearch/hermes-agent>

---

## 文档导航

| 章节 | 内容 |
|------|------|
| 第一章 | 操作手册（安装 / 配置 / 全部命令 / 工具 / 安全 / 排错） |
| 第二章 | 功能清单（按能力域分类） |
| 第三章 | 与 hermes-agent / pi-agent 的能力对比矩阵 |
| 第四章 | 白泽特有功能（两者所无、白泽独有） |
| 附录 | 验证数据、文件清单、术语 |

---

# 第一章　操作手册

## 1.1 安装与初始化

白泽运行时为**纯 Python 标准库实现，零第三方运行时依赖**（仅测试期需要 `pytest` / `coverage`）。

```bash
cd D:/gogogo
cp .env.example .env          # 1. 生成配置
python -m baize doctor        # 2. 环境门禁（必须通过，exit 0）
python -m baize index build   # 3. 构建技能索引（249 技能 / 3 来源）
```

运行要求：`python >= 3.10`（当前环境 3.13）。`doctor` 会真实探测 Python、`.env`、各目录可写性、技能库路径、必备命令行工具（`git` / `node`），任一阻断项失败则 `exit 1`。

## 1.2 配置（`.env`）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `SKILL_LIBRARY_PATHS` | 外部技能库路径（逗号分隔绝对路径），索引器扫描其下 `SKILL.md` | `D:/picasso-dev-skill/skills,D:/skills` |
| `BAIZE_MODEL_BASE_URL` | 任意 OpenAI 兼容 chat-completions 端点（OpenAI / OpenRouter / Ollama / vLLM / 本地网关） | 空（未配则 `run`/`team` 拒启 exit 2） |
| `BAIZE_MODEL_NAME` | 模型名（如 `gpt-4o-mini`） | 空 |
| `BAIZE_MODEL_API_KEY` | 端点 API Key，留空则不带 Authorization 头 | 空 |
| `BAIZE_LLM_MAX_RETRIES` | LLM 调用失败重试次数 | `2` |
| `BAIZE_AGENT_MAX_STEPS` | 单 Agent 思考→工具→观察迭代上限（防失控） | `24` |
| `BAIZE_WORKSPACE_DIR` | 工具沙箱根目录，文件工具不可越界 | 仓库根 |
| `BAIZE_ALLOW_OUTSIDE_WORKSPACE` | 是否允许工具访问工作区外路径（**默认 0 = 禁止**） | `0` |
| `BAIZE_SESSIONS_DIR` | JSONL 会话转录目录（崩溃安全、可续跑） | `./persistence/sessions` |
| `BAIZE_PERSISTENCE_DIR` / `BAIZE_PROJECTS_DIR` / `BAIZE_ASSETS_DIR` / `BAIZE_INDEX_FILE` | 持久化 / 项目 / 资产 / 索引文件根目录 | 仓库内对应目录 |

> **安全默认值**：模型端点未配置时 `run` / `team` **明确拒绝并 exit 2**；工具沙箱默认开启；危险命令 deny-list 默认拦截（`fail-closed`）。

## 1.3 命令速查表

| 命令 | 作用 | 退出码 |
|------|------|--------|
| `python -m baize doctor` | 环境门禁探测 | 0 通过 / 1 失败 |
| `python -m baize index build` | 构建技能索引 | 0 |
| `python -m baize index search <keyword>` | 按关键词检索技能 | 0 命中 / 1 无 / 2 缺参 |
| `python -m baize manifest validate <path>` | 校验流水线 manifest（证据物理核验） | 0 VALID / 1 失败 |
| `python -m baize memory log "文本" [--tags a,b]` | 记录一条事件 | 0 |
| `python -m baize memory remember "文本"` | 记录一条长期笔记 | 0 |
| `python -m baize memory recall <keyword>` | 按关键词+标签回溯记忆 | 0 命中 / 1 无 |
| `python -m baize memory stats` | 记忆统计 | 0 |
| `python -m baize run "<目标>" [--resume <id>]` | 启动**单 Agent** 自主执行 | 0 完成 / 1 未达成 / 2 未配置 |
| `python -m baize team "<目标>"` | 启动 **Director→Executor→Verifier** 团队 | 0 成功 / 1 失败 / 2 未配置 |
| `python -m baize sessions [<id>]` | 列出/回放会话转录 | 0 |

## 1.4 单 Agent 运行（`run`）

```bash
# 配置好模型端点后
python -m baize run "为 utils.py 补齐单元测试"
```

- 启动时**自动注入技能索引 + 相关持久记忆**（环境感知），无需手动拼提示词。
- 自主循环：思考 → 调用工具 → 观察结果 → 迭代，直到 `BAIZE_AGENT_MAX_STEPS` 上限或产出最终答案。
- 全程写入 JSONL 会话转录，崩溃不丢状态。

## 1.5 多 Agent 团队（`team`）

```bash
python -m baize team "实现用户登录接口并端到端验证"
```

- **Director** 规划拆解任务 → **Executor** 执行 → **Verifier** 独立取证核验。
- Verifier 核验失败会**自动带 issues 重试**（上限 `max_retries_per_task`）；全部通过才标记完成（**NO FAKE DONE 可执行化**）。
- 每个角色使用**独立会话**，全链路可审计。

## 1.6 会话管理与续跑（`sessions` / `--resume`）

```bash
python -m baize sessions                 # 列出全部会话（最多 30 条，含事件数与时间）
python -m baize sessions <session_id>    # 回放该会话的每一步（角色/内容/调用工具）
python -m baize run "继续上次任务" --resume <session_id>   # 从断点续跑
```

## 1.7 技能索引（`index`）

```bash
python -m baize index build              # 重新扫描并去重构建索引
python -m baize index search tdd         # 检索含 tdd 的技能，返回名称/来源/描述/路径
```

- 索引覆盖 3 个来源、去重后 **249 个唯一技能**。
- Agent 在运行时按需 `search_skills` / `load_skill`（**渐进披露**，不一次性灌入上下文）。

## 1.8 流水线门禁（`manifest`）

```bash
python -m baize manifest validate projects/simple-shopping-platform/manifest.json
```

- 核验 manifest 中各 phase 标记为 `done` 时，其 `evidence` 证据文件**必须物理存在**；缺失即判失败（**NO FAKE DONE**）。

## 1.9 持久记忆（`memory`）

```bash
python -m baize memory log "完成登录接口" --tags dev,auth
python -m baize memory remember "项目采用 Go+Vue3 技术栈"
python -m baize memory recall 登录
python -m baize memory stats
```

- 存储于 `persistence/logs/*.jsonl` 与 `notes.md`；支持多关键词 AND + 标签 + 相关性评分检索。

## 1.10 内置工具（9 个原语工具）

| 工具 | 参数 | 说明 |
|------|------|------|
| `read_file` | `path`, `max_lines=400` | 读取工作区内文本文件 |
| `write_file` | `path`, `content` | 写入/覆盖工作区内文件 |
| `list_dir` | `path="."` | 列出目录条目 |
| `bash` | `command`, `timeout=60` | 在工作区内执行 shell（**deny-list 网关拦截**，60s 超时） |
| `search_skills` | `keyword` | 按关键词检索技能索引 |
| `load_skill` | `skill_file` | 按需加载完整 `SKILL.md`（渐进披露） |
| `memory_recall` | `keyword`, `tags=""` | 检索持久记忆 |
| `memory_log` | `text`, `tags=""` | 写入一条记忆事件 |
| `save_skill` | `name`, `description`, `body_markdown` | **自进化**：沉淀新技能并即时重建索引 |

- 工具通过 `ToolRegistry` 运行时可扩展（继承 pi 的「原语而非内置特性」哲学）。
- 文件类工具经 `_resolve_in_workspace` 限制在 `BAIZE_WORKSPACE_DIR`；`BAIZE_ALLOW_OUTSIDE_WORKSPACE=0` 时越界即 `PermissionError`。

## 1.11 安全与沙箱

- **工作区沙箱**：所有文件操作限定在 `BAIZE_WORKSPACE_DIR` 内，越界默认拒绝。
- **命令 deny-list（fail-closed）**：覆盖 `rm -rf /`、`rm -rf [盘符]:`、`format`、`mkfs`、`del /s`、`shutdown`、`reboot`、`> /dev/sd*`、`dd if=` 等危险模式，命中即拦截。
- **模型端点未配置 fail-closed**：`run` / `team` 在未配端点时明确拒绝（exit 2），不会带着空配置盲目发起请求。

## 1.12 常见排错

| 现象 | 原因 / 处理 |
|------|-------------|
| `doctor` 失败 | 查看报告定位缺失项（`.env` 缺失、技能库路径无效、目录不可写等），修复后重跑 |
| `run`/`team` 提示未配置 | 在 `.env` 填 `BAIZE_MODEL_BASE_URL` / `BAIZE_MODEL_NAME`（及 API Key） |
| `index` 返回 0 技能 | 检查 `SKILL_LIBRARY_PATHS` 指向的目录是否含 `SKILL.md` |
| `bash` 命令被拒 | 命中 deny-list 或越出工作区；确认命令安全性与路径 |
| `manifest validate` 失败 | 某 phase 标记完成但 evidence 文件不存在，补齐证据或更正标记 |

---

# 第二章　功能清单

## 2.1 按能力域分类

**A. 运行形态**
- [x] 规约 + 技能包（可被 Claude Code / Codex / WorkBuddy 作为规约包加载）
- [x] 自带 Agent 运行时（可独立 `run` / `team` 运行）—— **双模式**

**B. LLM 与自主循环**
- [x] 模型无关 OpenAI 兼容客户端（`llm.py`）
- [x] 自主循环：思考 → 工具 → 观察 → 迭代（`agent.py`）
- [x] 调用失败自动重试（`BAIZE_LLM_MAX_RETRIES`）
- [x] 迭代步数硬上限防失控（`BAIZE_AGENT_MAX_STEPS`）

**C. 多 Agent 编排**
- [x] Director→Executor→Verifier 三角色编排（`orchestrator.py`）
- [x] Verifier 独立取证核验
- [x] 核验失败自动带 issues 重试（NO FAKE DONE 可执行化）

**D. 工具系统**
- [x] 9 个原语工具 + 运行时可注册扩展
- [x] 工作区沙箱 + 命令 deny-list（fail-closed）
- [x] `save_skill` 技能自进化并即时重建索引

**E. 会话与记忆**
- [x] append-only JSONL 会话持久化，崩溃不丢、`--resume` 续跑
- [x] 多 Agent 各自独立会话，全链路可审计
- [x] 持久记忆：多关键词 AND + 标签 + 相关性评分

**F. 技能生态**
- [x] 249 唯一技能可索引检索、渐进披露加载
- [x] 外部技能库配置化引用（`SKILL_LIBRARY_PATHS`），索引器动态发现，不复制

**G. 工程门禁**
- [x] `doctor` 环境门禁（真实探测、真实退出码）
- [x] `manifest validate` 流水线门禁（证据文件必须物理存在）

**H. 测试与可维护性**
- [x] 69 个 pytest 真实测试（脚本化 transport 驱动整条循环，无 mock 屏蔽）
- [x] 91% 覆盖率（阈值 85%）
- [x] 纯标准库零运行时依赖（仅测试需 pytest/coverage）

**I. 方法论内置**
- [x] 毛选调查思想 + 卡帕西编码（可加载、可注入 Agent 提示词）

---

# 第三章　与 hermes-agent / pi-agent 对比

## 3.1 能力矩阵

| 能力维度 | 白泽引擎 V19 | hermes-agent | pi |
|----------|-------------|--------------|----|
| **运行形态** | 规约+技能包 + 自带 Agent 运行时（双模式） | 独立运行时 Agent | 独立运行时 Agent |
| **LLM 调用循环** | 自带（`baize run`，思考→工具→观察循环） | 自带 | 自带 |
| **模型接入** | OpenAI 兼容任意端点（llm.py，模型无关） | 模型无关 | 多模型 |
| **多 Agent 编排** | Director→Executor→Verifier + 失败自动重试 | 子 Agent | 无内置 |
| **独立核验门禁** | Verifier 独立取证核验（NO FAKE DONE 可执行化） | 无 | 无 |
| **工具系统** | 9 原语工具 + 运行时可注册扩展 | 内置工具集 | 原语工具+扩展 |
| **工具沙箱** | 工作区限制 + 命令 deny-list（fail-closed） | sandbox/TEE | 无强制 |
| **会话持久化** | append-only JSONL，崩溃不丢、`--resume` 续跑 | 有 | JSONL+checkpoint |
| **技能体系** | 249 唯一技能可索引检索 + 渐进披露加载 | skills | 扩展包 |
| **技能自进化** | `save_skill` 工具沉淀新技能并即时重建索引 | 自进化技能 | 手动 |
| **多客户端支持** | 兼作 Claude Code / Codex / WorkBuddy 规约包 | 自有 CLI | 自有 CLI/TUI |
| **环境门禁** | baize doctor（真实探测，exit code 驱动） | 启动检查 | 启动检查 |
| **流水线门禁** | manifest validate（证据物理核验） | 无 | 无 |
| **持久记忆** | JSONL+notes，多关键词 AND + tags + 相关性评分 | 上下文 | 上下文 |
| **测试体系** | 69 个 pytest（脚本化 transport 真实驱动），91% 覆盖率 | 内置 | 内置 |
| **运行时依赖** | 纯标准库零依赖（仅测试需 pytest/coverage） | 需 pip 依赖 | 需 npm/pip |
| **方法论内置** | 毛选调查 + 卡帕西编码（可加载可注入技能） | 无 | 无 |

## 3.2 从两者学到并升级的设计

| 来源 | 学到的被验证设计 | 白泽的升级 |
|------|------------------|-----------|
| hermes | 自主循环、模型无关客户端 | 循环启动时自动注入技能索引 + 相关持久记忆（环境感知启动） |
| hermes | 自进化技能 | `save_skill` 落盘即重建索引，全体 Agent 立即可检索 |
| pi | 极简内核 + 原语工具 | 保持零依赖 stdlib，工具注册表运行时可扩展 |
| pi | JSONL 会话持久化 | 叠加多 Agent 编排：每个角色独立会话，全链路可审计 |
| 白泽独有 | — | Verifier 独立核验门禁、manifest 证据物理核验、doctor 环境门禁、249 技能生态、双模式（可被外部客户端加载，也可自主运行） |

> 能力矩阵中对 hermes/pi 的描述基于其公开文档（github.com/NousResearch/hermes-agent 与 pi.dev）；
> 实际量化对标数据需按 `benchmarks/COMPARISON.md` 的 BTS-001~005 基准在相同模型/硬件下执行回填。

---

# 第四章　白泽特有功能（两者所无）

以下功能为 hermes-agent 与 pi 均不具备，属于白泽在整合升级中的**差异化能力**：

1. **独立核验门禁（Verifier）** —— 多 Agent 编排中 Verifier 角色独立取证核验，失败自动带 issues 重试，把「NO FAKE DONE」从原则变成**可强制执行的机制**（hermes 仅子 Agent、无独立核验；pi 无内置编排）。

2. **流水线证据物理核验（manifest validate）** —— 任意 phase 标记 `done`，其 `evidence` 文件必须**物理存在**，否则判失败。把交付门禁前移到工具层，杜绝「声称完成却无证据」（hermes/pi 均无）。

3. **环境门禁（doctor）真实退出码驱动** —— 启动前真实探测 Python / `.env` / 目录可写性 / 技能库路径 / CLI 工具，失败以 `exit 1` 阻断，而非打印告警后继续。

4. **技能自进化即时生效** —— `save_skill` 不仅是写到磁盘，更**落盘即重建索引**，学习成果对全体 Agent 立即可检索复用（hermes 自进化技能未强调即时索引重建；pi 为手动）。

5. **双模式运行** —— 同一套规约既可被 Claude Code / Codex / WorkBuddy 作为「被加载的规约包」使用，也能以 `run` / `team` 独立运行；hermes/pi 主要作为自有独立运行时。

6. **大规模技能生态 + 渐进披露** —— 249 个去重唯一技能可索引检索，Agent 运行时按需 `search_skills` / `load_skill`，避免一次性灌入上下文；外部技能库配置化引用、动态发现、不复制。

7. **持久记忆系统** —— 跨会话 JSONL 记忆 + 笔记，支持多关键词 AND + 标签 + 相关性评分检索，且可在 Agent 启动时自动召回相关上下文（hermes/pi 主要依赖当次上下文）。

8. **零运行时依赖 + 确定性测试** —— 运行时纯标准库实现；测试用**可注入的脚本化 transport** 真实驱动整条 Agent 循环（非 MagicMock 屏蔽），69 测试、91% 覆盖率，可复现、可审计。

9. **方法论内置** —— 毛选调查思想 + 卡帕西编码作为可加载/可注入技能，将「调查先行」「外科手术式变更」固化为 Agent 行为准则（hermes/pi 均无内置方法论层）。

---

# 附录

## A. 验证数据（实测）

| 项 | 结果 |
|----|------|
| 版本 | 19.0.0 |
| `doctor` | PASSED（exit 0） |
| 运行时测试 | `tests/` 69 passed |
| 覆盖率 | 91%（阈值 85%，各模块均 ≥85%） |
| 技能索引 | 249 skills / 3 sources |
| `manifest validate` | VALID |
| `run`/`team` 未配置 | exit=2（明确拒绝） |
| 会话 / 记忆 | 可列、可回放、可写、可回溯 |

> 遗留（非阻断）：`legacy/engine-v17` 含 3 个旧 harness 测试失败（引用已清理的 `temp_repos`，与 V19 无关，仅归档追溯）；`doctor` 中 `go` 工具为 optional WARN。

## B. 交付文件清单

| 文件 | 用途 |
|------|------|
| `baize-agent-操作手册与功能清单.md` | 本文件（操作手册 + 功能清单 + 对比 + 特有功能） |
| `README.md` | 架构图与快速开始 |
| `V19重构交付报告.md` | V19 重构说明与验收结论 |
| `benchmarks/COMPARISON.md` | 与 hermes/pi 对标基准 + BTS 基准任务 |
| `AGENT.md` / `SKILL.md` / `START-HERE.md` | 操作协议 / 流水线规约 / 上手指引 |
| `openspec/specs/baize-{llm,tools,agent,orchestrator}` | 4 份运行时模块规格 |

## C. 术语

- **NO FAKE DONE**：标记完成必须伴随物理证据，禁止无证据的「已完成」。
- **渐进披露**：技能索引常驻，完整内容按需加载，避免上下文膨胀。
- **fail-closed**：默认拒绝，仅在明确允许时放行（沙箱越界、deny-list、未配置端点均如此）。
- **脚本化 transport**：在测试中注入假 HTTP transport，真实驱动整条 Agent 循环，保证确定性。

---

*— 白泽引擎乙方研发团队 ｜ 2026-07-29*
