# 🛡️ 主权追溯与证据链规约 (Traceability Sovereignty)

> [!IMPORTANT]
> **主权精髓**：本规约定义了白泽系统在执行复杂工程任务时的 **“确定性底座”**。它要求每一行代码、每一个决策都必须具备物理血统証明，物理终结“无主代码”与“逻辑碎片”。

---

## 1. 物理血统证明 (Logical Lineage)

所有的研发变更必须通过 **[指纹追溯]** 锚定到前序阶段的规划产物。

### A. 编码追溯 (Surgical Trace)
- **要求**：在执行 P6 (手术级编码) 时，每一个逻辑修改块必须在日志或注释中注明其来源。
- **正例**：`// Ref: TASK-04.1 [PromoPrice Calculation Logic]`
- **目标**：实现从“生产代码”到“任务拆解”的秒级物理回溯。

### B. 决策证据 (Decision Evidence)
- **要求**：在 P2 (技术方案) 如果调整了需求定义的边界，必须并在 [**`manifest.json`**](file:///d:/gogogo/projects/simple-shopping-platform/manifest.json) 中记录变更指纹。

---

## 2. 阶段性门禁核销 (Phase-Gate Discipline)

严禁在未完成前序确认的情况下进入下一阶段。

| 阶段转换 | 准入证 (Access Card) | 核销标准 |
| :--- | :--- | :--- |
| **P1 -> P2** | [需求模型 MD5] | 0 占位符分析完成。 |
| **P4 -> P6** | [任务清单 UUID] | 拆解颗粒度达到 RALPH 标准，且 manifest 锁定。 |
| **P6 -> P9** | [编译/自测日志] | 0 影子运行，0 占位符代码。 |

---

## 3. 证据核销矩阵 (Evidence Matrix)

每一个子任务完成时，必须产出对应的物理证据：
1. **[DOC]**：更新后的 .md 路径。
2. **[LOG]**：带有业务 TraceID 的控制台输出。
3. **[IMG]**：带有 UI 组件指纹的截图。

---
*Matrix V17.58: 步步为营。主权可证。白泽确定性指引。*
