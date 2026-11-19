<div align="center">

# 🏛️ 白泽引擎 (Baize Agent) — V39.0.0 Aegis

**零第三方运行依赖 · 强物理门禁 (`NO FAKE DONE`) · 8 域 53 模块的纯 Python 自治工程智能体运行时**

[![Version](https://img.shields.io/badge/version-V39.0.0--Aegis-orange?style=flat-square)](baize/__init__.py)
[![Tests](https://img.shields.io/badge/tests-1265%2F1268%20passed%20(99%25)-yellow?style=flat-square)](tests/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20third--party%20(stdlib%20only)-blue?style=flat-square)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

[**English**](README_EN.md) · [**5 分钟上手**](docs/START-HERE.md) · [**架构说明**](docs/architecture.md) · [**使用指南**](docs/USAGE_GUIDE.md) · [**教程系列**](docs/tutorials/README.md) · [**基准测试**](docs/benchmarks.md)

</div>

---

## 为什么是白泽引擎？

大多数 Agent 框架要么依赖几十个第三方包、动辄几百 MB 运行时，要么把「模型说做完了」当成「真的做完了」。

**Baize Agent V39 Aegis** 走极简硬核工程路线，只保留真正用于生产的 8 个核心域、53 个内聚模块：

- **零第三方运行依赖 (`dependencies = []`)**：100% Python 3.10+ 标准库实现（HTTP 连接池、SQLite 架构缓存、AST 符号图、TF-IDF 向量检索、MCP JSON-RPC 2.0、SSE 服务全部原生构建），由门禁 `scripts/gates/check_zero_deps.py` 强制守护。
- **NO FAKE DONE 物理门禁**：任何任务完成声称必须通过真实物理证据（编译、测试、文件哈希、契约检查）验证，并记录于只追加的 JSONL 运行账本（`RunLedger`）。
- **Fail-Closed 安全边界**：HTTP 写操作默认拒绝无鉴权请求（强制 `BAIZE_AUTH_TOKEN`），CORS 严格白名单，Shell 沙箱静态拦截危险命令，未实现路由诚实返回 `501 Not Implemented`。
- **静态代码库智能（6 个正交模块）**：基于 AST + 正则的多语言符号图（Python / TS / JS / Go / Rust / Java）、PageRank 排序、SQLite 增量缓存、分层 Repo Map 与爆炸半径 / 测试影响分析。
- **Director → Executor → Verifier 编排**：角色边界受控的多 Agent DAG，支持预算守卫、长程不变量锚定、会话分叉与 Hermes 轨迹技能蒸馏。
- **原生 Windows + 跨平台执行**：常驻 PowerShell 进程池、交互式提示检测、可选 Docker 沙箱与前端静态验证。

---

## 快速开始

### 1. 克隆并检查环境（无需安装任何 pip 运行依赖）

```bash
git clone https://github.com/jianjian12138/baize-agent.git
cd baize-agent
cp .env.example .env            # 填入你的 OpenAI / Anthropic / DeepSeek / Ollama 兼容 API Key
python -m baize doctor          # 检查运行时、配置与项目状态
```

### 2. 日常核心命令

```bash
python -m baize                 # 进入交互式终端 REPL
python -m baize run "为 auth 模块补齐边界单测并运行验证"
python -m baize team "重构支付状态机并验证回归测试"
python -m baize impact baize/core/agent.py --run   # 分析变更影响面并运行受影响测试
python -m baize blast run_gate                      # 计算符号调用爆炸半径
python -m baize serve --port 8765                   # 启动 HTTP / SSE 服务与仪表盘
python -m baize mcp                                 # 启动标准 JSON-RPC 2.0 MCP Server (stdio)
```

> 也可以通过 `pip install -e .` 安装 `baize` 命令入口；完整入门指南见 [`docs/START-HERE.md`](docs/START-HERE.md)。

---

## 核心架构（8 域 · 53 模块）

```text
  CLI / REPL / HTTP+SSE / Desktop / MCP          <- baize/interfaces/ & baize/ext/
                      │
                      ▼
  System-1 Guard ──▶ Director -> Executor -> Verifier DAG   <- baize/orchestration/
                      │                    │
         ┌────────────┴───────────┐        └───────────┐
         ▼                        ▼                    ▼
  Core Runtime              Codebase Intel        Execution & Sandbox
  (agent, llm, config,      (symbol_graph,        (tools, sandbox, proc,
   sessions, autonomy)       repo_map, impact,     powershell, docker)
                             arch_cache, search)
         │                        │                    │
         └────────────┬───────────┴────────────────────┘
                      ▼
       Knowledge (memory, graph, rag, skills)  +  Governance (gate, bench, mutation, doctor, obs)
```

| 领域包 | 模块数 | 职责说明 |
| :--- | :---: | :--- |
| **`baize/core/`** | 7 | Agent 主循环、多厂商 LLM 客户端（HTTP 连接池 + Prompt Cache）、配置/Schema/日志、会话持久化、自治策略与模式、插件与组件协议 |
| **`baize/orchestration/`** | 7 | Director→Executor→Verifier 编排器、项目契约/不变量锚定/Ralph 闭环、角色团队与子 Agent、System-1 快速路由、钩子、运行账本、自动化触发 |
| **`baize/execution/`** | 6 | 16 个内置工具 + Agent Rules + Tool SDK、Fail-Closed 沙箱、带交互检测的进程执行、Windows PowerShell 进程池、Docker 沙箱、前端校验 |
| **`baize/codebase/`** | 6 | 多语言符号图（PageRank）、SQLite 增量架构缓存、分层 Repo Map & AST 切片、爆炸半径与测试影响矩阵、零依赖工作区搜索、先验侦察 |
| **`baize/knowledge/`** | 6 | 分层情景/语义/团队记忆、知识图谱、TF-IDF 向量检索与 RAG、技能索引/目录/Hermes 蒸馏器、技能安全执行器、文档抓取 |
| **`baize/governance/`** | 5 | NO FAKE DONE 物理门禁与 Manifest 校验、真实基准套件、AST 变异测试与混沌注入、环境体检 `doctor`、Prometheus 指标与性能剖析 |
| **`baize/interfaces/`** | 9 | 29 个子命令 CLI、交互式 REPL、模块化 HTTP/SSE 服务（`server/` 4 模块）、桌面端 Studio、终端/Web UI 与配置向导 |
| **`baize/ext/`** | 7 | 标准 MCP 客户端/服务端/分发器（`mcp/` 5 模块）、聊天通道抽象、可观测性指标插件 |

完整文件树由门禁 `scripts/gates/check_arch_tree.py` 与 [`docs/architecture.md`](docs/architecture.md) 强一致校验。

---

## 仓库目录一览

```text
baize-agent/
├── baize/              # 核心运行包（8 个领域子包，53 个生产模块，0 扁平杂项）
├── tests/              # 10 域镜像测试套件（95 个测试文件）
├── scripts/
│   ├── gates/          # 工程门禁（零依赖、卫生、架构树、模块属性、端点诚实、真相校验、覆盖率）
│   └── tools/          # 辅助工具（上下文切片基准、API 连通探测）
├── assets/skills/      # 23 个内置结构化 SKILL.md 技能包
├── docs/               # 架构、教程、基准、快速开始、Desktop Studio 与协议文档
├── examples/           # 示例代码与 VS Code 伴侣插件（examples/vscode/）
├── install/            # 跨平台安装与桌面端启动脚本
├── projects/           # 本地项目隔离目录
├── AGENT.md            # 白泽引擎自治协作协议
├── baize.manifest.json # 工程交付证据清单
└── pyproject.toml      # 纯 stdlib 包声明（dependencies = []）
```

---

## 工程诚实性与验证门禁

任何提交都可通过以下物理门禁自证，无虚标、无隐藏脚本：

```bash
python scripts/gates/check_zero_deps.py         # 确认 baize/ 零第三方运行依赖
python scripts/gates/check_hygiene.py           # 确认仓库卫生、无残留垃圾、无未追踪引用
python scripts/gates/check_arch_tree.py         # 确认 docs/architecture.md 与文件系统 100% 一致
python scripts/gates/check_module_attrs.py      # 静态校验所有模块属性导入真实存在
python scripts/gates/check_endpoint_honesty.py  # 确认无伪造成功响应、未实现端点均诚实返回 501
python scripts/gates/sync_truth.py --check      # 校验版本号、徽章、教程与文档计数无漂移
python -m baize manifest validate baize.manifest.json
python -m baize bench                           # 运行 15 项本地端到端内核基准
pytest tests/                                   # 运行全量测试套件
```

---

## 历史里程碑标签

早期单文件与历史架构快照保留为只读 Git Tag，方便回溯演进轨迹：`v26.0.0-legacy`、`v33.0.0-legacy`。

## 贡献与协议

贡献规范与门禁要求请阅读 [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md)。本项目遵循 [MIT License](LICENSE)。
