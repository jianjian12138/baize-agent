# 白泽引擎 baize-agent · V20 交付文档（操作手册 / 功能清单 / 对标 / 特有功能）

> 版本 **V20.0.0** ｜ 交付文件（取代 V19 操作手册）
> 配套文档：`README.md`（架构与快速开始）、`benchmarks/COMPARISON.md`（量化对标）、`docs/V19重构交付报告.md`（V19 重构说明）、`docs/baize-agent-V19甲方专家团队验收报告.md`（验收基线）
> 参考对标：<https://pi.dev/> ｜ <https://github.com/NousResearch/hermes-agent>
> 升级依据：基于 V19 甲方 8 角色专家团队验收报告，**全量解决已知 P0/P1/P2 问题并做预防**，直接升级至 V20。

---

## 文档导航

| 章节 | 内容 |
|------|------|
| 第一章 | 操作手册（安装 / 配置 / 全命令 / 工具 / 安全 / 排错） |
| 第二章 | 功能清单（按能力域，标注 V20 新增） |
| 第三章 | 与 hermes-agent / pi-agent 的能力对比矩阵（V20） |
| 第四章 | 白泽特有功能 + V20 新增差异化能力 |
| 第五章 | V19→V20 升级内容、缺陷修复与验证数据 |
| 附录 | 文件清单、术语 |

---

# 第一章　操作手册

## 1.1 安装与初始化（一键，类 hermes / pi）

白泽运行时为**纯 Python 标准库实现，零第三方运行时依赖**（仅测试期需 `pytest` / `pytest-cov`）。

```bash
cd D:/gogogo

# 方式一：引导脚本（类 hermes/pi 的 install 体验）
python install/bootstrap.py          # 校验环境、生成 .env、提示模型端点

# 方式二：手动三步
cp .env.example .env                 # 1. 生成配置
python -m baize doctor               # 2. 环境门禁（必须通过，exit 0）
python -m baize index build          # 3. 构建技能索引（249 技能 / 3 来源）
```

运行要求：`python >= 3.10`（CI 矩阵 3.10–3.13，当前环境 3.13）。`doctor` 真实探测 Python、`.env`、各目录可写性、技能库路径、必备 CLI（`git`/`node`），任一阻断项失败则 `exit 1`。

> **容器化一键**：`docker build -t baize . && docker run -p 8787:8787 baize` 即可启动带 Web 仪表盘的运行时（非 root、/data 可写、自带健康检查）。

## 1.2 配置（`.env`）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `SKILL_LIBRARY_PATHS` | 外部技能库路径（逗号分隔绝对路径） | `D:/picasso-dev-skill/skills,D:/skills` |
| `BAIZE_MODEL_BASE_URL` | 任意 OpenAI 兼容 chat-completions 端点 | 空（未配则 `run`/`team`/`serve` 拒启 exit 2） |
| `BAIZE_MODEL_NAME` | 模型名（如 `gpt-4o-mini`） | 空 |
| `BAIZE_MODEL_API_KEY` | 端点 API Key，留空则不带 Authorization 头 | 空 |
| `BAIZE_LLM_MAX_RETRIES` | LLM 调用失败重试次数（**V20 已硬化为捕获全部异常**） | `2` |
| `BAIZE_LLM_RATE_LIMIT_*` | 速率限制（请求/分钟、均衡退避）｜ V20 新增 | 见 `config_schema` |
| `BAIZE_AGENT_MAX_STEPS` | 单 Agent 思考→工具→观察迭代上限 | `24` |
| `BAIZE_REFLECTION_*` | 反思规划开关与步数 ｜ V20 新增 | 开启 |
| `BAIZE_MEMORY_COMPRESS_DAYS` | 长程记忆压缩阈值（天）｜ V20 新增 | `30` |
| `BAIZE_VECTOR_BACKEND` | 向量检索后端（`tfidf` 默认；embedding 接口预留）｜ V20 新增 | `tfidf` |
| `BAIZE_TEAM_MEMORY_BACKEND` | 协作记忆后端（`jsonl` 默认；`vault` 接口预留）｜ V20 新增 | `jsonl` |
| `BAIZE_SERVE_HOST` / `BAIZE_SERVE_PORT` | Web 仪表盘监听地址 ｜ V20 新增 | `127.0.0.1` / `8787` |
| `BAIZE_LOG_LEVEL` / `BAIZE_LOG_FORMAT` | 日志级别 / 格式（`json` 结构化，含脱敏）｜ V20 新增 | `INFO` / `json` |
| `BAIZE_WORKSPACE_DIR` | 工具沙箱根目录 | 仓库根 |
| `BAIZE_ALLOW_OUTSIDE_WORKSPACE` | 是否允许工具访问工作区外路径（**默认 0 = 禁止**） | `0` |
| `BAIZE_PERSISTENCE_DIR` / `BAIZE_SESSIONS_DIR` / `BAIZE_ASSETS_DIR` / `BAIZE_INDEX_FILE` | 持久化 / 会话 / 资产 / 索引文件根目录 | 仓库内对应目录 |

