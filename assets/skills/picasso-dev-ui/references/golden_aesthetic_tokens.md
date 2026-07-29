# 黄金审美：Luxury 质感视觉规格 (Golden Aesthetic Tokens)

> [!NOTE]
> **审美主权**：本设计资产旨在消灭“廉价感”。所有组件必须优先引用以下物理参数，确证 UI 的极致谐振。

## 1. 核心色系 (Core Palette)

| 用途 | 变量名/值 | 效果说明 |
|:---|:---|:---|
| **主权色** | `--brand-primary: #1a1a1a;` | 指向绝对深度。 |
| **高光红** | `--status-promo: linear-gradient(135deg, #ff4d4f, #ff7875);` | 具备工业感的热量。 |
| **背景银** | `--bg-faint: #f5f5f7;` | 仿 Apple 铝合金质感背景。 |

---

## 2. 玻璃拟态指纹 (Glassmorphism)

所有浮层、弹窗必须执行以下规格：
```css
.luxury-glass {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(18px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.07);
}
```

---

## 3. 响应式阻尼 (Responsive Damping)

PC/H5 交互必须模拟真实物理惯性：
- **Transition**: `all 0.4s cubic-bezier(0.16, 1, 0.3, 1)` (Quart 曲线)。
- **Hover Scale**: `1.02` (极小幅放大，确证优雅)。

---
*Matrix Aesthetic / Sovereign UI / Quality Protocol*
