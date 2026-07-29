# Strategic Development 配套资源

本文档说明使用 `strategic-development` skill 开发复杂项目时需要的配套配置。

## 目录结构

推荐将以下目录结构复制到项目根目录：

```
project/
├── skills/                      # 技能目录
│   ├── strategic-development/  # 主skill
│   └── maozx/                  # 毛泽东思想skills
│       ├── maozx-main-contradiction/
│       ├── maozx-practice-first/
│       ├── maozx-long-war/
│       ├── maozx-mass-line/
│       └── ...（其他maozx skills）
├── templates/                  # 文档模板
│   ├── 00-需求总览.md
│   ├── 功能名-需求文档.md
│   ├── 功能名-技术方案.md
│   ├── 功能名-任务分解.md
│   ├── 功能名-验证报告.md
│   ├── 功能名-验收报告.md
│   └── manifest.json
├── workspace/                  # 工作目录
│   └── requests/              # 需求目录
└── .env                       # 环境配置（可选）
```

## 快速初始化

### 方式1：手动创建

```bash
# 1. 复制 skills 目录
cp -r /path/to/strategic-development skills/

# 2. 创建模板和目录
mkdir -p templates workspace/requests

# 3. 复制模板文件
cp templates/* templates/
```

### 方式2：使用脚本

```bash
# 创建项目结构
python3 << 'EOF'
import os
import json

templates = {
    "00-需求总览.md": """# {project_name} - 需求总览

## 基本信息
- **需求编号**: {request_key}
- **需求名称**: {title}
- **创建时间**: {created_at}
- **优先级**: {priority}

## 需求概述
简要描述此需求要解决的问题和目标。

## 背景
说明需求的来源和业务背景。

## 目标
- 目标1
- 目标2

## 非目标（不做的事情）
明确排除的范围，避免 scope creep。
""",
    "manifest.json": json.dumps({
        "request_key": "",
        "title": "",
        "type": "new-feature",
        "priority": "P1",
        "status": "draft",
        "created_at": "",
        "platforms": [],
        "owner": ""
    }, indent=2, ensure_ascii=False)
}

for name, content in templates.items():
    with open(f"templates/{name}", "w", encoding="utf-8") as f:
        f.write(content)

os.makedirs("workspace/requests", exist_ok=True)
print("Project initialized!")
EOF
```

## 配套 Skills 调用

使用 `sessions_spawn` 调用各执行 agent：

| 阶段 | Agent cwd | 说明 |
|------|-----------|------|
| 需求分析 | `D:\workspace\agents\product_manager` | 生成需求文档 |
| 技术方案 | `D:\workspace\agents\architect` | 架构设计 |
| 编码实现 | `D:\workspace\agents\backend-dev` | 后端开发 |
| 前端开发 | `D:\workspace\agents\frontend-dev` | 前端开发 |
| 测试验证 | `D:\workspace\agents\test_engineer` | 测试执行 |
| 验收确认 | `D:\workspace\agents\qa_engineer` | QA验收 |

## 环境检查清单

开始项目前确认以下环境就绪：

- [ ] 代码仓库权限
- [ ] 开发环境可用（IDE、编译工具、数据库）
- [ ] 测试账号权限
- [ ] 必要的 API Key/Token
- [ ] 文档协作工具（如飞书/Confluence）

## 执行流程

```
1. 创建需求目录
   └── workspace/requests/<request-key>/

2. 战略层分析
   ├── 抓主要矛盾（maozx-main-contradiction）
   └── 实践检验（maozx-practice-first）

3. 需求分析
   └── 产出 00-需求总览.md + 需求文档.md

4. 技术方案
   └── 产出 技术方案.md

5. 任务分解
   └── 产出 任务分解.md（粒度30-60min）

6. 编码实现
   └── 按任务执行编码

7. 验证测试
   ├── 代码审查
   └── 测试验证

8. 验收
   └── QA/产品验收
```

## 常见问题

### Q: 如何判断用哪个 maozx skill？
A: 
- 多任务并行不知道优先哪个 → 抓主要矛盾
- 需求不确定想验证方向 → 实践检验
- 项目周期长团队疲劳 → 持久战
- 各方意见分歧 → 群众路线/统一战线
- 遇到挫折需要反思 → 批评与自我批评

### Q: 没有配套 agents 怎么办？
A: 可以直接用 `sessions_spawn` 启动通用 subagent，或手动执行各阶段任务

### Q: 模板可以自定义吗？
A: 可以，根据项目特点调整 templates/ 目录下的模板内容