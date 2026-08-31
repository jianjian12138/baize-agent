# 📖 白泽智能体 (Baize Agent V36.0.0 Titan) 完整使用说明手册

> **白泽智能体 (Baize Agent)** 是一套面向 AI Agent 的**白盒工程化自主研发操作系统**：坚持**纯 Python 标准库构建（零第三方运行时依赖）**。以 **NO FAKE DONE** 物理门禁保证「绝不假绿」，原生支持 **Windows PowerShell 常驻 REPL (<5ms 极速响应)**、**AST 因果代码自愈**、**Asyncio Swarm 影子推演**、**5 大语言代码符号图谱** 与 **3 节点拜占庭博弈仲裁**。

---

## 目录
1. [系统环境要求与安装部署](#1-系统环境要求与安装部署)
2. [模型配置与多端点接入](#2-模型配置与多端点接入)
3. [命令行 CLI 与交互式 REPL 操作手册](#3-命令行-cli-与交互式-repl-操作手册)
4. [暗黑工业级桌面工作台 (Studio 11 大模块)](#4-暗黑工业级桌面工作台-studio-11-大模块)
5. [Windows & PowerShell 原生优化机制](#5-windows--powershell-原生优化机制)
6. [VS Code & Cursor 伴侣插件使用指南](#6-vs-code--cursor-伴侣插件使用指南)
7. [在 Antigravity 中作为技能或 MCP 挂载](#7-在-antigravity-中作为技能或-mcp-挂载)
8. [RESTful API 与 SSE 接口集成手册](#8-restful-api-与-sse-接口集成手册)
9. [常见问题排查与 FAQ](#9-常见问题排查与-faq)

---

## 1. 系统环境要求与安装部署

### 1.1 系统要求
- **操作系统**：Windows 10/11 (首选与深度优化)、Linux (Ubuntu 20.04+)、macOS (12+)
- **Python 版本**：Python **3.10** 及以上版本
- **外部依赖**：**零第三方运行时依赖（Pure Python Standard Library）**，开箱即用，免配复杂虚拟环境！

### 1.2 本地可编辑安装 (Editable Install)
在项目根目录下打开终端执行：
```powershell
# 1. 验证安装环境
python -m baize doctor

# 2. 以可编辑模式安装 CLI 全局命令
pip install -e .
```
安装后即可在系统的任意目录下直接调用 `baize` 命令！

---

## 2. 模型配置与多端点接入

白泽原生支持所有符合 OpenAI 兼容标准的模型端点、DeepSeek 官方 API 以及本地离线 Ollama 模型。

### 2.1 配置文件 `.env`
在项目根目录创建或编辑 `.env` 文件：

```ini
# ========== 1. 基础模型配置 (默认推荐 DeepSeek) ==========
BAIZE_MODEL_PROVIDER=openai_compatible
BAIZE_MODEL_BASE_URL=https://api.deepseek.com
BAIZE_MODEL_NAME=deepseek-chat
BAIZE_MODEL_API_KEY=sk-your-actual-api-key-here

# ========== 2. 备选配置示例: 本地离线 Ollama ==========
# BAIZE_MODEL_BASE_URL=http://localhost:11434/v1
# BAIZE_MODEL_NAME=qwen2.5-coder:latest
# BAIZE_MODEL_API_KEY=ollama

# ========== 3. 备选配置示例: 官方 OpenAI GPT-4o ==========
# BAIZE_MODEL_BASE_URL=https://api.openai.com/v1
# BAIZE_MODEL_NAME=gpt-4o
# BAIZE_MODEL_API_KEY=sk-proj-...

# ========== 4. 系统运行行为控制 ==========
BAIZE_AUTONOMY_LEVEL=2                  # 1=只读安全, 2=默认拦截高危, 3=全自主运行
BAIZE_WINDOWS_POWERSHELL_FIRST=true     # 强制开启 Windows 原生 PowerShell 极速引擎
BAIZE_AGENT_MAX_STEPS=30                # 单个自主任务最大迭代步数
```

---

## 3. 命令行 CLI 与交互式 REPL 操作手册

白泽提供了强大且符合人体工学的命令行工具集：

```
baize [SUBCOMMAND] [OPTIONS]
```

### 3.1 常用核心命令表

| 命令 | 用途与说明 | 典型使用示例 |
| :--- | :--- | :--- |
| `baize doctor` | 运行系统健康体检，验证 Python、PowerShell 执行策略与编码 | `baize doctor` |
| `baize run "<goal>"` | 启动单任务全自主执行（自动思考 ➔ 编码 ➔ 测试 ➔ 自愈） | `baize run "为用户认证模块编写严格单元测试"` |
| `baize repl` | 启动持续交互式终端（支持多行粘贴、时空回溯与模型热切） | `baize repl` |
| `baize serve` | 启动本地 RESTful API 服务与沉浸式桌面 Studio Web 界面 | `baize serve --port 8787` |
| `baize sessions` | 列出或审查历史执行会话轨迹与耗时谱系 | `baize sessions` 或 `baize sessions <id>` |
| `baize index` | 构建并搜索工作区代码符号图谱与 260+ 技能库 | `baize index search "tdd"` |
| `baize gate` | 运行物理防伪门禁核验（NO FAKE DONE 真实凭据检查） | `baize gate` |

### 3.2 交互式 REPL 专属快捷指令 (Slash Commands)
在运行 `baize repl` 时，支持以下高频斜杠指令：
- **`@file <path>`**：向上下文直接注入指定代码文件内容；
- **`/model <name>`**：会话过程中无缝热切换底层推理大模型；
- **`/fork`**：从当前状态分叉出新的时间线分支，进行假设性探索；
- **`/rewind <step>`**：时空回溯，撤销最近 N 步不合理的修改；
- **`/trace`**：以毫秒级瀑布流打印当前会话的每一个 Span 执行延迟。

---

## 4. 暗黑工业级桌面工作台 (Studio 11 大模块)

运行 `baize serve --port 8787`，在浏览器打开 **`http://127.0.0.1:8787`** 即可进入拥有 11 大模块的 Obsidian 暗黑工业级工作台：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🏛️ 白泽桌面 Studio (Universal Studio V36.0.0 Titan)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. 💬 流式对话 (SSE Live Chat)     │ 7. 🧠 分层记忆与混合 RAG (Memory & RAG) │
│ 2. 📝 Monaco 差异对比与 Hunk 合并 │ 8. 🌐 Anthropic MCP 协议工具连接器      │
│ 3. 🗺️ 多任务协同 DAG 控制台      │ 9. 🧬 达尔文元工具自繁衍企业市场        │
│ 4. 🌲 跨会话 Git-Graph 谱系树    │ 10. 🧪 系统体检与混沌抗脆弱演练台       │
│ 5. 🔍 5大语言代码符号依赖图谱     │ 11. 🛡️ 安全权限与自主度滑块 (L1~L3)     │
│ 6. 📚 技能中心 (260+ Matt Pocock)│                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 核心模块亮点：
1. **Monaco 差异对比与 Hunk 细粒度采纳**：支持针对大文件修改单键 Cherry-Pick 采纳单个代码块；
2. **多语言符号依赖图谱**：跨文件毫秒级检索 Python、TypeScript、Rust、Go、Java 中的接口、类与函数调用链；
3. **达尔文元工具企业市场**：智能体自合成的工具附带加密 `DARWIN-***` 基因签名，跨团队一键挂载；
4. **拜占庭共识演练台**：红队注入边界算子，蓝队沙箱验证，法官全票签署 `BFT-SIG-***` 防伪门禁。

---

## 5. Windows & PowerShell 原生优化机制

白泽针对 Windows 开发者进行了深度底层重构，彻底解决主流 Agent 在 Windows 下的各种水土不服：

1. **常驻 PowerShell REPL 进程池 (`PersistentPowerShellSession`)**：
   - 避免每次执行命令重复启动 200ms 的冷启动等待，执行延迟降至 **< 5ms**；
   - 会话级别的环境变量（`$env:KEY="VAL"`）与工作目录（`cd ...`）自动跨指令保留。
2. **15+ 种 POSIX 复合流式管道模拟垫片**：
   - 自动无感转译 `cat`, `ls -la`, `rm -rf`, `export`, `which`, `touch`, `mkdir -p`；
   - 深度模拟 Unix 复杂管道：`awk '{print $1}'` ➔ `ForEach-Object split`，`wc -l` ➔ `Measure-Object`，`sort -u` ➔ `Sort-Object -Unique`。
3. **终端交互式 CLI 提示词自动嗅探防挂死 (`detect_interactive_prompt`)**：
   - 实时拦截 `[y/N]`, `Password:`, `npm init` 等输入提示，自动注入安全应答，彻底消除 60 秒死等超时。
4. **全链路强制 UTF-8 编码与子进程树清理**：
   - 注入 `[Console]::OutputEncoding = UTF-8`，根治 Windows 中文控制台乱码；
   - 发生超时或中止时调用 `taskkill /F /T` 连同所有子进程一并清理，杜绝端口被僵尸进程占用。

---

## 6. VS Code & Cursor 伴侣插件使用指南

白泽提供了开箱即用的 IDE 伴侣插件（`extensions/vscode`）：

### 6.1 快捷键定义
- **`Ctrl+Shift+B`**：一键在 VS Code 侧边栏唤醒白泽 Studio 控制台；
- **`Ctrl+K`**：在编辑器中选中任意代码片段，弹出白泽 AST 就地重构浮窗！

### 6.2 安装方式
1. 在 VS Code 中打开本仓库根目录；
2. 打开 `extensions/vscode` 目录并在终端执行 `npm install && npm run compile`；
3. 按 `F5` 即可在新的扩展开发宿主窗口中实时使用伴侣插件！

---

## 7. 在 Antigravity 中作为技能或 MCP 挂载

### 方式一：作为标准 MCP Server 挂载（最推荐）
在 Antigravity 的 `.agents/mcp_config.json` 中添加配置：
```json
{
  "mcpServers": {
    "baize": {
      "command": "python",
      "args": ["-m", "baize.serve", "--port", "8787"],
      "description": "白泽工业级 AI 研发智能体（AST 因果自愈、PowerShell 引擎与代码符号图谱）"
    }
  }
}
```

### 方式二：注册为工作区自定义 Skill
在 `.agents/skills/baize-agent/SKILL.md` 中引用白泽命令，Antigravity 对话中即可直接调度白泽因果自愈能力！

---

## 8. RESTful API 与 SSE 接口集成手册

白泽内置轻量非阻塞 HTTP 服务器，提供工业级 API 接口：

| HTTP 端点 | 方法 | 功能描述 | 请求参数示例 / 响应格式 |
| :--- | :---: | :--- | :--- |
| `/health` | `GET` | 探针健康状态与当前版本 | 返回 `{"status":"ok","version":"36.0.0"}` |
| `/run` | `POST` | 阻塞式执行自主任务 | `{"goal": "重构工具层"}` ➔ 返回执行结果与轨迹 |
| `/run/stream` | `POST` | SSE 实时流式执行推送 | `{"goal": "分析代码"}` ➔ 推送 `data: {"type":"step", ...}` |
| `/api/mcp/tools` | `GET` | 列出所有已注册的 MCP 工具 | 返回标准 JSON-RPC 2.0 Schema 工具清单 |
| `/api/mcp/call` | `POST` | 调用指定 MCP 工具 | `{"server":"sqlite","tool":"query","arguments":{...}}` |
| `/api/symbol/search` | `GET` | 跨文件检索代码符号 | `/api/symbol/search?q=UserService` |
| `/api/swarm/speculate` | `POST` | 触发 Swarm 影子推演 | `{"goal":"优化并发安全"}` ➔ 3条分支并发推演结果 |
| `/api/byzantine/arbitrate` | `POST` | 触发拜占庭多方共识仲裁 | `{"code":"...","goal":"发布评审"}` ➔ 仲裁签名 |

---

## 9. 常见问题排查与 FAQ

#### Q1: 运行 `baize doctor` 提示 `PowerShell ExecutionPolicy` 受限怎么办？
> **答**：白泽内部在执行子进程时已自动注入 `-ExecutionPolicy Bypass` 沙箱参数，通常不影响 Agent 运行。如需为当前用户放开权限，可在管理员 PowerShell 窗口执行：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

#### Q2: 为什么大模型调用报 `401 Unauthorized`？
> **答**：请检查根目录下的 `.env` 文件，确认 `BAIZE_MODEL_API_KEY` 是否已填写真实的有效密钥，且 `BAIZE_MODEL_BASE_URL` 地址与模型名称正确匹配。

#### Q3: 如何清空历史会话与缓存？
> **答**：会话数据存储在 `persistence/sessions/` 目录下，直接删除该目录下的 `.jsonl` 文件即可清空历史。

---

## 📜 开源协议
白泽智能体基于 **MIT License** 开放源代码。欢迎全球开发者共同参与共建与贡献！
