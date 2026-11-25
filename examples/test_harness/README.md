# Baize Reusable Test Harness（可复用确定性测试底座）

一套**零第三方依赖、开箱即用、可无缝接入真实业务**的现代 **Test Harness（测试挽具）** 参考实现。

不同于传统重型测试框架或测试平台，它专注于 4 件高确定性工作：
1. **环境适配器（`core/env.py`）**：支持 `external`（已部署测试/预发 URL）、`command`（自动拉起本地服务并分配空闲端口与独立 DB）、`compose`（编排 `docker-compose.yml` 依赖栈并自动销毁）。
2. **协议原生驱动（`core/drivers.py`）**：薄 HTTP 驱动（自动抄录请求响应 + `$.a.b` 变量提取 + 并发压测）+ HTML/ARIA 语义与前端 JS 契约校验。
3. **确定性预言机（`core/oracles.py`）**：状态码/JSON 契约/延迟预算断言、SQLite 业务不变量 SQL 校验、服务端零 Traceback/500 日志预言机，以及自定义 Python 业务钩子（`module:func`）。
4. **人机共用证据包（`runner.py` & `mcp_server.py`）**：统一退出码（`0=通过`、`1=业务断言失败`、`2=环境故障`）、结构化 JSON 证据包（`.artifacts/latest_report.json`）、CI/CD 标准 **JUnit XML**（`--junit`），以及零依赖 **Streamable HTTP MCP Server**（直接对接 Baize 或任意 AI Agent）。

---

## 一、1 分钟开箱体验（内置 Demo 被测服务）

无需安装任何第三方依赖，直接运行内置的 FlashCart 样板服务（API + SQLite 事务库存 + Web 前端）全部 6 个确定性场景：

```bash
python3 examples/test_harness/runner.py --suite all
```

导出机器可读 JSON 或 CI/CD 标准 JUnit XML：

```bash
python3 examples/test_harness/runner.py --suite all --json --junit .artifacts/junit.xml
```

---

## 二、3 步接入你的真实业务系统

### 第 1 步：复制配置模板
将 `real_service.config.example.json` 复制到你的业务仓库（如 `my-service.harness.json`），按实际部署形态选择一种 `target.mode`：

- **模式 A：直连已有测试/预发环境（最常用）**
  ```json
  "target": {
    "mode": "external",
    "base_url": "${TEST_BASE_URL:-http://127.0.0.1:8080}",
    "health_path": "/health"
  }
  ```
- **模式 B：自动拉起本地服务进程（本地开发/CI 隔离跑）**
  ```json
  "target": {
    "mode": "command",
    "start_cmd": ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "{port}"],
    "cwd": "/path/to/your-service",
    "health_path": "/health"
  }
  ```
- **模式 C：编排 Docker Compose 多服务栈（DB + Redis + 被测服务）**
  ```json
  "target": {
    "mode": "compose",
    "compose_file": "docker-compose.test.yml",
    "base_url": "http://127.0.0.1:8080",
    "wait_ports": [5432, 6379, 8080],
    "health_path": "/health"
  }
  ```

> **密钥安全**：所有鉴权 Header 均支持 `${ENV_VAR:-default}` 环境变量展开，切勿在 JSON 中硬编码 Token。

### 第 2 步：编写你的业务场景与不变量
在配置中的 `scenarios`（或独立的 `scenarios_file`）中声明核心业务链路，支持 5 类步骤：
- `http`：发送请求，通过 `save: {"order_id": "$.order.id"}` 提取变量，后续用 `{{order_id}}`、`{{uuid}}` 串联；支持 `status`、`json_equals`、`json_exists`、`json_min_length`、`text_contains`、`header_contains`、`max_latency_ms`。
- `concurrent_http`：并发压测并精确校验状态码分布（如防超卖 `{"201": 5, "409": 3}`）。
- `ui_contract`：校验页面 ARIA 无障碍语义标记与前端 JS 语法/逻辑契约。
- `sql_invariant`：对本地 SQLite 执行确定性 SQL 不变量校验（`expect_zero_rows` / `expect_scalar`）。
- `oracle_hook`：挂接任意自定义 Python 校验函数（`"my_oracles:check_ledger_balance"`），可对接 Postgres / Redis / MQ 等任意真实业务中间件。

### 第 3 步：执行测试（命令行 / CI / Baize Agent）

1. **命令行 / CI/CD**：
   ```bash
   TEST_BASE_URL=https://staging.example.com TEST_API_TOKEN=xxx      python3 examples/test_harness/runner.py        --config my-service.harness.json        --suite all        --junit .artifacts/junit.xml
   ```
   也可以用 `--base-url` 临时覆盖目标地址，用 `--suite smoke` 或 `--scenario S01_...` 定向跑子集。

2. **接入 Baize Agent（MCP + Skill + 权限护栏）**：
   - 将 `baize_templates/permissions.json` 复制到业务仓库 `.baize/permissions.json`；
   - 将 `baize_templates/SKILL.md` 复制到业务仓库 `.baize/skills/test-harness/SKILL.md`；
   - 启动 Streamable HTTP MCP 服务供 Baize 直接调用：
     ```bash
     python3 examples/test_harness/mcp_server.py        --config my-service.harness.json        --port 8790
     ```
     Baize 连接 `http://127.0.0.1:8790/mcp` 后自动获得 `run_harness`、`list_scenarios` 工具、`evidence://latest` 资源与 `triage_harness_failure` 排障 Prompt。
