# 白泽智能桌面工作台 (Baize Agent Desktop Studio)

> **设计标杆**：[Hermes-CN-Desktop](https://github.com/Eynzof/Hermes-CN-Desktop) & Codex Desktop  
> **设计哲学**：白盒透明、极轻量零依赖、Windows 原生沉浸式体验。

---

## 1. 核心亮点

- **零依赖原生窗口**：支持 `pywebview` 原生窗口或 Edge/Chrome 独立 App 模式（`--app=http://127.0.0.1:8787`），无需打包笨重 Chromium，启动秒级、内存极省。
- **9 大专业级 Agent 治理模块**：
  1. **智能结对工作台 (Workbench)**：流式对话、Markdown 代码高亮、LaTeX 公式渲染、`<thinking>` 抽屉式 CoT、折叠式工具卡片、`patch_file` 差量 Diff 高亮、`@file` 文件上下文注入。
  2. **会话与分支时间旅行 (Archive)**：全量 JSONL 会话时间轴检索、一键 Fork 平行实验分支、Rewind 状态回退。
  3. **多 Agent DAG 并行调度 (Team Console)**：Director → Executor → Verifier 任务依赖图谱与执行状态脉冲、Trace 毫秒级瀑布流。
  4. **技能自进化中心 (Skills Hub)**：240+ 技能卡片、在线编辑与校验 `SKILL.md`、`SkillHarvester` 提炼新技能一键入库。
  5. **分层记忆面板 (Memory Studio)**：事实/决策/教训三层记忆卡片、BM25 + TF-IDF 倒数排名融合（RRF）在线检索测试台。
  6. **大模型服务商中心 (Model Hub)**：云端服务商预设（DeepSeek, OpenAI, Claude, 硅基流动）+ 本地 Ollama / LM Studio 自动探测与延迟测速。
  7. **系统体检与实时日志 (Doctor & Logs)**：`baize doctor` 仪表盘、多等级日志实时流与过滤。
  8. **安全与自主度控制 (Security & Autonomy)**：Read-Only / Supervised / YOLO Mode 三档自主度滑块与 Deny-list 规则编辑器。
  9. **平台生态集成 (Integrations)**：飞书 / 钉钉机器人 Webhook 桥接。

---

## 2. 启动方式

### 方式 1：CLI 命令
```bash
python -m baize desktop
```

### 方式 2：Windows 一键双击
直接双击运行仓库中的：
- `install/baize-desktop.bat` 或 `install/baize-desktop.ps1`