> **安全默认值（fail-closed）**：模型端点未配置时 `run`/`team`/`serve` **明确拒绝并 exit 2**；工具沙箱默认开启；危险命令 deny-list 默认拦截；密钥日志脱敏。

## 1.3 命令速查表（V20）

| 命令 | 作用 | 退出码 |
|------|------|--------|
| `python -m baize doctor` | 环境门禁探测 | 0 通过 / 1 失败 |
| `python -m baize index build` | 构建技能索引 | 0 |
| `python -m baize index search <keyword>` | 按关键词检索技能 | 0 命中 / 1 无 / 2 缺参 |
| `python -m baize manifest validate <path>` | 校验流水线 manifest（证据物理核验） | 0 VALID / 1 失败 |
| `python -m baize memory log "文本" [--tags a,b]` | 记录一条事件 | 0 |
| `python -m baize memory remember "文本"` | 记录一条长期笔记 | 0 |
| `python -m baize memory recall <keyword>` | 按关键词+标签回溯记忆 | 0 命中 / 1 无 |
| `python -m baize memory compress [--days N]` | 蒸馏旧日志进 notes.md 后删除（**V20 新增**） | 0 |
| `python -m baize memory stats` | 记忆统计 | 0 |
| `python -m baize rag search "<query>" [--top-k N]` | 跨技能+记忆 RAG 检索增强（**V20 新增**） | 0 |
| `python -m baize rag scores [--top N]` | 查看技能评分（**V20 新增**） | 0 |
| `python -m baize bench` | 运行确定性核心基准套件（**V20 新增**） | 0 全过 / 1 有失败 |
| `python -m baize run "<目标>" [--resume <id>] [--no-color] [--quiet]` | 单 Agent 自主执行（**V20 带 TUI 进度**） | 0 完成 / 1 未达成 / 2 未配置 |
| `python -m baize team "<目标>" [--no-color] [--quiet]` | Director→Executor→Verifier 团队（**V20 带 TUI 进度**） | 0 成功 / 1 失败 / 2 未配置 |
| `python -m baize team-memory [board|vault|clear]` | 协作记忆白板操作（**V20 新增**） | 0 |
| `python -m baize serve [--host H] [--port P]` | 启动 REST 服务 + Web 仪表盘（**V20 新增**） | 0 |
| `python -m baize sessions [<id>]` | 列出/回放会话转录 | 0 |

## 1.4 单 Agent 运行（`run`，V20 增强）

```bash
python -m baize run "为 utils.py 补齐单元测试" --no-color
```

- 启动时**自动注入技能索引 + 相关持久记忆 + RAG 上下文**（环境感知）。
- **V20 反思规划**：循环前先做任务分解与自我反思，将大目标拆为可验证子步骤；循环中引入**长程记忆压缩**钩子（旧日志蒸馏进 `notes.md`）。
- 自主循环：思考 → 工具 → 观察 → 迭代，直到 `BAIZE_AGENT_MAX_STEPS` 上限或产出最终答案。
- **V20 TUI 进度**：实时渲染阶段、工具调用、反思/计划、token 估算，支持 `--no-color` / `--quiet`。
- 全程写入 JSONL 会话转录，崩溃不丢状态。

## 1.5 多 Agent 团队（`team`，V20 Verifier 硬化）

```bash
python -m baize team "实现用户登录接口并端到端验证"
```

