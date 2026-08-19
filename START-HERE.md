# START-HERE — 10 分钟上手白泽引擎 V24.0.0

## 你拿到的是什么

一套真实可运行的 Agent 研发操作系统：
**技能规约层**（文档 + 249 技能索引，被 AI 客户端加载或注入 Agent 提示词）
+ **baize Agent 运行时**（纯 Python 标准库：自主循环、多 Agent 编排、校验门禁、持久记忆）。

## 第 1 步：环境（2 分钟）

> 想一条命令搞定？直接跑 `python install/bootstrap.py`：它会自动准备 `.env`、跑 `doctor`，
> 且**若本机没有 Python ≥ 3.10，会自动安装（winget / Homebrew / apt-dnf-apk / python.org）后重启**——
> 裸机也能一键部署（与 hermes 一致）。不想自动装 Python 就加 `--no-auto-python`。

```bash
cp .env.example .env
# 打开 .env（SKILL_LIBRARY_PATHS 已默认指向仓库自带的 ./assets/skills，
#   新鲜克隆可直接通过 doctor，无需改动）：
#   如需运行自主 Agent，配置 BAIZE_MODEL_BASE_URL / BAIZE_MODEL_NAME / BAIZE_MODEL_API_KEY
python -m baize doctor        # 必须 RESULT: PASSED
```

doctor 会真实探测：Python 版本、核心目录、persistence 写权限、
每一个配置的技能库路径、git/node/go 工具链。任何 FAIL 都会给出修复指引。

## 第 2 步：技能索引（1 分钟）

```bash
python -m baize index build           # 扫描全部技能库（3 来源自动去重）
python -m baize index search 关键词   # 例如 tdd / vue / golang
```

## 第 3 步：跑通测试（1 分钟）

```bash
python -m pytest tests/     # 69 个真实测试，全部应通过
```

## 第 4 步：运行你的第一个 Agent（3 分钟，需模型端点）

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
