---
name: Web-Harness-E2E
level: Industrial
domain: QA-Separation-of-Powers
---

# 🔱 技能：Web-Harness 验证隔离 (Separation of Powers)

本技能模仿 Anthropic 内部验证逻辑，将“生产”与“验收”权力进行物理解耦。

## 🪐 1. 权力制衡架构 (Verification Hierarchy)
- **生成的矛 (Generator Agent)**：根据 Spec 负责实现业务逻辑（Vue3 组件、Go API）。
- **核销的盾 (Evaluator Agent)**：
    - 不参与代码编写。
    - 负责编写基于 **Playwright** 的真实浏览器验证脚本。
    - 负责核销 UI 交互证据（截图/视频）。

## 🛡️ 2. 物理交付标准 (Definition of Done)
- **真实交互**：任何 UI 变更必须通过 `Evaluator` 执行一次“匿名用户交互探测”。
- **证据链**：在项目 `persistence/` 目录下产出对应的 `.webp` 交互证据。
- **Go 中间件验证**：强制执行 API 层的“恶意流量探测”，确证 Vue3 状态与 Go 后端状态的强一致性。

## 🧪 3. 驱动工具
- [**`Playwright`**](https://github.com/microsoft/playwright)
- `Matrix-Surgical-Probe` (引擎内置探测器)

---
*“Trust is synthesized through independent verification.”*