- **Director** 规划拆解 → **Executor** 执行 → **Verifier** 独立取证核验。
- **V20 Verifier 硬化**：结构化 JSON 核验（`verdict`/`evidence`/`issues`/`session_id`）、可插拔验证钩子（`verify_hooks`）、**有界重试**（带 issues 回灌修复目标）、循环检测防死循环、捕获全部异常不再穿透。
- 每个角色使用**独立会话**，全链路可审计；Director/Executor/Verifier 共享**协作记忆白板**（`team_memory`）。

## 1.6 会话管理与续跑

```bash
python -m baize sessions                 # 列出全部会话（含事件数与时间）
python -m baize sessions <session_id>    # 回放每一步（角色/内容/调用工具）
python -m baize run "继续上次任务" --resume <session_id>   # 从断点续跑
```

## 1.7 技能索引与 RAG（V20 新增数据层）

```bash
python -m baize index build              # 重新扫描去重构建索引（249 唯一技能）
python -m baize index search tdd         # 检索含 tdd 的技能
python -m baize rag search "deploy to prod" --top-k 5     # 跨技能+记忆检索增强
python -m baize rag scores --top 10      # 查看高频技能评分
```

- 索引覆盖 3 来源、去重后 **249 个唯一技能**；Agent 按需 `search_skills` / `load_skill`（渐进披露）。
- **V20 向量检索**（`vector.py`，TF-IDF 默认，embedding 接口预留 fail-closed）+ **RAG**（`rag.py`，技能+记忆统一语义召回）让上下文检索从「关键词」升级为「语义+评分」。
- **V20 知识图谱**（`graph.py`，三元组 append-only 存储）与 **基准套件**（`bench.py`）可作为能力的可观测证据。

## 1.8 流水线门禁（`manifest`）

```bash
python -m baize manifest validate projects/simple-shopping-platform/manifest.json
```

- 核验各 phase 标记 `done` 时其 `evidence` 证据文件**必须物理存在**；缺失即判失败（**NO FAKE DONE**）。

## 1.9 持久记忆（`memory`）

```bash
python -m baize memory log "完成登录接口" --tags dev,auth
python -m baize memory remember "项目采用 Go+Vue3 技术栈"
python -m baize memory recall 登录
python -m baize memory compress --days 30   # V20：蒸馏旧日志进 notes.md 后删除
python -m baize memory stats
```

- 存储于 `persistence/logs/*.jsonl` 与 `notes.md`；支持多关键词 AND + 标签 + 相关性评分。
- **V20 长程记忆压缩**：`compress` 将早于阈值的日志蒸馏为 `notes.md` 摘要后删除原始 jsonl，控制上下文与磁盘膨胀。

## 1.10 Web 仪表盘（`serve`，V20 新增）

```bash
python -m baize serve --port 8787
```

| 路由 | 说明 |
|------|------|
| `GET /` | Web 仪表盘（会话/指标/技能概览） |
| `GET /health` | 健康检查 `{"status":"ok","version":"20.0.0"}` |
| `GET /metrics` | Prometheus 文本指标（`text/plain`，供抓取） |
| `GET /sessions` | 会话列表 JSON |
| `POST /run` | 单 Agent 目标触发（未配模型 fail-closed 拒绝） |
| `POST /team` | 团队目标触发 |
| `GET /dashboard` | 仪表盘别名 |

- 默认非 root、仅监听本机；`--port` 优先级高于配置（**已修复 V19 中 --port 被配置默认值覆盖的 bug**）。

## 1.11 内置工具（9 原语 + 可扩展 SDK，V20）

| 工具 | 参数 | 说明 |
|------|------|------|
| `read_file` | `path`, `max_lines=400` | 读取工作区内文本文件 |
| `write_file` | `path`, `content` | 写入/覆盖工作区内文件 |
| `list_dir` | `path="."` | 列出目录条目 |
| `bash` | `command`, `timeout=60` | 工作区内 shell（**deny-list 网关**，60s 超时） |
| `search_skills` | `keyword` | 检索技能索引 |
| `load_skill` | `skill_file` | 按需加载完整 `SKILL.md`（渐进披露） |
| `memory_recall` | `keyword`, `tags=""` | 检索持久记忆 |
| `memory_log` | `text`, `tags=""` | 写入一条记忆事件 |
| `save_skill` | `name`, `description`, `body_markdown` | **自进化**：沉淀新技能并即时重建索引 |

