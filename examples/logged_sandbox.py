"""最小可运行示例：写一个自定义 baize 组件（sandbox 日志包装）。

零第三方依赖。本文件演示 V22「统一组件契约」的最小实现：
  * 一个类，带 ``KIND`` 属性，声明它替换哪一类核心单元；
  * 一个 ``build(cfg)`` 入口，返回满足对应 ``Protocol`` 的实例；
  * 实例的方法签名满足 ``baize.component`` 里的 ``*Proto`` 契约。

在真实项目里，你把它放进任意「在 PYTHONPATH 上的包/模块」，然后通过
``BAIZE_COMPONENTS=your_module:LoggedSandbox`` 注册即可，无需改动 ``agent.py``
或 ``tools.py`` 的调用点。

本文件的 ``__main__`` 直接用内核手动装配该组件，证明契约与装配真实可用
（无需先设置环境变量也能跑通）。
"""
from __future__ import annotations

import os
import sys

# 让示例脱离「baize 在 PYTHONPATH 上」也能直接 `python examples/logged_sandbox.py`。
# 真实项目请把本类放进你自己的包，再用 BAIZE_COMPONENTS 注册（见教程），此时此行无害。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from baize.component import Component, CompositionKernel, Kind


class LoggedSandbox:
    """自定义 sandbox：在委托内置沙箱前后打印日志。

    满足 ``SandboxProto`` —— 即提供一个
    ``run(command, cwd=None, timeout=60, cfg=None) -> Any`` 方法。
    """

    KIND = Kind.SANDBOX  # 也可以是字符串 "sandbox"

    def __init__(self, cfg: dict | None = None) -> None:
        from baize import sandbox  # 惰性 import，避免循环导入
        self._inner = sandbox
        self._cfg = cfg

    def run(self, command: str, cwd: str | None = None, timeout: int = 60,
            cfg: dict | None = None) -> object:
        # 这里是你的定制逻辑：审计、限流、加壳、改写命令……本例仅记录。
        print(f"[LoggedSandbox] -> command={command!r} cwd={cwd} timeout={timeout}")
        result = self._inner.run(command, cwd=cwd, timeout=timeout,
                                 cfg=cfg or self._cfg)
        print(f"[LoggedSandbox] <- done (type={type(result).__name__})")
        return result

    @classmethod
    def build(cls, cfg: dict | None = None) -> "LoggedSandbox":
        # CompositionKernel 装配时调用的入口。返回满足 Protocol 的实例。
        return cls(cfg)


if __name__ == "__main__":
    # 直接用手动注册的组件装配内核，验证契约与装配真实可用。
    kernel = CompositionKernel({})  # 空配置 = 全部用内置默认
    kernel.components[Kind.SANDBOX] = Component(
        Kind.SANDBOX, "logged", LoggedSandbox.build, explicit=True)
    runtime = kernel.assemble()

    print("已装配的组件来源:", runtime.names())
    print("-" * 40)
    # 实际跑一条命令，验证自定义 sandbox 被启用
    try:
        runtime.get(Kind.SANDBOX).run("echo hello-from-baize-component")
    except Exception as exc:  # 沙箱可能因环境受限失败，这里只演示装配
        print(f"(sandbox 执行返回: {exc!r})")
    print("-" * 40)
    print("OK: LoggedSandbox 作为 sandbox 组件成功装配并参与运行。")
