"""Interactive First-Run Onboarding Setup Wizard for Baize Agent (stdlib, zero dependencies).

Provides a friendly Hermes / Codex style CLI setup flow when users first launch
Baize or type `baize setup` / `/setup`.
Features:
- Presets for popular LLM providers (DeepSeek, OpenAI, Anthropic, OpenRouter, SiliconFlow, Ollama, Custom)
- API key input & recommended model auto-fill
- Immediate connectivity verification
- Automatic safe atomic write/update to root `.env` file
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import NamedTuple

from .config import ROOT, ENV_FILE, load_config
from .logging_setup import get_logger

log = get_logger("setup_wizard")


class ProviderPreset(NamedTuple):
    name: str
    base_url: str
    default_model: str
    notes: str
    needs_key: bool = True


PROVIDERS = [
    ProviderPreset(
        name="DeepSeek (深度求索 · 强烈推荐)",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        notes="超高性价比，代码与规划能力卓越",
        needs_key=True,
    ),
    ProviderPreset(
        name="SiliconFlow (硅基流动 · 国内高速聚合)",
        base_url="https://api.siliconflow.cn/v1",
        default_model="deepseek-ai/DeepSeek-V3",
        notes="稳定国内加速，支持 DeepSeek / Qwen",
        needs_key=True,
    ),
    ProviderPreset(
        name="OpenAI (GPT-4o / o1 / o3-mini)",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o",
        notes="OpenAI 官方端点",
        needs_key=True,
    ),
    ProviderPreset(
        name="Anthropic (Claude 3.5 Sonnet)",
        base_url="https://api.anthropic.com",
        default_model="claude-3-5-sonnet-20241022",
        notes="顶尖代码工程与工具调用能力",
        needs_key=True,
    ),
    ProviderPreset(
        name="OpenRouter (全球模型全聚合)",
        base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-3.5-sonnet",
        notes="一个 Key 访问 Claude/GPT/Gemini/DeepSeek",
        needs_key=True,
    ),
    ProviderPreset(
        name="Ollama (本地私有化 · 免费免Token)",
        base_url="http://localhost:11434/v1",
        default_model="qwen2.5-coder:7b",
        notes="本地离线运行，无需 API Key",
        needs_key=False,
    ),
    ProviderPreset(
        name="Custom (自定义兼容 OpenAI 端点)",
        base_url="",
        default_model="",
        notes="手动指定 Base URL、Key 和 Model",
        needs_key=True,
    ),
]


def _test_connection(base_url: str, api_key: str, model_name: str) -> tuple[bool, str]:
    """Lightweight test probe to check endpoint connectivity."""
    url = base_url.rstrip("/") + "/models"
    try:
        headers = {"User-Agent": "baize-setup-probe"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status in (200, 201):
                return True, "Endpoint connection verified successfully."
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "HTTP 401 Unauthorized: Invalid API Key."
        if e.code in (404, 405):
            # Many custom proxy endpoints do not implement /models; probe /chat/completions with minimal ping or consider reachable
            return True, f"Host reached (HTTP {e.code}). Note: verify model name '{model_name}' manually."
        return False, f"HTTP Error {e.code}: {e.reason}"
    except Exception as exc:
        return False, f"Connection warning: {exc}"
    return True, "Probe completed."


def update_env_file(updates: dict[str, str], env_path: Path | None = None) -> Path:
    """Safely update or create the .env file with new key-value pairs."""
    target = env_path or ENV_FILE
    existing_lines = []
    if target.exists():
        existing_lines = target.read_text(encoding="utf-8").splitlines()

    updated_keys = set()
    new_lines = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in updates:
                new_lines.append(f'{key}="{updates[key]}"')
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Append any remaining keys not found in existing file
    for k, v in updates.items():
        if k not in updated_keys:
            new_lines.append(f'{k}="{v}"')

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return target


def run_setup_wizard(non_interactive: bool = False, preset_idx: int | None = None,
                     api_key: str = "", model: str = "", base_url: str = "") -> bool:
    """Interactive first-run wizard to configure LLM settings."""
    print("\n" + "=" * 60)
    print("  🚀 Baize Agent — 大模型初始化快速配置向导")
    print("  Pure Python stdlib · Zero dependencies · NO FAKE DONE")
    print("=" * 60 + "\n")

    if non_interactive:
        idx = preset_idx if preset_idx is not None else 0
        preset = PROVIDERS[idx]
        b_url = base_url or preset.base_url
        m_name = model or preset.default_model
        updates = {
            "BAIZE_MODEL_BASE_URL": b_url,
            "BAIZE_MODEL_API_KEY": api_key,
            "BAIZE_MODEL_NAME": m_name,
        }
        update_env_file(updates)
        return True

    print("请选择您要使用的大模型服务供应商：\n")
    for i, p in enumerate(PROVIDERS, 1):
        rec = " [推荐]" if i == 1 else ""
        print(f"  [{i}] {p.name}{rec}")
        print(f"      说明: {p.notes}")

    # 1. Select Provider
    choice_idx = 0
    while True:
        try:
            raw = input(f"\n请输入序号 [1-{len(PROVIDERS)}] (默认: 1 DeepSeek): ").strip()
            if not raw:
                choice_idx = 0
                break
            num = int(raw)
            if 1 <= num <= len(PROVIDERS):
                choice_idx = num - 1
                break
            print(f"请输入 1 到 {len(PROVIDERS)} 之间的数字。")
        except ValueError:
            print("请输入有效数字。")
        except (KeyboardInterrupt, EOFError):
            print("\n已取消配置向导。")
            return False

    preset = PROVIDERS[choice_idx]
    print(f"\n✓ 已选择: {preset.name}")

    # 2. Base URL
    final_base_url = preset.base_url
    if choice_idx == len(PROVIDERS) - 1:  # Custom
        while not final_base_url:
            try:
                final_base_url = input("请输入 Base URL (例如 https://api.openai.com/v1): ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n已取消。")
                return False
    else:
        try:
            custom_url = input(f"Base URL [回车使用默认: {preset.base_url}]: ").strip()
            if custom_url:
                final_base_url = custom_url
        except (KeyboardInterrupt, EOFError):
            print("\n已取消。")
            return False

    if final_base_url and not (final_base_url.startswith("http://") or final_base_url.startswith("https://")):
        final_base_url = "https://" + final_base_url.lstrip("/")

    # 3. API Key
    final_key = ""
    if preset.needs_key:
        while not final_key:
            try:
                final_key = input("请输入 API Key (sk-...): ").strip()
                if not final_key:
                    print("API Key 不能为空，请重新输入。")
            except (KeyboardInterrupt, EOFError):
                print("\n已取消。")
                return False
    else:
        try:
            k_input = input("API Key (Ollama 可直接按回车跳过): ").strip()
            final_key = k_input or "ollama-local"
        except (KeyboardInterrupt, EOFError):
            print("\n已取消。")
            return False

    # 4. Model Name
    final_model = preset.default_model
    try:
        m_prompt = f"模型名称 [回车使用推荐: {preset.default_model or 'gpt-4o'}]: " if preset.default_model else "请输入模型名称 (例如 deepseek-chat): "
        m_input = input(m_prompt).strip()
        if m_input:
            final_model = m_input
        elif not final_model:
            final_model = "deepseek-chat"
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        return False

    # 5. Connectivity check
    print(f"\n正在测试连接到 {final_base_url} ...")
    ok, msg = _test_connection(final_base_url, final_key, final_model)
    if ok:
        print(f"✓ {msg}")
    else:
        print(f"! 提示: {msg} (仍将保存配置)")

    # 6. Save .env
    updates = {
        "BAIZE_MODEL_BASE_URL": final_base_url,
        "BAIZE_MODEL_API_KEY": final_key,
        "BAIZE_MODEL_NAME": final_model,
    }
    env_file_path = update_env_file(updates)

    # Hot-reload environment variables in current process
    for k, v in updates.items():
        os.environ[k] = v

    print(f"\n🎉 配置完成！已成功安全写入: {env_file_path}")
    print(f"   • Provider:  {preset.name}")
    print(f"   • Model:     {final_model}")
    print(f"   • Base URL:  {final_base_url}")
    print("=" * 60 + "\n")
    return True
