# 教程 08 · 写一个 baize 组件（Write a baize Component）

> 前置：已读完 [01-认识白泽引擎](../tutorials/01-认识白泽引擎.md) 并跑通 [03-跑通你的第一个任务](../tutorials/03-跑通你的第一个任务.md)。
> 适用版本：V22 插件化架构（`baize.component` 组合内核），V23 继续沿用。零第三方依赖。

白泽 V22 吸收了 deepseek-harness（Cordis）「万物皆可插件」的思想，但**刻意不抄**它的三处安全弱点（默认松权限、第三方插件默认可信、执行模型生成的 JS）。白泽把每个核心单元（模型 / 工具 / 技能 / 会话 / 沙箱 / 循环 / 调度 / UI / 存储）都描述成一份**统一组件契约**，由 `CompositionKernel` 从配置装配。

本教程带你从零写一个可替换的组件，并注册生效——**不改 `agent.py` / `tools.py` / `serve.py` 的任何调用点**。

---

## 1. 组件到底是什么

一个「组件」就是一份元数据 + 一个工厂：

| 字段 | 含义 |
|---|---|
| `KIND` | 它替换哪一类核心单元（封闭枚举，见下） |
| `build(cfg)` | 工厂方法，返回满足对应 `Protocol` 的**实例** |
| （可选）`provides` / `requires` | 能力 id，用于拓扑依赖解析（fail-closed） |

`build` 返回的类型用 `Any` 标注，装配时再惰性解析——这是**刻意**的，用来消除循环导入。

### 9 类封闭 Kind（新增 kind 必须改代码，不为第三方开放）

```
model / tool / skill / session / sandbox / loop / scheduler / ui / storage
```

每一类都有一份 `Protocol` 契约（在 `baize/component.py` 里，形如 `SandboxProto`），装配后做**结构类型校验**：形状不对的坏实现会被拒绝，而不是悄悄出错。

### 两套隔离语义（这是白泽相对 harness 的关键修正）

| 来源 | 行为 | 失败时 |
|---|---|---|
| **显式覆盖**：你通过 `BAIZE_COMPONENTS` 指定替换某内置单元 | 高信任、你担责 | **整体 fail-closed，启动即阻断**（exit 非 0），绝不静默降级到内置 |
| **自动发现**：`plugin.py` 从 `baize/plugins/` + `BAIZE_PLUGINS_DIR` 扫描 | 低信任 | **记录日志 + 跳过**，host 不崩，**绝不默认可信** |

写自定义组件时，你通常用「显式覆盖」路径（可信、可控）；放进插件目录走「自动发现」路径时，则享受防御性隔离。

---

## 2. 最小可运行示例：给 sandbox 加审计日志

完整可运行文件见仓库 [`examples/logged_sandbox.py`](../../examples/logged_sandbox.py)。核心三步走：

```python
from baize.component import Component, CompositionKernel, Kind

class LoggedSandbox:
    KIND = Kind.SANDBOX          # ① 声明替换哪一类核心单元（也可用字符串 "sandbox"）

    def __init__(self, cfg=None):
        from baize import sandbox        # 惰性 import，避免循环导入
        self._inner = sandbox
        self._cfg = cfg

    def run(self, command, cwd=None, timeout=60, cfg=None):
        # ② 满足 SandboxProto：run(command, cwd, timeout, cfg) -> Any
        print(f"[LoggedSandbox] -> {command!r}")
        return self._inner.run(command, cwd=cwd, timeout=timeout, cfg=cfg or self._cfg)

    @classmethod
    def build(cls, cfg=None):
        # ③ 工厂入口：返回满足 Protocol 的实例
        return cls(cfg)
```

就这三件事：**声明 KIND → 方法签名符合协议 → 提供 build 工厂**。不需要继承任何基类，也不需要改白泽内核代码。

### 本地验证（无需改环境变量）

```bash
python examples/logged_sandbox.py
```

输出里会看到 `已装配的组件来源` 中 `sandbox` 一项变成了 `logged`，并且命令确实经由你的 `LoggedSandbox` 执行。

---

## 3. 注册生效：用 `BAIZE_COMPONENTS`

