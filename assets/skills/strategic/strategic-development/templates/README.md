# Strategic Development 项目初始化脚本

## 使用方式

### 方式1：复制整个目录

```bash
# 复制到新项目
cp -r /path/to/strategic-development <新项目目录>/

# 重命名
mv strategic-development/templates <新项目目录>/templates
```

### 方式2：使用 Python 脚本快速初始化

```bash
python3 init_project.py --key REQ-001 --title "用户登录功能"
```

## 脚本功能

1. 创建需求目录结构
2. 复制模板文件
3. 替换占位符
4. 生成 manifest.json

## 命令行参数

| 参数 | 说明 | 示例 |
|------|------|------|
| --key | 需求编号 | REQ-001 |
| --title | 需求标题 | 用户登录功能 |
| --type | 需求类型 | new-feature |
| --priority | 优先级 | P1 |

## 示例

```bash
# 创建新需求
python3 init_project.py --key REQ-001 --title "用户登录功能" --type new-feature --priority P0

# 创建Bug修复
python3 init_project.py --key BUG-001 --title "登录页闪退" --type bugfix --priority P0
```

## 输出结构

```
workspace/requests/REQ-001/
├── 00-需求总览.md
├── manifest.json
├── 用户登录功能-需求文档.md
├── 用户登录功能-技术方案.md
├── 用户登录功能-任务分解.md
├── 用户登录功能-验证报告.md
├── 用户登录功能-验收报告.md
└── logs/
```