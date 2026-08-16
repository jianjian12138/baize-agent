"""V20 web dashboard - a single self-contained HTML page, zero dependencies.

Served by the built-in REST service at GET / (and /dashboard). No build step,
no CDN, no external assets: the page is one string with inline CSS + JS that
polls the existing JSON endpoints (/health, /metrics, /sessions).

Kept in its own module so serve.py stays a thin router and the markup can be
tested independently.
"""
from __future__ import annotations

from . import __version__

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
    """Return the dashboard HTML with the runtime version substituted."""
    return PAGE.replace("__VER__", version or __version__)
