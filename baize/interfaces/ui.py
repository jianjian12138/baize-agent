"""Terminal UI rendering, HTTP dashboard HTML, session viewer, and interactive setup wizard."""

from __future__ import annotations

# ===========================================================================
# Section: ui.py
# ===========================================================================

import os
import sys
import time

__all__ = ["supports_color", "Palette", "ProgressUI",
           "render_fork_tree", "render_compress_report"]


def supports_color(stream=None) -> bool:
    """True only when ANSI color is genuinely safe to emit."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("BAIZE_FORCE_COLOR") == "1":
        return True
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform == "win32":
        try:  # enable VT processing; if it fails, stay monochrome
            import ctypes
            kernel32 = ctypes.windll.kernel32
            return bool(kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7))
        except Exception:
            return False
    return os.environ.get("TERM", "") != "dumb"


class Palette:
    """ANSI codes, or empty strings when color is unavailable."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        codes = {"dim": "\033[2m", "bold": "\033[1m", "red": "\033[31m",
                 "green": "\033[32m", "yellow": "\033[33m", "blue": "\033[34m",
                 "magenta": "\033[35m", "cyan": "\033[36m", "reset": "\033[0m"}
        for name, code in codes.items():
            setattr(self, name, code if enabled else "")

    def paint(self, color: str, text: str) -> str:
        return f"{getattr(self, color, '')}{text}{self.reset}"


# kind -> (glyph, color)
_STYLES = {
    "phase":    ("=>", "cyan"),
    "tool":     ("->", "blue"),
    "final":    ("OK", "green"),
    "reflect":  ("**", "magenta"),
    "compress": ("~~", "dim"),
    "loop":     ("!!", "yellow"),
    "error":    ("XX", "red"),
    "retry":    ("<>", "yellow"),
}


class ProgressUI:
    """Streaming progress renderer for the agent/orchestrator event stream."""

    def __init__(self, stream=None, color: bool | None = None,
                 verbose: bool = True, max_detail: int = 110):
        self.stream = stream or sys.stdout
        enabled = supports_color(self.stream) if color is None else color
        self.p = Palette(enabled)
        self.verbose = verbose
        self.max_detail = max_detail
        self.started = time.perf_counter()
        self.counts: dict[str, int] = {}
        self.events: list[tuple[float, str, str]] = []

    # --- event sink ---------------------------------------------------------

    def event(self, kind: str, detail: str = "") -> None:
        """Drop-in for on_event=(kind, detail). Never raises."""
        try:
            elapsed = time.perf_counter() - self.started
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.events.append((elapsed, kind, detail))
            if self.verbose:
                self._render(elapsed, kind, detail)
        except Exception:
            pass  # UI must never break a run

    def _render(self, elapsed: float, kind: str, detail: str) -> None:
        glyph, color = _STYLES.get(kind, ("..", "dim"))
        text = detail.replace("\n", " ")
        if len(text) > self.max_detail:
            text = text[:self.max_detail - 1] + "…"
        stamp = self.p.paint("dim", f"{elapsed:6.1f}s")
        badge = self.p.paint(color, f"{glyph} {kind:<8}")
        print(f"{stamp} {badge} {text}", file=self.stream, flush=True)

    # --- summary ------------------------------------------------------------

    def summary(self, result=None) -> str:
        """Render a closing summary; returns the text (also printed)."""
        total = time.perf_counter() - self.started
        lines = [self.p.paint("bold", "-" * 62),
                 self.p.paint("bold", f"  run finished in {total:.1f}s")]
        if self.counts:
            parts = "  ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
            lines.append(f"  events: {parts}")
        if result is not None:
            reason = getattr(result, "stopped_reason", None)
            if reason:
                color = "green" if reason == "final" else "yellow"
                lines.append(f"  outcome: {self.p.paint(color, reason)}  "
                             f"steps={getattr(result, 'steps', '?')}  "
                             f"tools={getattr(result, 'tool_calls', '?')}")
            success = getattr(result, "success", None)
            if success is not None:
                color = "green" if success else "red"
                label = "SUCCESS" if success else "FAILED"
                lines.append(f"  overall: {self.p.paint(color, label)}")
        lines.append(self.p.paint("bold", "-" * 62))
        text = "\n".join(lines)
        print(text, file=self.stream, flush=True)
        return text

    def bar(self, done: int, total: int, width: int = 30) -> str:
        """Render a static progress bar (returned, not printed)."""
        total = max(1, total)
        filled = int(width * min(done, total) / total)
        return (f"[{'#' * filled}{'.' * (width - filled)}] "
                f"{done}/{total}")


# ---------------------------------------------------------------------------
# P2-4: session fork tree + compression report (text renderers)
# ---------------------------------------------------------------------------


def render_fork_tree(lineage: dict, palette: Palette | None = None) -> str:
    """Render the session fork lineage as an ASCII tree.

    ``lineage`` maps child_id -> {parent, at_index, created_at}. The oldest
    ancestors (no parent pointing at them) start each branch.
    """
    p = palette or Palette(enabled=False)
    children_ids = {cid for cid, meta in lineage.items() if meta.get("parent")}
    roots = [cid for cid in lineage if cid not in children_ids] or list(lineage)
    children: dict = {}
    for cid, meta in lineage.items():
        par = meta.get("parent")
        if par:
            children.setdefault(par, []).append(cid)

    lines: list[str] = [p.paint("bold", "会话分叉树")]
    seen: set[str] = set()

    def walk(cid: str, prefix: str) -> None:
        if cid in seen:
            return
        seen.add(cid)
        meta = lineage.get(cid, {})
        at = meta.get("at_index")
        fork_tag = f" (fork @#{at})" if at is not None else ""
        lines.append(f"{prefix}{p.paint('cyan', cid)}{fork_tag}")
        for child in children.get(cid, []):
            walk(child, prefix + "  ├─ ")

    for root in roots:
        walk(root, "└─ ")
    if not lineage:
        lines.append(p.paint("dim", "(暂无分叉)"))
    return "\n".join(lines)


def render_compress_report(report: dict, palette: Palette | None = None) -> str:
    """Render a compress_session() report as readable text."""
    p = palette or Palette(enabled=False)
    s = report.get("summary", {})
    rows = [
        f"{p.paint('bold', '会话 ' + str(report.get('session_id')))}",
        f"  压缩前 tokens : {report.get('before_tokens')}",
        f"  压缩后 tokens : {report.get('after_tokens')}",
        (f"  节省 tokens   : {p.paint('green', str(report.get('saved_tokens')))}"
         f"  (比率 {report.get('compression_ratio')})"),
        (f"  保留消息      : {report.get('retained_messages')}"
         f" / {s.get('total_messages')}"),
        f"  角色分布      : {s.get('roles')}",
        f"  目标          : {', '.join(s.get('goals', [])) or '无'}",
        f"  工具调用      : {', '.join(s.get('tool_calls', [])) or '无'}",
        (f"  Verifier 结论 : "
         f"{p.paint('magenta', ' | '.join(s.get('verdicts', [])) or '无')}"),
        f"  错误数        : {s.get('errors')}",
    ]
    return "\n".join(rows)

# ===========================================================================
# Section: dashboard.py
# ===========================================================================

from .. import __version__

__all__ = ["render", "PAGE"]

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Baize Engine V__VER__ · 控制台</title>
<style>
  :root {
    --bg:#0f1115; --panel:#171a21; --line:#262b36; --fg:#e6e9ef;
    --muted:#8b93a7; --accent:#5eead4; --ok:#4ade80; --warn:#fbbf24; --err:#f87171;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
  header { padding:18px 24px; border-bottom:1px solid var(--line);
           display:flex; align-items:center; gap:14px; }
  h1 { margin:0; font-size:17px; letter-spacing:.5px; }
  .tag { font-size:12px; color:var(--bg); background:var(--accent);
         padding:2px 8px; border-radius:10px; font-weight:600; }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--muted); }
  .dot.on { background:var(--ok); box-shadow:0 0 8px var(--ok); }
  .dot.off { background:var(--err); }
  main { padding:24px; display:grid; gap:18px;
         grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }
  section { background:var(--panel); border:1px solid var(--line);
            border-radius:10px; padding:16px 18px; }
  h2 { margin:0 0 12px; font-size:13px; text-transform:uppercase;
       letter-spacing:1px; color:var(--muted); font-weight:600; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  td { padding:5px 0; border-bottom:1px solid var(--line); }
  td:last-child { text-align:right; color:var(--accent); font-variant-numeric:tabular-nums; }
  tr:last-child td { border-bottom:none; }
  .empty { color:var(--muted); font-style:italic; }
  form { display:flex; gap:8px; margin-bottom:10px; }
  input, button { font:inherit; border-radius:6px; border:1px solid var(--line); }
  input { flex:1; padding:8px 10px; background:var(--bg); color:var(--fg); }
  button { padding:8px 16px; background:var(--accent); color:#08131a;
           font-weight:600; border:none; cursor:pointer; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  pre { margin:0; white-space:pre-wrap; word-break:break-word; max-height:260px;
        overflow:auto; font-size:12px; color:var(--muted);
        font-family:ui-monospace,Consolas,monospace; }
  .full { grid-column:1/-1; }
  footer { padding:10px 24px 26px; color:var(--muted); font-size:12px; }
</style>
</head>
<body>
<header>
  <span class="dot" id="dot"></span>
  <h1>Baize Engine</h1><span class="tag" id="ver">V__VER__</span>
  <span class="tag" id="gate" style="background:var(--muted)">门禁 —</span>
  <span style="margin-left:auto;color:var(--muted);font-size:12px" id="tick">—</span>
</header>
<main>
  <section>
    <h2>运行状态</h2>
    <table id="health"><tr><td class="empty">加载中…</td></tr></table>
  </section>
  <section>
    <h2>指标 Metrics</h2>
    <table id="metrics"><tr><td class="empty">加载中…</td></tr></table>
  </section>
  <section>
    <h2>会话 Sessions</h2>
    <table id="sessions"><tr><td class="empty">加载中…</td></tr></table>
  </section>
  <section class="full">
    <h2>执行任务</h2>
    <form id="runform">
      <input id="goal" placeholder="输入目标，例如：检查项目结构并总结" autocomplete="off">
      <button type="submit" id="btn">运行</button>
    </form>
    <pre id="out">尚未运行。提交目标后结果显示在此处。</pre>
  </section>
  <section class="full">
    <h2>会话分支 / 压缩</h2>
    <p style="color:var(--muted);font-size:12px;margin:0 0 10px">
      分叉：从某条消息处派生独立会话（父会话不变）；压缩：抽取式压缩，保留
      Verifier 证据（工具调用 / 结论 / 错误），显示压缩前后 token。
    </p>
    <form id="forkform" style="margin-bottom:14px">
      <input id="fparent" placeholder="父会话 id" autocomplete="off">
      <input id="fat" placeholder="分叉位置 (消息序号, 留空=全部)" style="max-width:260px" autocomplete="off">
      <button type="submit">分叉</button>
    </form>
    <form id="compressform" style="margin-bottom:10px">
      <input id="cid" placeholder="会话 id" autocomplete="off">
      <button type="submit">压缩分析</button>
    </form>
    <pre id="forkout">分叉 / 压缩结果在此显示。</pre>
  </section>
</main>
<footer>纯 stdlib 实现 · 无第三方依赖 · 数据每 5 秒刷新</footer>
<script>
const $ = id => document.getElementById(id);
const rows = (obj, empty) => {
  const ks = Object.keys(obj);
  if (!ks.length) return '<tr><td class="empty">' + empty + '</td></tr>';
  return ks.map(k => '<tr><td>' + k + '</td><td>' + obj[k] + '</td></tr>').join('');
};
async function poll() {
  try {
    const h = await (await fetch('/health')).json();
    $('dot').className = 'dot on';
    $('ver').textContent = 'V' + h.version;
    $('health').innerHTML = rows({状态: h.status, 版本: h.version}, '无数据');
  } catch (e) { $('dot').className = 'dot off'; }
  try {
    const text = await (await fetch('/metrics')).text();
    const m = {};
    text.split('\\n').forEach(l => {
      if (!l || l.startsWith('#')) return;
      const [k, v] = l.split(' ');
      if (k) m[k.replace(/^baize_/, '')] = v;
    });
    $('metrics').innerHTML = rows(m, '暂无指标');
  } catch (e) {}
  try {
    const s = await (await fetch('/sessions')).json();
    const list = (s.sessions || []).slice(-8).reverse();
    $('sessions').innerHTML = list.length
      ? list.map(x => '<tr><td>' + (x.id || x) + '</td><td>' +
          (x.messages !== undefined ? x.messages + ' 条' : '') + '</td></tr>').join('')
      : '<tr><td class="empty">暂无会话</td></tr>';
  } catch (e) {}
  try {
    const g = await (await fetch('/gate')).json();
    const el = $('gate');
    const map = {pass:['通过','var(--ok)'], fail:['失败','var(--err)'],
                 unknown:['未达','var(--warn)']};
    const [label, color] = map[g.status] || ['—','var(--muted)'];
    el.textContent = '门禁 ' + label;
    el.style.background = color;
  } catch (e) {}
  $('tick').textContent = new Date().toLocaleTimeString();
}
$('runform').onsubmit = async ev => {
  ev.preventDefault();
  const goal = $('goal').value.trim();
  if (!goal) return;
  $('btn').disabled = true; $('out').textContent = '运行中…';
  try {
    const r = await fetch('/run', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({goal})});
    const d = await r.json();
    $('out').textContent = d.error
      ? '错误: ' + d.error
      : d.final_text + '\\n\\n[' + d.stopped_reason + ' · steps=' + d.steps +
        ' · session=' + d.session_id + ']';
  } catch (e) { $('out').textContent = '请求失败: ' + e; }
  $('btn').disabled = false; poll();
};
$('forkform').onsubmit = async ev => {
  ev.preventDefault();
  const parent = $('fparent').value.trim();
  const at = $('fat').value.trim();
  if (!parent) return;
  $('forkout').textContent = '处理中…';
  try {
    const r = await fetch('/sessions/fork', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({parent, at_index: at})});
    const d = await r.json();
    if (d.error) { $('forkout').textContent = '错误: ' + d.error; return; }
    $('forkout').textContent = '分叉成功 → 新会话 ' + d.new_session_id +
      '\\n父会话 ' + d.fork_of + ' @ 消息#' + d.at_index;
  } catch (e) { $('forkout').textContent = '请求失败: ' + e; }
};
$('compressform').onsubmit = async ev => {
  ev.preventDefault();
  const id = $('cid').value.trim();
  if (!id) return;
  $('forkout').textContent = '分析中…';
  try {
    const r = await fetch('/sessions/compress', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({id})});
    const d = await r.json();
    if (d.error) { $('forkout').textContent = '错误: ' + d.error; return; }
    const s = d.summary;
    const lines = [
      '会话 ' + d.session_id,
      '压缩前 tokens : ' + d.before_tokens,
      '压缩后 tokens : ' + d.after_tokens,
      '节省 tokens   : ' + d.saved_tokens + '  (比率 ' + d.compression_ratio + ')',
      '保留消息数    : ' + d.retained_messages + ' / ' + s.total_messages,
      '角色分布      : ' + JSON.stringify(s.roles),
      '工具调用      : ' + (s.tool_calls.join(', ') || '无'),
      'Verifier 结论 : ' + (s.verdicts.join(' | ') || '无'),
      '错误数        : ' + s.errors,
    ];
    $('forkout').textContent = lines.join('\\n');
  } catch (e) { $('forkout').textContent = '请求失败: ' + e; }
};
poll(); setInterval(poll, 5000);
</script>
</body>
</html>"""


def render(version: str | None = None) -> str:
    """Return the Universal Desktop Studio HTML with the runtime version substituted."""
    from .desktop import render_desktop_studio
    return render_desktop_studio(version or __version__)

# ===========================================================================
# Section: session_viewer.py
# ===========================================================================

import json
from pathlib import Path


def render_session(path, max_content=200):
    path = Path(path)
    if not path.is_file():
        return "ERROR: session file not found: " + str(path)
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        return "(empty session: " + path.name + ")"
    out = ["Session: " + path.stem, "  Records: " + str(len(records)), "-" * 60]
    span_count = 0
    total_ms = 0
    for rec in records:
        kind = rec.get("kind", "message")
        ts = rec.get("ts", "")
        if kind == "message":
            msg = rec.get("message", {})
            role = msg.get("role", "?")
            content = str(msg.get("content") or "")[:max_content]
            ct = content.replace("\n", " ")
            if role == "system":
                out.append("  [" + ts + "] SYSTEM (" + str(len(content)) + " chars)")
            elif role == "user":
                out.append("  [" + ts + "] USER  " + repr(ct[:80]))
            elif role == "assistant":
                tcs = msg.get("tool_calls") or []
                cot = " (thinking)" if "<thinking>" in content else ""
                if tcs:
                    names = ", ".join(tc.get("function", {}).get("name", "?") for tc in tcs)
                    out.append("  [" + ts + "] ASST" + cot + " -> [" + names + "]")
                else:
                    out.append("  [" + ts + "] ASST" + cot + " " + repr(ct[:80]))
            elif role == "tool":
                out.append("  [" + ts + "]   OBS " + repr(ct[:80]))
        elif kind == "span":
            span_count += 1
            elapsed = rec.get("elapsed_ms", 0)
            total_ms += elapsed
            ok = "OK" if rec.get("ok", True) else "FAIL"
            tn = rec.get("tool", "?")
            out.append("  [" + ts + "]   SPAN " + tn + " (" + str(elapsed) + "ms) " + ok)
        elif kind == "compress":
            n = rec.get("message", {}).get("compressed", 0)
            out.append("  [" + ts + "] COMPRESS " + str(n))
        elif kind in ("fork", "rewind"):
            out.append("  [" + ts + "] " + kind.upper())
    out.append("-" * 60)
    out.append("  spans=" + str(span_count) + " total_tool_ms=" + str(total_ms))
    return "\n".join(out)


def find_session_file(session_id, cfg=None):
    if cfg is None:
        from ..core.config import load_config
        cfg = load_config()
    d = Path(cfg.get("BAIZE_SESSIONS_DIR", "persistence/sessions"))
    if not d.is_dir():
        return None
    exact = d / (session_id + ".jsonl")
    if exact.is_file():
        return exact
    matches = sorted(d.glob(session_id + "*.jsonl"), reverse=True)
    return matches[0] if matches else None

# ===========================================================================
# Section: setup_wizard.py
# ===========================================================================

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import NamedTuple

from ..core.config import ROOT, ENV_FILE, load_config
from ..core.config import get_logger

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