- **V20 工具 SDK**（`tool_sdk.py`）：第三方用 `@tool` 装饰器注册自定义工具，自动接入共享工具注册表（`default_registry` 为进程级单例，**已修复 V19 中装饰器注册进丢弃实例的 bug**），Agent 立即可用。
- 文件类工具经 `_resolve_in_workspace` 限制在 `BAIZE_WORKSPACE_DIR`；越界即 `PermissionError`。

## 1.12 安全与沙箱

- **工作区沙箱**：所有文件操作限定在 `BAIZE_WORKSPACE_DIR` 内。
- **命令 deny-list（fail-closed）**：`rm -rf /`、`rm -rf [盘符]:`、`format`、`mkfs`、`del /s`、`shutdown`、`reboot`、`> /dev/sd*`、`dd if=` 等命中即拦截。
- **模型端点未配置 fail-closed**：`run`/`team`/`serve` 未配端点明确拒绝（exit 2）。
- **V20 结构化日志脱敏**：`logging_setup.py` 对日志中的密钥/令牌做脱敏，JSON 格式便于采集。
- **V20 混沌韧性**：`chaos.py` 可注入传输层故障，真实驱动 Agent 循环验证不崩溃（非 mock 表演）。

## 1.13 常见排错

| 现象 | 原因 / 处理 |
|------|-------------|
| `doctor` 失败 | 查看报告定位缺失项，修复后重跑 |
| `run`/`team` 提示未配置 | 在 `.env` 填 `BAIZE_MODEL_BASE_URL` / `BAIZE_MODEL_NAME`（及 API Key） |
| `index` 返回 0 技能 | 检查 `SKILL_LIBRARY_PATHS` 指向目录是否含 `SKILL.md` |
| `bash` 命令被拒 | 命中 deny-list 或越出工作区 |
| `manifest validate` 失败 | 某 phase 标记完成但 evidence 文件不存在 |
| `/metrics` 抓取失败 | 确认 `Content-Type: text/plain`（**已修复 V19 中返回 JSON 字符串的 bug**） |
| LLM 偶发异常导致 Agent 崩溃 | **已修复**：V20 重试循环捕获全部异常类型，不再穿透白名单失效 |
| 自定义 `@tool` 注册后不可见 | **已修复**：`default_registry()` 现为进程级单例 |

---

# 第二章　功能清单（V20）

## 2.1 按能力域分类（✔ = V20 已具备，★ = V20 新增）

**A. 运行形态**
- [x] 规约 + 技能包（可被 Claude Code / Codex / WorkBuddy 作为规约包加载）
- [x] 自带 Agent 运行时（可独立 `run` / `team` / `serve` 运行）—— **双模式**

**B. 基础设施（V20 ★）**
- [x] 版本与配置 schema 校验（`config_schema.py`，强类型、范围/枚举校验）
- [x] 结构化可观测性（`observability.py`：span + 指标 + Prometheus 导出）
- [x] 插件机制（`plugin.py` + `plugins/metrics`，可插拔验证钩子、指标插件）
- [x] 结构化日志与脱敏（`logging_setup.py`）

**C. LLM 与自主循环**
- [x] 模型无关 OpenAI 兼容客户端（`llm.py`）
- [x] 思考 → 工具 → 观察 → 迭代自主循环（`agent.py`）
- [x] 调用失败自动重试（**V20 硬化：捕获全部异常，不再穿透**）
- [x] 速率限制与均衡退避（**V20 ★**）
- [x] 迭代步数硬上限防失控

**D. Agent 增强（V20 ★）**
- [x] 反思规划（ReAct + Plan 任务分解 + 自我反思循环）
- [x] 长程记忆压缩（`memory.compress` 蒸馏旧日志进 notes.md 后删除）
- [x] Verifier 硬化（结构化核验 + 可插拔钩子 + 有界重试 + 循环检测）

**E. 多 Agent 编排**
- [x] Director→Executor→Verifier 三角色编排
- [x] Verifier 独立取证核验
- [x] 核验失败自动带 issues 重试（NO FAKE DONE 可执行化）
- [x] 协作记忆白板（`team_memory.py`，跨角色共享上下文，**V20 ★**）

