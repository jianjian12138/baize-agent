# START-HERE — 10 分钟上手白泽引擎 V33.0.0

## 你拿到的是什么

一套真实可运行的 Agent 研发操作系统：
**技能规约层**（文档 + 249+ 技能索引，被 AI 客户端加载或注入 Agent 提示词）
+ **baize Agent 运行时**（纯 Python 标准库：持续交互 REPL 终端、自主循环、多 Agent 编排、校验门禁、持久记忆、差量补丁、代码沙箱、链路追踪）。

## 第 1 步：一键环境部署（1 分钟）

> 想要一行命令搞定？直接运行：
> - **Linux / macOS / WSL**：`curl -fsSL https://raw.githubusercontent.com/jianjian12138/baize-agent/main/install/install.sh | bash`
> - **Windows PowerShell**：`irm https://raw.githubusercontent.com/jianjian12138/baize-agent/main/install/install.ps1 | iex`
> - **或本地执行**：`python install/bootstrap.py`

```bash
cp .env.example .env
# 打开 .env：
#   如需运行自主 Agent，配置 BAIZE_MODEL_BASE_URL / BAIZE_MODEL_NAME / BAIZE_MODEL_API_KEY
python -m baize doctor        # 必须 RESULT: PASSED
```

doctor 会真实探测：Python 版本、核心目录、persistence 写权限、
每一个配置的技能库路径、git/node/go 工具链。任何 FAIL 都会给出修复指引。

## 第 2 步：技能索引（1 分钟）

```bash
python -m baize index build           # 扫描全部技能库（3 来源自动去重）
python -m baize index search tdd      # 例如 tdd / vue / golang
```

## 第 3 步：跑通测试（1 分钟）

```bash
python -m pytest tests/ -q            # 593 个真实测试，全部通过
```

## 第 4 步：体验极致交互式终端（3 分钟，推荐）

```bash
# 启动行业领先的连续交互 REPL 终端
python -m baize

# 交互终端内直接使用斜线命令：
# > /help       - 查看完整命令列表
# > /trace      - 可视化查看步骤时间线与 Span 工具执行耗时
# > /cost       - 实时查看 Token 消耗与计费仪表盘
# > /model deepseek-reasoner - 秒级热切换活跃模型
# > /fork       - 平行分叉出新的实验分支
# > /rewind 1   - 时间旅行回退 1 轮会话
# > /paste      - 进入多行长代码粘贴模式
#
# 高级特性：
# > baize-agent > 帮我重构 @baize/agent.py:10-30 中的方法  (@直接注入文件上下文)
# > baize-agent > """粘贴多行代码"""                       (三引号多行块)
```

## 第 5 步：CLI 单次执行与多 Agent 团队

```bash
# 单 Agent 自主执行（思考→工具→观察循环，JSONL 会话持久化）
python -m baize run "列出 projects 目录下的项目并总结各自技术栈"

# 多 Agent 团队（Director 规划 → Executor 执行 → Verifier 独立核验）
python -m baize team "为 simple-shopping-platform 写一份部署检查清单"

# 会话管理：中断/崩溃后可续跑
python -m baize sessions              # 列出会话
python -m baize run "继续" --resume <session_id>
```

未配置模型端点时，`run`/`team` 会明确拒绝启动（exit 2）并提示所需变量——不会假装运行。

## 第 5 步：开始一个项目（3 分钟）

1. 在 `projects/<你的项目>/` 创建 `manifest.json`（12 个 phase，参照
   `projects/simple-shopping-platform/manifest.json`）。
2. 按 `SKILL.md` 的 P1–P12 推进；每完成一个阶段，把证据文件路径写入
   evidence 并执行 `python -m baize manifest validate <path>`。
3. 会话结束前：`python -m baize memory log "今天做了什么"`。

## 常见问题

| 问题 | 处理 |
|------|------|
| doctor 报技能库 FAIL | 检查 .env 中 SKILL_LIBRARY_PATHS 路径是否存在 |
| run/team 提示 not configured | 在 .env 配置 BAIZE_MODEL_BASE_URL / BAIZE_MODEL_NAME |
| manifest INVALID: NO FAKE DONE | 该 phase 没列证据或证据文件不存在——补齐真实产物 |
| Agent 写文件被拒绝 | 沙箱默认限制在 BAIZE_WORKSPACE_DIR 内，属预期防护 |
| 想看历史工作记录 | `python -m baize memory recall <关键词>` 或 `baize sessions` |
| legacy/ 是什么 | V17 归档（含模拟通过的旧代码），只读参考，勿引用 |
