# Baize Agent (白泽引擎) — 零依赖工业级自主研发操作系统 · V36.0.0 Titan

<div align="center">

<img src="assets/hero_banner.png" alt="Baize Agent Hero Banner" width="100%" />

<br/>

[![Version](https://img.shields.io/badge/version-V36.0.0--Titan-orange?style=for-the-badge)](https://github.com/jianjian12138/baize-agent)
[![Tests](https://img.shields.io/badge/tests-53%2F53%20passed%20(100%25)-brightgreen?style=for-the-badge)](https://github.com/jianjian12138/baize-agent)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Runtime Deps](https://img.shields.io/badge/runtime%20deps-0%20(pure%20stdlib)-blueviolet?style=for-the-badge)](https://github.com/jianjian12138/baize-agent)
[![Windows Native](https://img.shields.io/badge/windows-native%20powershell%20repl-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/jianjian12138/baize-agent)
[![MCP](https://img.shields.io/badge/Anthropic%20MCP-JSON--RPC%202.0-D97706?style=for-the-badge)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](https://opensource.org/licenses/MIT)

<br/>

**[ [中文文档](README.md) | [English README](README_EN.md) | [完整使用手册](docs/USAGE_GUIDE.md) | [中文极速上手](docs/QUICKSTART_CN.md) | [English Quickstart](docs/QUICKSTART_EN.md) ]**

<br/>

</div>

> **白泽智能体 (Baize Agent)** 是一套面向 AI Agent 的**白盒工程化自主研发操作系统**：坚持**纯 Python 标准库构建（零第三方运行时依赖）**。以 **NO FAKE DONE** 物理门禁保证「绝不假绿」，深度原生适配 **Windows PowerShell 常驻 REPL (<5ms 极速响应)**、**AST 因果代码自愈**、**Asyncio Swarm 影子推演**、**5大语言代码符号图谱** 与 **3 节点拜占庭博弈仲裁**。

---

## 📸 10 秒自主编码全流程动态演示

<div align="center">
<img src="assets/demo_showcase.gif" alt="Baize Agent 终端自愈与拜占庭共识演示" width="92%" />
</div>

---

## 🌟 核心差异化特性（Why Baize?）

| 核心特性 | 解决的传统痛点 | 白泽的工业级解决方案 |
| :--- | :--- | :--- |
| **🪟 Windows 原生第一等公民** | 主流 Agent 在 Win 下 CMD 语法崩溃、GBK 乱码、200ms 冷启动延迟。 | **常驻 PowerShell REPL 进程池 (<5ms 延迟)** + 15+ POSIX 复合管道模拟 (`awk`, `wc -l`, `sort -u`) + 全链路 UTF-8 隔离。 |
| **🛡️ NO FAKE DONE 真实物理防伪** | 传统 Agent 易产生“我已修复但实际未跑通测试”的幻觉。 | 强制物理运行凭证 + AST 变异测试网 (100% 击杀率) + 3 节点拜占庭博弈全票加密签名 (`BFT-SIG-***`)。 |
| **🌲 多语言代码符号依赖图谱** | 无法精准跨文件理解大型代码库调用关系。 | 原生支持 **Python、TypeScript/JS、Rust、Go、Java** 5 大语言符号索引与调用链追踪。 |
| **🧠 AST 语义级上下文剪枝** | 大型代码库上下文占用过高导致 Token 浪费与幻觉。 | 智能将非关键函数体剪枝为 `...` 类型存根，**大模型 Token 消耗直降 50% ~ 70%**。 |
| **⚡ Asyncio Swarm 并发影子推演** | 传统串行试错生成极慢。 | 3 条独立策略路线在 **Git Worktree 独立物理沙箱**中并发推演，毫秒级选举最优时间线。 |
| **🔌 官方标准 Anthropic MCP 协议** | 各家 Agent 工具生态碎片化。 | 标准 **JSON-RPC 2.0 MCP 客户端**，一键连通全球开源 SQLite, GitHub, Puppeteer 工具生态。 |
| **🖥️ 暗黑工业级桌面工作台 (Studio)** | 开发者需在多个终端与网页间频繁切换。 | 内置 11 大核心功能模块（流式对话、Monaco Diff、DAG 控制台、代码图谱、达尔文工具市场、因果自愈）。 |

---

## 📊 与业界主流框架全方位对比

| 对比维度 | **白泽智能体 (Baize V36 Titan)** | Claude Code / Cursor | AutoGPT / OpenDevin | LangChain / CrewAI |
| :--- | :---: | :---: | :---: | :---: |
| **运行时第三方依赖** | **0（纯 Python 标准库）** | 较重 (Node/C++) | 较重 (多层 Python 库) | 100+ Pip 依赖包 |
| **Windows 原生 PowerShell 池 (<5ms)** | **✅ 原生第一等公民支持** | ⚠️ 基础支持 / POSIX | ⚠️ 仅限 WSL/Docker | ❌ 无 |
| **AST 因果自愈与变异测试网** | **✅ 内置 (100% 变异捕获)** | ❌ 无 | ❌ 无 | ❌ 无 |
| **NO FAKE DONE 物理防伪门禁** | **✅ 加密水印物理签名** | ⚠️ 软性提示词约束 | ⚠️ 软性提示词约束 | ❌ 无 |
| **官方 Anthropic MCP 协议** | **✅ 标准 JSON-RPC 2.0** | 部分支持 | 部分支持 | ⚠️ 自定义封装 |
| **多语言代码符号依赖图谱** | **✅ Python/TS/Rust/Go/Java** | 偏向 TS/C++ | 偏向 Python | ❌ 无 |
| **Swarm 物理隔离影子推演** | **✅ Git Worktree 物理隔离** | ❌ 无 | ❌ 无 | ❌ 无 |
| **3 节点拜占庭共识安全仲裁** | **✅ 红队攻防 vs 蓝队防御** | ❌ 无 | ❌ 无 | ❌ 无 |

---

## ⚡ 1 分钟极速上手

### 1. 环境自检门禁
```bash
python -m baize doctor
```

### 2. 命令行自主执行与交互式 REPL
```bash
# 单任务直接自主执行
python -m baize run "为数据持久化层编写严格的单元测试并跑通"

# 进入持续交互式 REPL 终端（支持 @file 上下文注入与多行粘贴）
python -m baize repl
```

### 3. 唤起暗黑工业级桌面 Studio 工作台
```bash
python -m baize serve --port 8787
```
打开浏览器访问 **`http://127.0.0.1:8787`**，或在 Windows 下双击 `install/baize-desktop.bat` 即可直接进入具备 11 大核心模块的沉浸式桌面客户端！

---

## 🗺️ 架构拓扑图

```
                  ┌────────────────────────────────────────────────────────┐
                  │         白泽桌面 Universal Studio (11 大核心功能模块)    │
                  │   Monaco Diff · 可视化 DAG · 多语言图谱 · MCP 开放连接器 │
                  └──────────────────────────┬─────────────────────────────┘
                                             │ HTTP / SSE 流式推送
                  ┌──────────────────────────▼─────────────────────────────┐
                  │                 白泽工业级核心研发引擎                  │
                  ├──────────────────────────┬─────────────────────────────┤
                  │ ⚡ Asyncio Swarm 并发引擎 │  🌲 多语言代码符号图谱      │
                  │ (Git Worktree 物理沙箱)  │  (Python/TS/Rust/Go/Java)   │
                  ├──────────────────────────┼─────────────────────────────┤
                  │ 🧠 AST 语义上下文剪枝器  │  🛡️ 3 节点拜占庭博弈演练台   │
                  │ (Token 消耗直降 50%-70%) │  (红队攻防 / 蓝队防御全票共识) │
                  ├──────────────────────────┼─────────────────────────────┤
                  │ 🪟 常驻 PowerShell 进程池 │  🔌 官方标准 Anthropic MCP   │
                  │ (<5ms 延迟 + 复合管道垫片)│  (JSON-RPC 2.0 开放工具生态) │
                  └──────────────────────────┴─────────────────────────────┘
```

---

## 📜 开源许可证
基于 [MIT 许可证](LICENSE) 开源。代码坚持纯 Python 标准库构建，确保极高的审计安全性、轻量化与高移植性。
