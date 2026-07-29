---
name: karpathy-surgical-coding
description: 卡帕西外科手术式编码——最小 diff、澄清优先、奥卡姆剃刀。适用于任何代码变更场景，要求变更纯净、无关代码零改动、每处变更可验证。
level: Advanced
domain: Logic-Precision
---

# 技能：卡帕西外科手术式编码 (Karpathy Surgical Coding)

本技能源于 Andrej Karpathy 的 Agent 开发哲学，追求代码变更的极致纯净度与逻辑透明度。

## 1. 核心规约 (The Code Mantras)
- **澄清本位 (Clarification First)**：在需求模糊时严禁假设。必须列出备选方案（Options）与用户确认。
- **奥卡姆剃刀 (Occam's Razor)**：优先选择最简、无依赖、易于测试的实现路径。
- **Git 纯净化 (Minimal Diff Side-effects)**：
    - 严禁修改无关代码行。
    - 严禁调整不相关的缩进或空格。
    - 严禁修改无关的注释或文档。

## 🛡️ 2. Go 语言适配准则 (Go Engineering Standard)
- **接口单一职责**：保持 struct 与 interface 的简洁，不引入多余的复杂抽象。
- **并发安全性**：每当使用 `go routine` 或 `channel` 时，必须物理证明其关闭逻辑。
- **错误透明**：强制使用 `fmt.Errorf("context: %w", err)` 保持错误链的完整性。

## 🧪 3. 验证锚点
- **Diff 核销**：变更完成后，必须自审计 `git diff`，确证无冗余字符波动。
- **逻辑闭环**：每一处变更必须在 `task.md` 中有对应的原子验证项。

---
*“Precision is the final sovereignty over hallucination.”*
