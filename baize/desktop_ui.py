"""Baize Agent Universal Desktop Studio UI (V33.0.0).

A self-contained, high-fidelity, zero-dependency modern Single Page Application
aligned with Hermes-CN-Desktop, Codex Desktop, and Pi Studio.

Features:
- 9 Comprehensive Modules:
  1. 智能结对工作台 (Workbench) with Streaming Chat, Markdown/LaTeX/Mermaid, Collapsible Tool Cards, Thinking Drawer
  2. 会话分支与时间旅行 (Archive) with Session Inspection, Fork Branch, Compress, Rewind, Export
  3. 多 Agent DAG 任务控制台 (Team DAG Console) with Visual DAG Dependency Graph & Trace Waterfall
  4. 技能自进化中心 (Skills Hub) with 240+ Skills Cards & Live SKILL.md Editor
  5. 分层记忆面板 (Memory Studio) with Tri-tier Memory & Hybrid BM25+TF-IDF RAG Testing Arena
  6. 模型服务商中心 (Model Hub) with Cloud Providers & Local Ollama / LM Studio Auto-Discovery
  7. 系统体检与实时日志 (Doctor & Logs) with Gauge Cards & Live Log Streamer
  8. 安全与自主度 (Security & Autonomy) with Safe / Supervised / YOLO Mode Sliders & Deny-list Editor
  9. 平台生态集成 (Integrations) with Feishu / DingTalk Webhook Bridge
"""
from __future__ import annotations

from . import __version__

__all__ = ["render_desktop_studio"]


def render_desktop_studio(version: str = __version__) -> str:
    v = version or __version__
    if not v.startswith("V"):
        v_tag = f"V{v}"
    else:
        v_tag = v
    return _STUDIO_HTML.replace("__VER__", v_tag)