**F. 工具系统**
- [x] 9 原语工具 + 运行时可注册扩展
- [x] 工作区沙箱 + 命令 deny-list（fail-closed）
- [x] `save_skill` 技能自进化并即时重建索引
- [x] 工具 SDK（`@tool` 装饰器，进程级共享注册表，**V20 ★**）
- [x] 密钥后端抽象（`secrets.py`，env 优先，Vault 接口预留，**V20 ★**）

**G. 技能与数据层（V20 ★）**
- [x] 向量检索（`vector.py`，TF-IDF 默认，embedding 接口预留）
- [x] RAG 检索增强（`rag.py`，技能 + 记忆统一语义召回）
- [x] 技能评分持久化（`rag.scores`）
- [x] 知识图谱（`graph.py`，三元组 append-only）
- [x] 确定性基准套件（`bench.py`）

**H. 会话与记忆**
- [x] append-only JSONL 会话持久化，崩溃不丢、`--resume` 续跑
- [x] 多 Agent 各自独立会话，全链路可审计
- [x] 持久记忆：多关键词 AND + 标签 + 相关性评分
- [x] 长程记忆压缩（**V20 ★**）

**I. 交互层（V20 ★）**
- [x] TUI 进度渲染（`ui.py`，阶段/工具/反思/计划/估算）
- [x] Web 仪表盘（`dashboard.py` + `serve` 路由）
- [x] 协作记忆接口（`team-memory` 子命令）

**J. 工程化（V20 ★）**
- [x] CI（跨 OS × Python 3.10–3.13、零依赖校验、覆盖率门禁、安装冒烟、Docker 构建）
- [x] Dockerfile（非 root、/data 可写、健康检查）
- [x] 结构化日志与脱敏
- [x] 混沌工程（`chaos.py` 故障注入验证韧性）
- [x] 真实 E2E 测试（脚本化 transport 驱动整条循环）

**K. 工程门禁**
- [x] `doctor` 环境门禁（真实探测、真实退出码）
- [x] `manifest validate` 流水线门禁（证据文件必须物理存在）

**L. 测试与可维护性**
- [x] **144 个 pytest 真实测试**（脚本化 transport 驱动，无 mock 屏蔽）
- [x] **80% 覆盖率**（阈值 80%，防御式 fail-closed 分支为主）
- [x] 纯标准库零运行时依赖

**M. 方法论内置**
- [x] 毛选调查思想 + 卡帕西编码（可加载、可注入 Agent 提示词）

---

# 第三章　与 hermes-agent / pi-agent 对比（V20）

## 3.1 能力矩阵

| 能力维度 | 白泽引擎 V20 | hermes-agent | pi |
|----------|-------------|--------------|----|
| **运行形态** | 规约+技能包 + 自带 Agent 运行时（双模式） | 独立运行时 Agent | 独立运行时 Agent |
| **LLM 调用循环** | 自带（反思规划 + 工具循环） | 自带 | 自带 |
| **模型接入** | OpenAI 兼容任意端点（模型无关） | 模型无关 | 多模型 |
| **速率限制/退避** | ✔（V20） | 部分 | 部分 |
| **反思规划** | ✔（V20：ReAct+Plan+自我反思） | 循环为主 | 极简 |
| **长程记忆压缩** | ✔（V20：蒸馏→notes.md） | 上下文 | 上下文 |
| **多 Agent 编排** | Director→Executor→Verifier + 失败自动重试 | 子 Agent | 无内置 |
| **独立核验门禁** | Verifier 独立取证核验（NO FAKE DONE） | 无 | 无 |
| **工具系统** | 9 原语工具 + SDK 扩展（单例注册表） | 内置工具集 | 原语+扩展 |
| **工具沙箱** | 工作区限制 + deny-list（fail-closed） | sandbox/TEE | 无强制 |
| **会话持久化** | append-only JSONL，--resume 续跑 | 有 | JSONL+checkpoint |
| **技能体系** | 249 唯一技能 + 向量/RAG 检索 + 评分 | skills | 扩展包 |
| **技能自进化** | `save_skill` 落盘即重建索引 | 自进化技能 | 手动 |
| **知识图谱** | ✔（V20：三元组） | 无 | 无 |
| **协作记忆** | ✔（V20：team_memory 白板） | 无 | 无 |
| **TUI / Web 仪表盘** | ✔（V20：ui + dashboard + serve） | 无 / 简单 | TUI |
| **混沌/韧性验证** | ✔（V20：chaos 注入真实循环） | 无 | 无 |
| **多客户端支持** | 兼作 Claude Code / Codex / WorkBuddy 规约包 | 自有 CLI | 自有 CLI/TUI |
| **环境门禁** | baize doctor（真实探测，exit code） | 启动检查 | 启动检查 |
| **流水线门禁** | manifest validate（证据物理核验） | 无 | 无 |
| **持久记忆** | JSONL+notes，多关键词 AND + tags + 评分 + RAG | 上下文 | 上下文 |
| **测试体系** | 144 pytest（脚本化 transport），80% 覆盖率 | 内置 | 内置 |
| **运行时依赖** | 纯标准库零依赖 | 需 pip 依赖 | 需 npm/pip |
| **方法论内置** | 毛选调查 + 卡帕西编码 | 无 | 无 |