把上面的类放进**任意在 `PYTHONPATH` 上的包/模块**（例如你自己的项目包，或 `baize/plugins/` 目录），然后设置：

```bash
export BAIZE_COMPONENTS="your_package.logged_sandbox:LoggedSandbox"
# 多个覆盖用逗号分隔：BAIZE_COMPONENTS="a.b:Cls1, c.d:Cls2"
```

格式为 `"模块路径:类名"`，或仅写内置 kind 名（`model` / `sandbox` / ...）表示「保留该内置默认」。内核在启动时：

1. 加载全部内置默认组件；
2. 应用 `BAIZE_COMPONENTS` 覆盖（**最后应用，优先生效**）；
3. 拓扑解析依赖、循环检测（含显式组件成环 → fail-closed）；
4. 装配出 `Runtime` 单例，agent / serve / 工具统一从这里取用。

> **诚实约束**：`BAIZE_COMPONENTS` 的格式会被 `config_schema.validate()` 在启动前 fail-fast 校验；写错格式（如 `a.b:Cls,` 多逗号或非法字符）会直接报错，而不是悄然忽略。

你也可以不设置环境变量，而是在代码里手动注册（示例 `__main__` 用的就是这种，便于测试）：

```python
kernel = CompositionKernel({})
kernel.components[Kind.SANDBOX] = Component(
    Kind.SANDBOX, "logged", LoggedSandbox.build, explicit=True)
runtime = kernel.assemble()
```

---

## 4. 不同 kind 要满足什么协议

装配后每个实例都会被对应 `Protocol` 校验。常用签名速查（`baize/component.py`）：

| Kind | 必须提供的方法（结构校验） |
|---|---|
| `model` | `chat(messages, tools=None) -> dict`、`configured` 属性 |
| `tool` | `schemas() -> list[dict]`、`execute(name, arguments) -> str` |
| `skill` | `search(keyword) -> list[dict]`、`build_index(cfg=None)` |
| `session` | `append(message, kind="message")`、`list_sessions(cfg=None)`（classmethod） |
| `sandbox` | `run(command, cwd=None, timeout=60, cfg=None) -> Any` |
| `loop` | `run(agent, goal, extra_system="") -> Any` |
| `scheduler` | `tick() -> list[str]`、`next_due() -> float`、`start()` |
| `ui` | `event(kind, detail="")` |
| `storage` | `read_records`、`list_sessions`、`fork_session`、`compress_session`、`list_lineage` |

> `runtime_checkable` 协议只校验**方法是否存在**（结构校验），不校验参数类型。所以请自觉按上表签名实现，坏形状会在装配时被拒绝。

---

## 5. 一键自检：诚实门禁

V22 把「组件替换 + 模式切换」写进了诚实门禁。改完组件后跑：

```bash
python -m baize gate
```

它会在 `composition` 检查里**真实装配默认 runtime**、校验 9 类 `Protocol`、并验证 4 种命名模式（`coding` / `eval` / `autonomous` / `safe-review`）的 bundle；任一项失败整体 `overall` 即 `fail`。同时复测全量覆盖率（门槛 85%）。门禁不假绿——所有结论都有真实执行数据支撑。

---

## 6. 常见陷阱

- **循环导入**：组件文件**不要**在模块顶层 `from baize.agent import ...`。所有具体单元的 import 放进 `build()` / 方法里惰性导入（示例已示范）。
- **忘了 `KIND`**：`BAIZE_COMPONENTS` 加载时会报 `missing a KIND attribute`（fail-closed）。
- **协议形状不对**：方法名/存在性不符，显式覆盖会启动阻断，自动发现会被跳过——看日志即可定位。
- **误以为插件目录默认可信**：放进 `baize/plugins/` 的组件走「自动发现」路径，构建/类型失败只会被跳过，不会替你兜底。若要稳定替换，请用 `BAIZE_COMPONENTS` 显式覆盖。

---

## 7. 小结

写一个 baize 组件 = 「声明 `KIND` + 实现协议方法 + 提供 `build` 工厂」三步，再用 `BAIZE_COMPONENTS` 注册。内核负责装配、依赖解析、类型校验和隔离语义——你只关心自己的定制逻辑。这正是 V22 把「核心单元可组合」与「fail-closed 护城河」同时守住的方式。
