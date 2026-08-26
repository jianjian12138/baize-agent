---
name: Memory-Layer-autoDream
level: System
domain: Memory-Governance
---

# 🔱 技能：autoDream 记忆层级管理 (Memory Governance)

本技能旨在治理 Matrix 引擎在长周期项目中的记忆膨胀与熵增，保持响应指令的纳秒级纯净度。

## 🪐 1. 四层记忆模型 (Four-Tier Memory)
- **层级 1 (Prefs)**：个人偏好（编码风格、常用技术栈）。持久化至 `IDENTITY.md`。
- **层级 2 (Project)**：项目规约（目录结构、专有接口）。持久化至项目本地 `docs/`。
- **层级 3 (Team)**：团队共识（评审标准、交付门禁）。持久化至 `assets/skills/`。
- **层级 4 (Temp)**：临时笔记（会话上下文、临时 TODO）。存放在 `persistence/working_memory/`，定期清理。

## 🛡️ 2. autoDream 协议规约 (Maintenance Protocol)
- **知识蒸馏**：项目里程碑达成后，自动将层级 4 的有价值经验萃取为层级 2/3 的技能包。
- **梦境清理 (Pruning)**：
    - 删除已完成且无复用价值的临时 Task 记录。
    - 压缩冗余的报错排查路径，转为“错误预防 Skill”。
    - 将相对时间引用转换为绝对物理时间。

## 🧪 3. 运行依据
- [**`persistence/EVOLUTION_AUDIT.md`**](file:///d:/gogogo/persistence/EVOLUTION_AUDIT.md)

---
*“Clean memory is the fuel for clear logic.”*