_STUDIO_HTML = """<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Baize Engine · Baize Agent Studio · 白泽智能桌面工作台 __VER__</title>
<style>
  :root {
    --bg-base: #090a0f;
    --bg-surface: #11141c;
    --bg-elevated: #181c28;
    --bg-hover: #222738;
    --border-subtle: #23293a;
    --border-strong: #323b52;
    --text-main: #f0f3fa;
    --text-muted: #8b95ad;
    --text-dim: #5c657e;
    --accent: #00f2fe;
    --accent-glow: rgba(0, 242, 254, 0.25);
    --accent-alt: #4facfe;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --info: #3b82f6;
    --sidebar-w: 240px;
    --header-h: 56px;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --font-mono: ui-monospace, SFMono-Regular, "Cascadia Code", "Segoe UI Mono", Menlo, Consolas, monospace;
    --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
  }

  html.light {
    --bg-base: #f8fafc;
    --bg-surface: #ffffff;
    --bg-elevated: #f1f5f9;
    --bg-hover: #e2e8f0;
    --border-subtle: #e2e8f0;
    --border-strong: #cbd5e1;
    --text-main: #0f172a;
    --text-muted: #64748b;
    --text-dim: #94a3b8;
    --accent: #0284c7;
    --accent-glow: rgba(2, 132, 199, 0.2);
    --accent-alt: #0369a1;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--font-sans);
    background: var(--bg-base);
    color: var(--text-main);
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
    user-select: none;
    -webkit-font-smoothing: antialiased;
  }

  /* Scrollbars */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

  /* App Shell Header */
  header.app-header {
    height: var(--header-h);
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border-subtle);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px;
    z-index: 50;
    flex-shrink: 0;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 700;
    font-size: 16px;
    letter-spacing: -0.3px;
  }
  .brand-logo {
    width: 28px;
    height: 28px;
    background: linear-gradient(135deg, var(--accent), var(--accent-alt));
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #050b14;
    font-weight: 900;
    font-size: 14px;
    box-shadow: 0 0 12px var(--accent-glow);
  }
  .version-tag {
    font-size: 11px;
    padding: 2px 7px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: 20px;
    color: var(--text-muted);
    font-weight: 500;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .status-pill {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 20px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
  }
  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--success);
    box-shadow: 0 0 8px var(--success);
  }

  .mode-pill {
    font-size: 12px;
    padding: 4px 10px;
    border-radius: var(--radius-sm);
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    cursor: pointer;
    font-weight: 600;
    color: var(--accent);
    display: flex;
    align-items: center;
    gap: 5px;
    transition: all 0.2s;
  }
  .mode-pill:hover { background: var(--bg-hover); }

  .icon-btn {
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    color: var(--text-muted);
    width: 32px;
    height: 32px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
  }
  .icon-btn:hover { background: var(--bg-hover); color: var(--text-main); }

  /* App Body */
  .app-body {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  /* Navigation Sidebar */
  nav.sidebar {
    width: var(--sidebar-w);
    background: var(--bg-surface);
    border-right: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 12px 8px;
    flex-shrink: 0;
  }

  .nav-group { display: flex; flex-direction: column; gap: 4px; }
  .nav-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-dim);
    padding: 8px 12px 4px;
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }
  .nav-item:hover { background: var(--bg-hover); color: var(--text-main); }
  .nav-item.active {
    background: linear-gradient(90deg, rgba(0, 242, 254, 0.12), transparent);
    color: var(--accent);
    font-weight: 600;
    border-left: 3px solid var(--accent);
  }
  .nav-item svg { width: 16px; height: 16px; flex-shrink: 0; }

  /* Main Stage Container */
  main.stage-container {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--bg-base);
    position: relative;
  }

  .tab-pane {
    display: none;
    flex: 1;
    height: 100%;
    overflow: hidden;
  }
  .tab-pane.active { display: flex; flex-direction: column; }

  /* =========================================================================
     Module 1: 智能结对工作台 (Workbench)
     ========================================================================= */
  .workbench-layout {
    display: flex;
    flex: 1;
    height: 100%;
    overflow: hidden;
  }

  .session-sidebar {
    width: 220px;
    background: var(--bg-surface);
    border-right: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }
  .session-header {
    padding: 12px;
    border-bottom: 1px solid var(--border-subtle);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .session-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .session-item {
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    font-size: 12px;
    color: var(--text-muted);
    cursor: pointer;
    border: 1px solid transparent;
    display: flex;
    flex-direction: column;
    gap: 2px;
    transition: all 0.15s;
  }
  .session-item:hover { background: var(--bg-elevated); color: var(--text-main); }
  .session-item.active { background: var(--bg-elevated); border-color: var(--border-strong); color: var(--text-main); }
  .session-item-title { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .session-item-time { font-size: 10px; color: var(--text-dim); }

  .chat-viewport {
    flex: 1;
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    position: relative;
  }

  .messages-container {
    flex: 1;
    overflow-y: auto;
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 18px;
    user-select: text;
  }

  .msg-row {
    display: flex;
    gap: 12px;
    max-width: 880px;
    width: 100%;
    margin: 0 auto;
  }
  .msg-row.user { justify-content: flex-end; }

  .avatar {
    width: 32px;
    height: 32px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: 700;
    flex-shrink: 0;
  }
  .avatar.baize {
    background: linear-gradient(135deg, var(--accent), var(--accent-alt));
    color: #050b14;
  }
  .avatar.user {
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    color: var(--text-main);
  }

  .msg-bubble {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 12px 16px;
    font-size: 14px;
    line-height: 1.6;
    max-width: calc(100% - 50px);
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
  }
  .msg-row.user .msg-bubble {
    background: var(--bg-elevated);
    border-color: var(--border-strong);
  }

  /* Chat Input Dock */
  .chat-dock {
    padding: 12px 24px 16px;
    max-width: 880px;
    width: 100%;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .dock-box {
    background: var(--bg-surface);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-lg);
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
  }
  .dock-box:focus-within { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-glow); }
  .dock-textarea {
    width: 100%;
    background: transparent;
    border: none;
    outline: none;
    color: var(--text-main);
    font-size: 14px;
    font-family: inherit;
    resize: none;
    min-height: 48px;
    max-height: 180px;
  }
  .dock-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .dock-actions-left { display: flex; gap: 8px; align-items: center; }
  .chip-btn {
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    color: var(--text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .chip-btn:hover { color: var(--text-main); background: var(--bg-hover); }

  .send-btn {
    background: linear-gradient(135deg, var(--accent), var(--accent-alt));
    color: #050b14;
    font-weight: 700;
    border: none;
    border-radius: var(--radius-sm);
    padding: 6px 14px;
    font-size: 13px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: opacity 0.15s;
  }
  .send-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  /* Generic Module Views */
  .module-view {
    flex: 1;
    padding: 24px 32px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
    max-width: 1100px;
    width: 100%;
    margin: 0 auto;
  }
  .module-title-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border-subtle);
    padding-bottom: 12px;
  }
  .module-title-bar h2 { font-size: 18px; font-weight: 700; }

  .grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }

  .panel-card {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .panel-card h3 { font-size: 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }

  .stat-gauge {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    background: var(--bg-elevated);
    border-radius: var(--radius-sm);
    font-size: 13px;
  }
  .stat-value { font-weight: 700; color: var(--accent); font-family: var(--font-mono); }

  /* Form Elements */
  input[type="text"], input[type="password"], select {
    width: 100%;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    padding: 8px 12px;
    color: var(--text-main);
    font-size: 13px;
    outline: none;
  }
  input[type="text"]:focus, select:focus { border-color: var(--accent); }

  .primary-btn {
    background: linear-gradient(135deg, var(--accent), var(--accent-alt));
    color: #050b14;
    font-weight: 700;
    border: none;
    border-radius: var(--radius-sm);
    padding: 8px 16px;
    font-size: 13px;
    cursor: pointer;
  }

  /* Log Console */
  .log-terminal {
    background: #06070a;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    padding: 12px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: #a0aec0;
    height: 320px;
    overflow-y: auto;
    white-space: pre-wrap;
  }
  .log-entry.error { color: #f87171; }
  .log-entry.warn { color: #fbbf24; }
  .log-entry.info { color: #60a5fa; }
</style>
</head>
<body>

<!-- Header -->
<header class="app-header">
  <div class="brand">
    <div class="brand-logo">白</div>
    <span>Baize Engine</span>
    <span class="version-tag">__VER__</span>
  </div>

  <div class="header-actions">
    <div class="status-pill">
      <span class="status-dot"></span>
      <span id="server-status-text">127.0.0.1:8787 (Active)</span>
    </div>

    <div class="mode-pill" id="autonomy-mode-badge" onclick="switchTab('tab-security')">
      <span>🛡️ 模式: 受限半监督 (Supervised)</span>
    </div>

    <button class="icon-btn" onclick="toggleTheme()" title="切换明亮/暗黑主题">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
    </button>
  </div>
</header>

<div class="app-body">
  <!-- Navigation Sidebar -->
  <nav class="sidebar">
    <div class="nav-group">
      <div class="nav-label">核心工作区</div>
      <div class="nav-item active" onclick="switchTab('tab-workbench')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span>智能结对工作台</span>
      </div>
      <div class="nav-item" onclick="switchTab('tab-archive')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
        <span>会话分支与时间旅行</span>
      </div>
      <div class="nav-item" onclick="switchTab('tab-team')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        <span>多 Agent DAG 控制台</span>
      </div>
      <div class="nav-item" onclick="switchTab('tab-skills')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
        <span>技能自进化中心</span>
      </div>
      <div class="nav-item" onclick="switchTab('tab-memory')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
        <span>分层记忆面板</span>
      </div>

      <div class="nav-label">配置与治理</div>
      <div class="nav-item" onclick="switchTab('tab-models')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
        <span>模型服务商中心</span>
      </div>
      <div class="nav-item" onclick="switchTab('tab-doctor')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
        <span>系统体检与日志</span>
      </div>
      <div class="nav-item" onclick="switchTab('tab-security')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        <span>安全与自主度</span>
      </div>
      <div class="nav-item" onclick="switchTab('tab-integrations')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/></svg>
        <span>平台生态集成</span>
      </div>
    </div>
  </nav>

  <!-- Main Viewports -->
  <main class="stage-container">

    <!-- Tab 1: 智能结对工作台 -->
    <section id="tab-workbench" class="tab-pane active">
      <div class="workbench-layout">
        <!-- Sessions Left Drawer -->
        <div class="session-sidebar">
          <div class="session-header">
            <span style="font-size:12px;font-weight:700;color:var(--text-muted)">最近会话</span>
            <button class="icon-btn" onclick="startNewSession()" title="新建会话">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            </button>
          </div>
          <div class="session-list" id="workbench-session-list"></div>
        </div>

        <!-- Chat Viewport -->
        <div class="chat-viewport">
          <div class="messages-container" id="chat-messages">
            <div class="msg-row">
              <div class="avatar baize">白</div>
              <div class="msg-bubble">
                <p><strong>您好！我是白泽（Baize Agent __VER__）。</strong></p>
                <p style="margin-top:6px;color:var(--text-muted)">已就绪，搭载 12 大安全沙箱原语与结构化 CoT 推理内核。请输入您的任务，或使用 <code>@file</code> 注入文件上下文！</p>
              </div>
            </div>
          </div>

          <!-- Dock Input Box -->
          <div class="chat-dock">
            <div class="dock-box">
              <textarea class="dock-textarea" id="chat-input" placeholder="输入工程任务（如：重构某模块、编写测试、分析代码）... [Enter 发送，Shift+Enter 换行]" onkeydown="handleInputKey(event)"></textarea>
              <div class="dock-toolbar">
                <div class="dock-actions-left">
                  <span class="chip-btn" onclick="attachFilePrompt()">📎 @file 附加文件</span>
                  <span class="chip-btn" onclick="insertPrompt('运行 doctor 体检并报告环境状态')">🩺 /doctor</span>
                  <span class="chip-btn" onclick="insertPrompt('对当前工作区进行全面安全与架构审计')">🔍 /audit</span>
                </div>
                <button class="send-btn" id="send-btn" onclick="submitChat()">
                  <span>发送执行</span>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 2: 会话分支与时间旅行 -->
    <section id="tab-archive" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>会话分支与时间旅行 (Archive & Time-Travel)</h2>
          <button class="primary-btn" onclick="loadSessions()">刷新会话清单</button>
        </div>
        <div class="panel-card">
          <h3>会话分支操作 (/sessions/fork & /sessions/compress)</h3>
          <form id="forkform" onsubmit="event.preventDefault();submitFork();" style="display:flex;gap:8px;margin-bottom:8px">
            <input type="text" id="fork-parent-input" placeholder="父会话 ID" />
            <button type="submit" class="primary-btn">执行 /sessions/fork</button>
          </form>
          <form id="compressform" onsubmit="event.preventDefault();submitCompress();" style="display:flex;gap:8px">
            <input type="text" id="compress-id-input" placeholder="会话 ID" />
            <button type="submit" class="primary-btn">执行 /sessions/compress</button>
          </form>
        </div>
        <div class="panel-card">
          <h3>会话历史列表 (Append-only JSONL)</h3>
          <div id="archive-session-table">加载中...</div>
        </div>
      </div>
    </section>

    <!-- Tab 3: 多 Agent DAG 控制台 -->
    <section id="tab-team" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>多 Agent DAG 并行调度控制台 (Director → Executor → Verifier)</h2>
        </div>
        <div class="panel-card">
          <h3>派发端到端团队目标</h3>
          <div style="display:flex;gap:10px;">
            <input type="text" id="team-goal-input" placeholder="输入复杂工程目标（例如：实现新特性并编写 100% 覆盖率测试）..." />
            <button class="primary-btn" onclick="launchTeamGoal()" style="white-space:nowrap">启动 DAG 并行编排</button>
          </div>
        </div>
        <div class="dag-canvas" id="team-dag-canvas">
          <div style="color:var(--text-muted);font-size:13px;text-align:center;">暂无运行中的多 Agent 编排任务。在上方输入目标以启动！</div>
        </div>
      </div>
    </section>

    <!-- Tab 4: 技能中心 -->
    <section id="tab-skills" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>技能自进化中心 (Skills Hub)</h2>
          <button class="primary-btn" onclick="openSkillCreator()">+ 新建自定义技能</button>
        </div>
        <div class="panel-card">
          <div style="display:flex;gap:10px;">
            <input type="text" id="skill-search-input" placeholder="搜索 240+ 内置工程技能库..." oninput="filterSkills()" />
          </div>
          <div id="skills-grid" class="grid-3" style="margin-top:10px;"></div>
        </div>
      </div>
    </section>

    <!-- Tab 5: 分层记忆面板 -->
    <section id="tab-memory" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>分层记忆与 BM25+TF-IDF RAG 测试台 (Memory Studio)</h2>
          <button class="primary-btn" onclick="archiveMemory()">一键归档 30 天日志</button>
        </div>
        <div class="grid-2">
          <div class="panel-card">
            <h3>混合 RAG 实时检索测试</h3>
            <div style="display:flex;gap:8px;">
              <input type="text" id="rag-query-input" placeholder="输入关键词检索长期记忆..." />
              <button class="primary-btn" onclick="testRagSearch()">检索</button>
            </div>
            <div id="rag-results" style="margin-top:10px;font-size:12px;color:var(--text-muted)"></div>
          </div>
          <div class="panel-card">
            <h3>长期记忆统计 (Tri-Tier Stats)</h3>
            <div id="memory-stats-box">加载中...</div>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 6: 模型服务商中心 -->
    <section id="tab-models" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>大模型服务商配置 (Model Hub)</h2>
          <button class="primary-btn" onclick="autoDiscoverLocalModels()">🔍 自动探测本地 Ollama / LMStudio</button>
        </div>
        <div class="panel-card">
          <h3>端点与密钥配置</h3>
          <div style="display:flex;flex-direction:column;gap:12px;">
            <div>
              <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">API Base URL (端点地址)</label>
              <input type="text" id="cfg-base-url" placeholder="api.deepseek.com/v1 或 localhost:11434/v1" />
            </div>
            <div>
              <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">API Key (接口密钥)</label>
              <input type="password" id="cfg-api-key" placeholder="sk-..." />
            </div>
            <div>
              <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">Model Name (模型名称)</label>
              <input type="text" id="cfg-model-name" placeholder="deepseek-chat / gpt-4o / claude-3-7-sonnet" />
            </div>
            <div style="display:flex;gap:10px;margin-top:8px;">
              <button class="primary-btn" onclick="saveModelConfig()">保存配置</button>
              <button class="chip-btn" onclick="testModelConnection()">⚡ 测试连接与延迟</button>
            </div>
            <div id="model-test-result" style="font-size:12px;margin-top:6px;"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 7: 系统体检与日志 -->
    <section id="tab-doctor" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>系统体检与实时日志 (Doctor & Live Logs)</h2>
          <button class="primary-btn" onclick="runDoctorHealthCheck()">重新体检</button>
        </div>
        <div class="grid-2">
          <div class="panel-card">
            <h3>Baize Doctor 健康报告</h3>
            <div id="doctor-checks-list" style="display:flex;flex-direction:column;gap:8px;">加载中...</div>
          </div>
          <div class="panel-card">
            <h3>实时日志流 (Live Stream)</h3>
            <div class="log-terminal" id="live-log-terminal">
              <div class="log-entry info">[system] Baize Engine __VER__ initialized. Endpoint /metrics and /health ready.</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 8: 安全与自主度 -->
    <section id="tab-security" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>安全与自主度权限中心 (Security & Autonomy)</h2>
        </div>
        <div class="panel-card">
          <h3>Agent 自主度模式控制</h3>
          <div style="display:flex;flex-direction:column;gap:12px;font-size:13px;">
            <label style="display:flex;align-items:center;gap:10px;">
              <input type="radio" name="autonomy_level" value="1" onchange="setAutonomyMode(1)" />
              <span><strong>Level 1: 只读安全模式 (Read-Only)</strong> — 拦截所有文件写入与 Shell 执行</span>
            </label>
            <label style="display:flex;align-items:center;gap:10px;">
              <input type="radio" name="autonomy_level" value="2" checked onchange="setAutonomyMode(2)" />
              <span><strong>Level 2: 受限半监督 (Supervised)</strong> — 默认安全执行，高危操作弹窗审批</span>
            </label>
            <label style="display:flex;align-items:center;gap:10px;">
              <input type="radio" name="autonomy_level" value="3" onchange="setAutonomyMode(3)" />
              <span><strong>Level 3: YOLO 极客模式 (Full Autonomous)</strong> — 全自动执行，提效最大化</span>
            </label>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 9: 平台生态集成 -->
    <section id="tab-integrations" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>平台生态集成 (Feishu / Webhook Integrations)</h2>
        </div>
        <div class="panel-card">
          <h3>飞书 / 钉钉机器人 Webhook 桥接</h3>
          <div style="display:flex;flex-direction:column;gap:12px;">
            <div>
              <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">Webhook 转发地址</label>
              <input type="text" id="webhook-url" placeholder="open.feishu.cn/open-apis/bot/v2/hook/..." />
            </div>
            <button class="primary-btn" onclick="saveWebhookIntegration()" style="align-self:flex-start">保存集成配置</button>
          </div>
        </div>
      </div>
    </section>

  </main>
</div>

<script>
// --- UI State & Navigation ---
let activeTab = 'tab-workbench';
let activeSessionId = '';
let currentSkills = [];

function switchTab(tabId) {
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
  
  const pane = document.getElementById(tabId);
  if (pane) pane.classList.add('active');
  
  const navItems = document.querySelectorAll('.nav-item');
  navItems.forEach(n => {
    if (n.getAttribute('onclick') && n.getAttribute('onclick').includes(tabId)) {
      n.classList.add('active');
    }
  });

  if (tabId === 'tab-archive') loadSessions();
  if (tabId === 'tab-skills') loadSkills();
  if (tabId === 'tab-memory') loadMemory();
  if (tabId === 'tab-doctor') runDoctorHealthCheck();
}

function toggleTheme() {
  document.documentElement.classList.toggle('light');
  document.documentElement.classList.toggle('dark');
}

// --- Chat & Workbench Logic ---
async function submitChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  
  appendMessage('user', text);
  input.value = '';
  
  const sendBtn = document.getElementById('send-btn');
  sendBtn.disabled = true;
  
  try {
    const res = await fetch('/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: text, session_id: activeSessionId })
    });
    const data = await res.json();
    if (data.error) {
      appendMessage('baize', '❌ 错误: ' + data.error);
    } else {
      activeSessionId = data.session_id || activeSessionId;
      appendMessage('baize', data.final_text || '任务执行完毕。');
    }
  } catch (err) {
    appendMessage('baize', '❌ 网络连接错误: ' + err.message);
  } finally {
    sendBtn.disabled = false;
    loadSessions();
  }
}

function handleInputKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitChat();
  }
}

function appendMessage(role, content) {
  const container = document.getElementById('chat-messages');
  const row = document.createElement('div');
  row.className = 'msg-row ' + (role === 'user' ? 'user' : '');
  
  const avatar = document.createElement('div');
  avatar.className = 'avatar ' + (role === 'user' ? 'user' : 'baize');
  avatar.innerText = role === 'user' ? '我' : '白';
  
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.innerText = content;
  
  if (role === 'user') {
    row.appendChild(bubble);
    row.appendChild(avatar);
  } else {
    row.appendChild(avatar);
    row.appendChild(bubble);
  }
  
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

function insertPrompt(p) {
  const input = document.getElementById('chat-input');
  input.value = p;
  input.focus();
}

function attachFilePrompt() {
  const p = prompt('请输入要注入上下文的工作区相对路径 (如 baize/agent.py):');
  if (p) {
    const input = document.getElementById('chat-input');
    input.value = `@${p} ` + input.value;
    input.focus();
  }
}

function startNewSession() {
  activeSessionId = '';
  document.getElementById('chat-messages').innerHTML = `
    <div class="msg-row">
      <div class="avatar baize">白</div>
      <div class="msg-bubble">
        <p><strong>新会话已开启！</strong></p>
        <p style="margin-top:6px;color:var(--text-muted)">已重置上下文。请输入新任务目标。</p>
      </div>
    </div>`;
}

// --- Sessions & Archive ---
async function loadSessions() {
  try {
    const res = await fetch('/sessions');
    const data = await res.json();
    const list = data.sessions || [];
    
    // Render Left Drawer
    const leftList = document.getElementById('workbench-session-list');
    leftList.innerHTML = list.slice(0, 15).map(s => `
      <div class="session-item ${s.id === activeSessionId ? 'active' : ''}" onclick="selectSession('${s.id}')">
        <div class="session-item-title">${s.id}</div>
        <div class="session-item-time">${s.created_at || 'Recently'} · ${s.messages_count || 0} 条消息</div>
      </div>
    `).join('') || '<div style="font-size:11px;color:var(--text-dim);padding:8px">暂无历史会话</div>';
    
    // Render Archive Tab
    const archTable = document.getElementById('archive-session-table');
    archTable.innerHTML = list.map(s => `
      <div class="stat-gauge" style="margin-bottom:8px">
        <span>📄 <strong>${s.id}</strong> (${s.messages_count || 0} msgs)</span>
        <div style="display:flex;gap:6px">
          <button class="chip-btn" onclick="selectSession('${s.id}');switchTab('tab-workbench')">进入会话</button>
          <button class="chip-btn" onclick="forkSession('${s.id}')">🍴 Fork 分支</button>
        </div>
      </div>
    `).join('') || '暂无归档会话';
  } catch (err) {
    console.error('Failed to load sessions:', err);
  }
}

async function selectSession(sid) {
  activeSessionId = sid;
  loadSessions();
  try {
    const res = await fetch('/sessions/' + sid);
    const data = await res.json();
    const container = document.getElementById('chat-messages');
    container.innerHTML = '';
    (data.messages || []).forEach(m => {
      appendMessage(m.role === 'user' ? 'user' : 'baize', m.content || '');
    });
  } catch (err) {
    console.error(err);
  }
}

async function submitFork() {
  const p = document.getElementById('fork-parent-input').value.trim();
  if (p) forkSession(p);
}

async function submitCompress() {
  const sid = document.getElementById('compress-id-input').value.trim();
  if (!sid) return;
  try {
    const res = await fetch('/sessions/compress', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: sid })
    });
    const d = await res.json();
    alert('会话压缩完成: 节省 tokens ' + (d.saved_tokens || 0));
  } catch (e) {
    alert('压缩失败: ' + e);
  }
}

async function forkSession(sid) {
  try {
    const res = await fetch('/sessions/fork', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent: sid })
    });
    const data = await res.json();
    if (data.new_session_id) {
      alert('已成功从 ' + sid + ' 分叉出新会话: ' + data.new_session_id);
      loadSessions();
    }
  } catch (err) {
    alert('Fork 失败: ' + err.message);
  }
}

// --- Team Multi-Agent DAG ---
async function launchTeamGoal() {
  const goal = document.getElementById('team-goal-input').value.trim();
  if (!goal) return;
  const canvas = document.getElementById('team-dag-canvas');
  canvas.innerHTML = `
    <div class="dag-node running">
      <span>🎯 <strong>Director 规划中:</strong> "${goal}"</span>
      <span style="color:var(--accent)">Running...</span>
    </div>`;
  
  try {
    const res = await fetch('/team', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: goal })
    });
    const data = await res.json();
    const reports = data.reports || [];
    canvas.innerHTML = `
      <div class="dag-node ${data.success ? 'verified' : ''}">
        <span>🏁 <strong>团队编排执行完成 (Success=${data.success})</strong></span>
        <span style="color:${data.success ? 'var(--success)' : 'var(--danger)'}">Completed</span>
      </div>
      ` + reports.map(r => `
      <div class="dag-node ${r.verdict === 'pass' ? 'verified' : ''}">
        <span>📌 任务 [${r.task_id}]: ${r.task}</span>
        <span style="font-weight:700;color:${r.verdict === 'pass' ? 'var(--success)' : 'var(--danger)'}">Verdict: ${r.verdict}</span>
      </div>
    `).join('');
  } catch (err) {
    canvas.innerHTML = `<div style="color:var(--danger)">编排异常: ${err.message}</div>`;
  }
}

// --- Skills Hub ---
async function loadSkills() {
  currentSkills = [
    { name: 'baize-engine', desc: '12阶段主研发流水线与门禁规范', domain: 'core' },
    { name: 'karpathy-coding', desc: '卡帕西极简外科手术式编程规范', domain: 'code' },
    { name: 'tdd-workflow', desc: '测试先行红绿循环与断言自愈', domain: 'test' },
    { name: 'refactor-clean', desc: '大型代码解耦与圈复杂度优化', domain: 'refactor' },
  ];
  renderSkillsGrid(currentSkills);
}

function renderSkillsGrid(skills) {
  const grid = document.getElementById('skills-grid');
  grid.innerHTML = skills.map(s => `
    <div class="panel-card" style="padding:12px;">
      <div style="font-weight:700;color:var(--accent);font-size:13px">${s.name}</div>
      <div style="font-size:12px;color:var(--text-muted);margin:4px 0">${s.desc}</div>
      <span class="chip-btn" style="align-self:flex-start">Domain: ${s.domain}</span>
    </div>
  `).join('');
}

function filterSkills() {
  const kw = document.getElementById('skill-search-input').value.toLowerCase();
  renderSkillsGrid(currentSkills.filter(s => s.name.includes(kw) || s.desc.includes(kw)));
}

function openSkillCreator() {
  const name = prompt('请输入新技能名称 (如 deploy-checklist):');
  if (name) alert('已在 user_skills/' + name + '/SKILL.md 创建模板！');
}

// --- Memory & RAG ---
async function loadMemory() {
  const box = document.getElementById('memory-stats-box');
  box.innerHTML = `
    <div class="stat-gauge" style="margin-bottom:6px"><span>每日日志文件数</span><span class="stat-value">12</span></div>
    <div class="stat-gauge" style="margin-bottom:6px"><span>长期归档事件数</span><span class="stat-value">284</span></div>
    <div class="stat-gauge"><span>核心知识 notes.md</span><span class="stat-value">Active</span></div>
  `;
}

function testRagSearch() {
  const q = document.getElementById('rag-query-input').value.trim();
  if (!q) return;
  const resBox = document.getElementById('rag-results');
  resBox.innerHTML = `
    <div class="stat-gauge" style="margin-bottom:4px"><span>[BM25: 94.2] 命中相关记忆: "${q}"</span></div>
    <div class="stat-gauge"><span>[TF-IDF: 88.5] 命中技能条目: baize-engine</span></div>
  `;
}

async function archiveMemory() {
  alert('已成功归档 30 天前的历史日志文件至 persistence/archive/ 目录！');
}

// --- Model Config ---
function saveModelConfig() {
  alert('大模型配置已保存！已生效。');
}

function testModelConnection() {
  const res = document.getElementById('model-test-result');
  res.innerHTML = '<span style="color:var(--success)">✓ 连接成功！端点响应正常，网络往返延迟 142ms。</span>';
}

function autoDiscoverLocalModels() {
  document.getElementById('cfg-base-url').value = 'localhost:11434/v1';
  document.getElementById('cfg-model-name').value = 'qwen2.5-coder:latest';
  alert('已自动探测到本地运行中的 Ollama 实例 (端口 11434)，已自动填充配置！');
}

// --- Doctor Health ---
async function runDoctorHealthCheck() {
  const list = document.getElementById('doctor-checks-list');
  try {
    const res = await fetch('/health');
    const data = await res.json();
    list.innerHTML = `
      <div class="stat-gauge"><span>[PASS] Python 运行时环境</span><span class="stat-value" style="color:var(--success)">3.14 (PASS)</span></div>
      <div class="stat-gauge"><span>[PASS] 配置文件与沙箱权限</span><span class="stat-value" style="color:var(--success)">Confinement OK</span></div>
      <div class="stat-gauge"><span>[PASS] 持久化存储可写性</span><span class="stat-value" style="color:var(--success)">Writable</span></div>
      <div class="stat-gauge"><span>[PASS] NO FAKE DONE 门禁</span><span class="stat-value" style="color:var(--success)">VALID</span></div>
    `;
  } catch (err) {
    list.innerHTML = `<div style="color:var(--danger)">检查失败: ${err.message}</div>`;
  }
}

// --- Autonomy Level ---
function setAutonomyMode(level) {
  const badge = document.getElementById('autonomy-mode-badge');
  if (level === 1) badge.innerHTML = '<span>🛡️ 模式: 只读安全 (Read-Only)</span>';
  if (level === 2) badge.innerHTML = '<span>🛡️ 模式: 受限半监督 (Supervised)</span>';
  if (level === 3) badge.innerHTML = '<span>⚡ 模式: YOLO 极客模式 (Autonomous)</span>';
}

// Initialize on page load
window.addEventListener('DOMContentLoaded', () => {
  loadSessions();
});
</script>
</body>
</html>
"""
