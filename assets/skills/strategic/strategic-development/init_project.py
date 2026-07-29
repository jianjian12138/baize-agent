#!/usr/bin/env python3
"""
Strategic Development 项目初始化脚本
用法: python3 init_project.py --key REQ-001 --title "需求标题"
"""

import os
import json
import argparse
from datetime import datetime
from pathlib import Path

# 模板文件映射
TEMPLATES = {
    "00-需求总览.md": "00-需求总览.md",
    "功能名-需求文档.md": "{title}-需求文档.md",
    "功能名-技术方案.md": "{title}-技术方案.md",
    "功能名-任务分解.md": "{title}-任务分解.md",
    "功能名-验证报告.md": "{title}-验证报告.md",
    "功能名-验收报告.md": "{title}-验收报告.md",
}

MANIFEST = {
    "request_key": "",
    "title": "",
    "type": "new-feature",
    "priority": "P1",
    "status": "draft",
    "created_at": "",
    "updated_at": "",
    "platforms": [],
    "owner": "",
    "assignee": "",
    "due_date": "",
    "milestones": {
        "requirement": "",
        "design": "",
        "development": "",
        "testing": ""
    }
}

def get_template_content(template_name: str) -> str:
    """读取模板文件内容"""
    template_dir = Path(__file__).parent / "templates"
    template_file = template_dir / template_name
    
    if not template_file.exists():
        print(f"Warning: Template {template_name} not found, skipping")
        return ""
    
    with open(template_file, "r", encoding="utf-8") as f:
        return f.read()

def copy_template(src: Path, dst: Path, replacements: dict):
    """复制并替换模板内容"""
    if not src.exists():
        return
    
    content = src.read_text(encoding="utf-8")
    
    for key, value in replacements.items():
        content = content.replace(f"{{{key}}}", value)
    
    # 清理未替换的占位符
    import re
    content = re.sub(r'\{[^}]+\}', '', content)
    
    dst.write_text(content, encoding="utf-8")
    print(f"Created: {dst}")

def init_project(args):
    """初始化项目"""
    # 替换值
    replacements = {
        "request_key": args.key,
        "title": args.title,
        "type": args.type,
        "priority": args.priority,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    
    # 创建目录
    base_dir = Path(args.workspace or "workspace")
    request_dir = base_dir / "requests" / args.key
    
    if request_dir.exists() and not args.force:
        print(f"Error: Directory {request_dir} already exists. Use --force to overwrite.")
        return
    
    request_dir.mkdir(parents=True, exist_ok=True)
    (request_dir / "logs").mkdir(exist_ok=True)
    
    # 复制模板
    template_dir = Path(__file__).parent / "templates"
    
    for template_name, output_name in TEMPLATES.items():
        src = template_dir / template_name
        dst_name = output_name.format(title=args.title)
        dst = request_dir / dst_name
        
        if src.exists():
            copy_template(src, dst, replacements)
    
    # 生成 manifest.json
    manifest = MANIFEST.copy()
    manifest["request_key"] = args.key
    manifest["title"] = args.title
    manifest["type"] = args.type
    manifest["priority"] = args.priority
    manifest["created_at"] = replacements["created_at"]
    manifest["updated_at"] = replacements["created_at"]
    
    manifest_path = request_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Created: {manifest_path}")
    
    print(f"\nProject initialized at: {request_dir}")
    print(f"\nNext steps:")
    print(f"1. Edit manifest.json")
    print(f"2. Fill in 00-需求总览.md")
    print(f"3. Start requirement analysis")

def main():
    parser = argparse.ArgumentParser(description="Strategic Development 项目初始化")
    parser.add_argument("--key", required=True, help="需求编号，如 REQ-001")
    parser.add_argument("--title", required=True, help="需求标题")
    parser.add_argument("--type", default="new-feature", choices=["new-feature", "change-request", "bugfix", "ui-optimization"], help="需求类型")
    parser.add_argument("--priority", default="P1", choices=["P0", "P1", "P2", "P3"], help="优先级")
    parser.add_argument("--workspace", default="workspace", help="工作目录")
    parser.add_argument("--force", action="store_true", help="强制覆盖已存在的目录")
    
    args = parser.parse_args()
    init_project(args)

if __name__ == "__main__":
    main()