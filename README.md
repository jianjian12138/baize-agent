<div align="center">

# 🏛️ 白泽引擎 (Baize Agent) — V49.0.0 Zenith

**零第三方运行依赖 · 强物理门禁 (`NO FAKE DONE`) · 8 域 58 模块的工业级纯 Python 自治工程运行时**

[![Version](https://img.shields.io/badge/version-V49.0.0--Zenith-orange?style=flat-square)](baize/__init__.py)
[![Tests](https://img.shields.io/badge/tests-1376%2F1376%20passed%20(100%25)-brightgreen?style=flat-square)](tests/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20third--party%20(stdlib%20only)-blue?style=flat-square)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

[**English**](README_EN.md) · [**5 分钟上手**](docs/START-HERE.md) · [**架构说明**](docs/architecture.md) · [**使用指南**](docs/USAGE_GUIDE.md) · [**教程系列**](docs/tutorials/README.md) · [**基准测试**](docs/benchmarks.md)

</div>

---

## 为什么是白泽引擎？

**Baize Agent V49 Zenith** 走极简硬核工程路线，以 **0 第三方运行依赖（纯 Python 3.10+ 标准库）** 构建完整的工业级自主研发闭环：

- **内核提速与原子事务回滚**：端到端 Token 级流式响应（REPL & HTTP SSE）、只读工具并发批处理（写操作严格串行）、基于临时 Git 索引的非侵入式检查点（`GitCheckpointManager`）与失败自动/一键回滚（`baize rollback`）。
- **分级强隔离沙箱**：默认本地加固（静态护栏 + Landlock/Seatbelt + POSIX `rlimit` CPU/FD 配额 + 敏感环境变量清洗），支持 `BAIZE_SANDBOX_MODE=docker|auto` 一键切换无网络/限核/限 PID 的 Docker 容器隔离（`docker` 模式严格 Fail-Closed）。
- **零依赖 LSP 诊断桥与写后即查**：内置纯标准库 stdio JSON-RPC 2.0 LSP 客户端与多语言编译器/语法检查链（`baize diagnose`），每次 `write_file`/`patch_file` 自动触发即时诊断并回喂模型。
- **可量化真实编码评测闭环**：内置多文件真实工程评测集（`baize eval`），支持 `oracle` 确定性 CI 验证与 `live` 真实大模型评测，持久化 JSONL 记分卡并支持跨版本回归对比（`--compare`）。
- **生产化持久化异步服务**：基于 SQLite WAL 的持久化任务队列（`POST /api/jobs`、崩溃自动恢复、协作取消、SSE 进度流）、滑动窗口限流（`429`）、真实 `/team/dag` 编排与带检查点保护的 `/api/git/apply_hunk`。
- **NO FAKE DONE 物理门禁与静态代码库智能**：多语言符号图（PageRank）、SQLite 增量缓存、分层 Repo Map、爆炸半径与测试影响矩阵，全部由可执行门禁强制守护。

---

## 快速开始

```bash
git clone https://github.com/jianjian12138/baize-agent.git
cd baize-agent
cp .env.example .env            # 配置 OpenAI / Anthropic / DeepSeek / Ollama 兼容 API Key
python -m baize doctor          # 检查运行时、配置与分级沙箱隔离态势
```

### 日常核心命令

```bash
python -m baize                                   # 进入实时流式终端 REPL
python -m baize run "为 auth 模块补齐边界单测并验证"
python -m baize team "重构支付状态机并运行回归测试"
python -m baize diagnose baize/core/agent.py      # 运行即时编译器 / LSP 诊断
python -m baize eval --mode oracle                # 运行多文件编码评测闭环（--mode live 接真实模型）
python -m baize rollback --list                   # 查看或回滚 Git 事务检查点
python -m baize impact baize/core/agent.py --run  # 计算变更影响面并运行受影响测试
python -m baize serve --port 8765                 # 启动持久化 HTTP/SSE 服务与异步任务队列
python -m baize mcp                               # 启动标准 JSON-RPC 2.0 MCP Server (stdio)
```

---

## 核心架构（8 域 · 58 模块）

| 领域包 | 模块数 | 职责说明 |
| :--- | :---: | :--- |
| **`baize/core/`** | 7 | 流式 + 只读并发 Agent 主循环、多厂商 LLM 客户端（连接池 + Prompt Cache + 流式工具增量解析）、配置/Schema/日志、会话、自治策略、插件协议 |
| **`baize/orchestration/`** | 7 | Director→Executor→Verifier 编排器、契约/不变量/Ralph 闭环、角色团队与子 Agent、System-1 快速路由、钩子、运行账本、自动化触发 |
| **`baize/execution/`** | 7 | 17 个默认内置工具 + Tool SDK、分级强隔离沙箱（Landlock/Seatbelt + `rlimit` + 环境变量清洗 + Docker）、Git 原子检查点、进程超时、PowerShell 进程池、前端校验 |
| **`baize/codebase/`** | 7 | 零依赖 stdio LSP/编译器诊断桥、多语言符号图（PageRank）、SQLite 增量架构缓存、分层 Repo Map & AST 切片、爆炸半径与测试影响矩阵、工作区搜索、先验侦察 |
| **`baize/knowledge/`** | 6 | 分层情景/语义/团队记忆、知识图谱、TF-IDF 向量检索与 RAG、技能索引/目录/Hermes 蒸馏器、技能执行器、文档抓取 |
| **`baize/governance/`** | 6 | NO FAKE DONE 物理门禁与清单校验、15 项内核基准、真实多文件编码评测闭环（`eval_harness`）、AST 变异与混沌注入、`doctor`、Prometheus 指标 |
| **`baize/interfaces/`** | 11 | 32 个子命令 CLI、流式 REPL、模块化 HTTP/SSE 服务与 SQLite WAL 持久化异步任务队列（`server/` 6 模块）、桌面端 Studio、终端/Web UI |
| **`baize/ext/`** | 7 | 标准 MCP 客户端/服务端/分发器（`mcp/` 5 模块）、聊天通道抽象、可观测性指标插件 |

完整文件树由门禁 `scripts/gates/check_arch_tree.py` 与 [`docs/architecture.md`](docs/architecture.md) 强一致校验。

---

## 验证门禁

```bash
python scripts/gates/check_zero_deps.py         # 确认 baize/ 零第三方运行依赖
python scripts/gates/check_hygiene.py           # 确认仓库卫生、无残留垃圾、无未追踪引用
python scripts/gates/check_arch_tree.py         # 确认 docs/architecture.md 与文件系统 100% 一致
python scripts/gates/check_module_attrs.py      # 静态校验所有模块属性导入真实存在
python scripts/gates/check_endpoint_honesty.py  # 确认零伪造响应、零 501 占位、已下线历史路由诚实返回 410 Gone
python scripts/gates/sync_truth.py --check      # 校验版本号、徽章、教程与文档计数无漂移
python -m baize manifest validate baize.manifest.json
python -m baize bench                           # 运行 15 项本地内核基准
python -m baize eval --mode oracle              # 验证多文件编码评测闭环
pytest tests/                                   # 运行全量测试套件
```

---

## 历史里程碑标签

早期单文件与历史架构快照保留为只读 Git Tag：`v26.0.0-legacy`、`v33.0.0-legacy`。

## 贡献与协议

贡献规范与门禁要求请阅读 [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md)。本项目遵循 [MIT License](LICENSE)。
