# baize-tools 规格说明

## 概述

工具注册表与沙箱：工具是「原语」而非固化功能（pi 哲学），以 JSON schema 注册，
运行时可扩展；文件操作限制在工作区内，shell 命令经 deny-list 门禁（fail-closed）。

## 接口

- `ToolRegistry.register(name, description, parameters, fn)`
- `ToolRegistry.schemas() -> list[dict]`：OpenAI tools 数组。
- `ToolRegistry.execute(name, arguments) -> str`：永远返回字符串观察值，不抛异常。
- `default_registry() -> ToolRegistry`：注册 9 个内置工具
  （read_file / write_file / list_dir / bash / search_skills / load_skill /
  memory_recall / memory_log / save_skill）。
- `command_allowed(command) -> (bool, reason)`
- 配置项：`BAIZE_WORKSPACE_DIR` / `BAIZE_ALLOW_OUTSIDE_WORKSPACE`。

## 行为规约

1. 执行未注册工具返回 `ERROR: unknown tool ...` 观察值，不崩溃。
2. 工具函数抛出的任何异常被捕获并转为 `ERROR: ...` 观察值（观察值哲学：错误也是信息）。
3. 文件工具路径解析后必须位于 `BAIZE_WORKSPACE_DIR` 内，越界抛 `PermissionError`
   （被 execute 转为 ERROR 观察值）；`BAIZE_ALLOW_OUTSIDE_WORKSPACE=1` 时放行。
4. bash 命令先过 deny-list（rm -rf 根/盘符、format、mkfs、shutdown、dd 等），
   命中即拒绝执行并说明命中的模式。
5. bash 执行有超时（默认 60s），超时返回 ERROR 观察值；输出截断至 8000 字符。
6. `save_skill` 将技能写入 `assets/skills/learned/<safe-name>/SKILL.md`
   （frontmatter 含 origin: agent-learned）并立即重建索引，使其可被检索。
7. `read_file` 超长文件截断并注明剩余行数；`list_dir` 最多列 200 项。

## 边界与异常

- 工具参数与 schema 不符时返回 `ERROR: bad arguments`。
- 相对路径相对于工作区根解析。

## 测试映射

| 规约 | 测试 |
|------|------|
| 1, 2 | `tests/test_tools.py`（unknown tool / 异常转观察值） |
| 3 | `tests/test_tools.py`（沙箱越界拒绝与放行开关） |
| 4, 5 | `tests/test_tools.py`（deny-list 拦截 / bash 真实执行） |
| 6 | `tests/test_tools.py`（save_skill 落盘并可检索） |