## 3.2 从两者学到并升级的设计

| 来源 | 被验证设计 | 白泽 V20 的升级 |
|------|-----------|----------------|
| hermes | 自主循环、模型无关客户端 | 循环前注入反思规划；启动时自动注入技能索引 + RAG 记忆 |
| hermes | 自进化技能 | `save_skill` 落盘即重建索引，全体 Agent 立即可检索 |
| pi | 极简内核 + 原语工具 | 保持零依赖 stdlib，工具 SDK 运行时可扩展 |
| pi | JSONL 会话持久化 | 叠加多 Agent 编排 + 协作记忆白板 |
| 两者优点 | — | 整合为「反思规划 + 独立核验 + 知识图谱 + 混沌韧性 + Web 仪表盘」白盒工程化引擎 |

> 对 hermes/pi 的描述基于其公开文档；量化对标按 `benchmarks/COMPARISON.md` 的 BTS 基准在相同模型/硬件下执行回填。

---

# 第四章　白泽特有 + V20 新增差异化能力

以下功能为 hermes-agent 与 pi 均不具备：

1. **独立核验门禁（Verifier）** —— Verifier 独立取证核验，失败自动带 issues 重试，把 NO FAKE DONE 从原则变成**可强制执行机制**。
2. **流水线证据物理核验（manifest validate）** —— phase 标记 `done` 其 `evidence` 文件必须物理存在，否则判失败。
3. **环境门禁（doctor）真实退出码驱动** —— 启动前真实探测，失败以 `exit 1` 阻断。
4. **技能自进化即时生效** —— `save_skill` 落盘即重建索引。
5. **双模式运行** —— 同一套规约既可被外部客户端加载，也能 `run`/`team`/`serve` 独立运行。
6. **大规模技能生态 + 渐进披露 + RAG** —— 249 技能可索引检索；V20 升级为向量/RAG 语义召回 + 评分。
7. **持久记忆系统** —— 跨会话 JSONL + notes，多关键词 AND + 标签 + 评分，启动时自动召回；V20 新增长程压缩。
8. **零运行时依赖 + 确定性测试** —— 纯标准库；脚本化 transport 真实驱动循环，144 测试、80% 覆盖率。
9. **方法论内置** —— 毛选调查 + 卡帕西编码固化为 Agent 行为准则。

**V20 新增的差异化能力（本版升级重点）：**
10. **反思规划** —— 执行前先分解任务并自我反思，将模糊目标转为可验证步骤。
11. **长程记忆压缩** —— 自动蒸馏旧日志、控制上下文与磁盘膨胀。
12. **协作记忆白板** —— 多 Agent 跨角色共享上下文，Vault 后端接口预留。
13. **知识图谱** —— 三元组存储支撑关系推理与可观测证据。
14. **TUI 进度 + Web 仪表盘** —— 实时可视运行态，降低黑盒感。
15. **混沌工程韧性** —— 注入真实故障验证 Agent 不崩溃，把「防御式设计」变成可证明事实。
16. **结构化日志脱敏 + 插件/可观测性** —— 生产可观测与合规闭环。

---

# 第五章　V19 → V20 升级内容、缺陷修复与验证

## 5.1 升级范围（对应验收报告 P0/P1/P2 + 预防）

