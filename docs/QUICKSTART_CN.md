# ⚡ 白泽智能体 (Baize Agent) 中文极速上手指南

欢迎使用 **白泽智能体 (Baize Agent V36.0.0 Titan)** —— 纯 Python 标准库构建、零第三方运行时依赖的工业级自主研发操作系统！

---

## 🎯 1 分钟极速上手三步法

### 1. 环境自检门禁（确保环境健康）
在项目根目录下运行环境诊断医生：
```bash
python -m baize doctor
```
> **提示**：诊断医生会自动检查 Python 版本（>=3.10）、PowerShell 执行策略与 UTF-8 编码环境。

---

### 2. 交互式命令行运行（CLI & REPL）
让白泽自主执行一个开发或测试任务：
```bash
# 单任务直接自主执行
python -m baize run "为用户认证模块编写严格的单元测试并跑通"

# 进入持续交互式 REPL 终端（支持 @file 上下文注入与多行粘贴）
python -m baize repl
```

---

### 3. 唤起暗黑工业级桌面 Studio 工作台
```bash
# 启动 Web 服务与 REST API (端口 8787)
python -m baize serve --port 8787
```
打开浏览器访问 **`http://127.0.0.1:8787`**，或在 Windows 下双击 `install/baize-desktop.bat` 即可直接进入具备 11 大核心模块的沉浸式桌面客户端！

---

## ⚙️ 模型配置指南 (`.env`)

在根目录下创建 `.env` 文件（或复制 `.env.example`）：
```ini
# 模型接口配置（支持 DeepSeek / OpenAI / Claude / Ollama 等任意兼容端点）
BAIZE_MODEL_PROVIDER=openai_compatible
BAIZE_MODEL_BASE_URL=https://api.deepseek.com
BAIZE_MODEL_NAME=deepseek-chat
BAIZE_MODEL_API_KEY=sk-your-api-key-here

# Windows 原生 PowerShell 优化 (默认开启)
BAIZE_WINDOWS_POWERSHELL_FIRST=true
```

---

## 🔌 进阶生态集成

### 1. VS Code & Cursor 伴侣插件
- 在 VS Code 中打开本仓库，加载 `extensions/vscode`；
- 使用快捷键 **`Ctrl+Shift+B`** 一键唤醒白泽 Studio；
- 选中代码按 **`Ctrl+K`** 触发 AST 就地重构！

### 2. 作为 Antigravity 官方技能 / MCP Server
- 工作区技能：将本目录挂载为 Antigravity Skill；
- 标准 MCP：在 `.agents/mcp_config.json` 中配置 `python -m baize.serve --port 8787` 即可直连白泽工具箱！
