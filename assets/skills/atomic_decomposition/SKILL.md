---
name: Atomic-Decomposition-Ralph
level: Industrial
domain: Task-Entropy-Control
---

# 🔱 技能：纳秒级任务原子拆解 (Atomic Decomposition)

本技能借鉴 `snarktank/ralph` 范式，通过强力解构复杂 PRD，实现研制路径的单点突破与极致可控。

## 🪐 1. 拆解核心：任务状态机 (prd.json State Machine)
- **核心载体**：[**`projects/[name]/task_decomposition.json`**](file:///d:/gogogo/projects/)。
- **拆解准则**：
    - 每一个任务项必须是一个 **“可独立验证、且研发耗时不超过 5 分钟”** 的原子故事。
    - 严禁出现“实现项目所有后端”等模糊项。必须细化至“实现 System/Login 接口及其对应的 Postgres DAO”。
- **任务状态**：`passes: false | true`。

## 🛡️ 2. ralph 封闭循环规约 (The Ralph Loop)
1. **任务拾取**：在每一次 `Edit` 动作开启前，系统自动从 `task_decomposition.json` 选中最高优先级的 `False` 项。
2. **手术实施**：白泽进入“原子沉浸模式”，只修改与该任务物理相关的代码。
3. **物理核销**：
    - 只有当 `Evaluation-Agent` (Web-Harness) 产出绿色证据后，方可由人工/系统将状态置为 `True`。
    - **严禁提前核销**。
4. **进度对齐**：同步更新 `task.md` 看板，确证主公获取全局态势。

## 🧪 3. 产出物对齐
- **`任务分解.md`**：作为本 JSON 状态机的可读化快照，供主公审查。

---
*“Complexity is defeated by the relentless execution of the obvious.”*