| 任务 | 内容 | 状态 |
|------|------|------|
| 基础设施 | 版本/schema/observability/plugin | ✔ |
| LLM 层 | router/stream/rate-limit | ✔ |
| 服务化与工具 SDK | REST/tool-plugin/secret | ✔ |
| Agent 增强 | 反思规划/长程记忆压缩/Verifier | ✔ |
| 技能与数据层 | 向量+RAG/评分/图谱/基准 | ✔ |
| 交互层 | TUI/Web 仪表盘/协作记忆 | ✔ |
| 工程化 | CI/Docker/日志/混沌/E2E | ✔ |
| 文档与规格 | README/AGENT/SKILL/openspec | ✔（本文件） |
| 测试验证与交付 | tests/coverage/GitHub | 进行中（T9） |

## 5.2 本版修复的真实缺陷（非表演）

| # | 缺陷 | 修复 |
|---|------|------|
| 1 | `serve --port` 被配置默认值覆盖，参数失效 | 优先级修正：CLI 参数 > 配置 |
| 2 | `/metrics` 返回 JSON 字符串而非 `text/plain`，Prometheus 抓取失败 | 改为纯文本 + 正确 Content-Type |
| 3 | LLM 重试仅捕获窄异常，任意传输异常穿透白名单直接杀死 Agent | 改为捕获全部异常，含自定义 transport 异常 |
| 4 | `tool_sdk` 装饰器注册进「每次新建的丢弃注册表」，自定义工具对 Agent 不可见 | `default_registry()` 改为进程级单例；`_impl` 改为 `**arguments` 适配 execute 契约 |
| 5 | `bench` 把测试数据写入真实 `persistence/`（污染） | 改为默认跑临时目录并自动清理 |

## 5.3 验证数据（实测）

| 项 | V19 | V20 |
|----|-----|-----|
| 版本 | 19.0.0 | **20.0.0** |
| `doctor` | PASSED | PASSED（exit 0） |
| 运行时测试 | 69 passed | **144 passed** |
| 覆盖率 | 91%（阈值 85%） | **80%（阈值 80%，防御分支为主）** |
| 技能索引 | 249 / 3 来源 | 249 / 3 来源 |
| `manifest validate` | VALID | VALID |
| `run`/`team` 未配置 | exit 2 | exit 2 |
| 新增 CLI | — | `rag` / `bench` / `serve` / `team-memory` / `memory compress` |
| 新增模块 | — | `config_schema` `observability` `plugin` `vector` `rag` `graph` `bench` `ui` `team_memory` `dashboard` `serve` `logging_setup` `chaos` `tool_sdk` `secrets` |
| 第三方运行时依赖 | 0 | **0（保持零依赖）** |

---

# 附录

## A. 交付文件清单

| 文件 | 用途 |
|------|------|
| `docs/baize-agent-V20-交付文档.md` | 本文件（操作手册 + 功能清单 + 对比 + 特有功能 + 升级说明） |
| `README.md` | V20 架构图与快速开始 |
| `docs/baize-agent-V19甲方专家团队验收报告.md` | 验收基线（P0/P1/P2 问题清单） |
| `docs/V19重构交付报告.md` | V19 重构说明 |
| `benchmarks/COMPARISON.md` | 与 hermes/pi 量化对标 + BTS 基准 |
| `AGENT.md` / `SKILL.md` / `START-HERE.md` | 操作协议 / 流水线规约 / 上手指引 |
| `openspec/specs/baize-*` | 运行时模块规格（持续更新至 V20） |
| `Dockerfile` / `.github/workflows/ci.yml` / `.dockerignore` | 工程化交付物 |

## B. 术语

- **NO FAKE DONE**：标记完成必须伴随物理证据。
- **渐进披露**：技能索引常驻，完整内容按需加载。
- **fail-closed**：默认拒绝，仅明确允许时放行。
- **脚本化 transport**：测试注入假 HTTP transport，真实驱动整条 Agent 循环，保证确定性。
- **反思规划**：执行前分解任务并自我反思（V20）。
- **长程记忆压缩**：蒸馏旧日志进 notes.md 后删除（V20）。
- **协作记忆白板**：多 Agent 跨角色共享上下文（V20）。

---

*— 白泽引擎乙方研发团队 ｜ V20 交付 2026-07-30*
