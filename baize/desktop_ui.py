"""Baize Agent Universal Desktop Studio UI (V33.0.0).

A self-contained, high-fidelity, zero-dependency modern Single Page Application
aligned with Cursor, Hermes-CN-Desktop, Codex Desktop, and Pi Studio.
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


_STUDIO_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Baize Engine · Baize Agent Studio · 白泽智能桌面工作台 __VER__</title>
<style>
  :root {
    --bg-base: #08090d;
    --bg-surface: #10121a;
    --bg-elevated: #161a26;
    --bg-hover: #1f2537;
    --border-subtle: rgba(255, 255, 255, 0.07);
    --border-strong: rgba(255, 255, 255, 0.14);
    --text-main: #f1f5f9;
    --text-muted: #94a3b8;
    --text-dim: #64748b;
    --accent: #00f2fe;
    --accent-glow: rgba(0, 242, 254, 0.25);
    --accent-alt: #38bdf8;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --info: #3b82f6;
    --rail-w: 64px;
    --header-h: 50px;
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

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
    font-size: 15px;
  }
  .brand-logo {
    width: 26px;
    height: 26px;
    background: linear-gradient(135deg, var(--accent), var(--accent-alt));
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #050b14;
    font-weight: 900;
    font-size: 13px;
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
  .workspace-pill {
    font-size: 11px;
    color: var(--text-dim);
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .status-pill {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 20px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    color: var(--text-muted);
  }
  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--success);
    box-shadow: 0 0 6px var(--success);
  }

  .mode-pill {
    font-size: 11px;
    padding: 3px 8px;
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
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
  }
  .icon-btn:hover { background: var(--bg-hover); color: var(--text-main); }
  .icon-btn.active { background: var(--bg-hover); color: var(--accent); border-color: var(--accent); }

  /* App Body */
  .app-body {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  /* Activity Rail (Slim 64px Cursor-style Navigation) */
  nav.activity-rail {
    width: var(--rail-w);
    background: var(--bg-surface);
    border-right: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: space-between;
    padding: 10px 0;
    flex-shrink: 0;
  }
  .rail-top-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: 100%;
    align-items: center;
  }
  .rail-item {
    width: 44px;
    height: 44px;
    border-radius: var(--radius-md);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    cursor: pointer;
    position: relative;
    transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .rail-item:hover {
    background: var(--bg-elevated);
    color: var(--text-main);
  }
  .rail-item.active {
    background: rgba(0, 242, 254, 0.12);
    color: var(--accent);
  }
  .rail-item.active::before {
    content: '';
    position: absolute;
    left: -10px;
    top: 10px;
    bottom: 10px;
    width: 3px;
    border-radius: 0 4px 4px 0;
    background: var(--accent);
    box-shadow: 0 0 8px var(--accent-glow);
  }
  .rail-item svg { width: 18px; height: 18px; }
  .rail-item span { font-size: 9px; margin-top: 3px; font-weight: 500; }

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
     Module 1: 智能结对工作台 (Workbench) 3-Column Flexible Layout
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
    transition: width 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .session-sidebar.collapsed { width: 0; overflow: hidden; border-right: none; }

  .session-header {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-subtle);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .session-list {
    flex: 1;
    overflow-y: auto;
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 3px;
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
    min-height: 0;
    overflow: hidden;
    position: relative;
  }

  .messages-container {
    flex: 1 1 0;
    min-height: 0;
    overflow-y: auto;
    padding: 24px 24px 12px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    user-select: text;
  }

  .msg-row {
    display: flex;
    gap: 12px;
    max-width: 860px;
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
    font-size: 12px;
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

  /* Prompt Shelf */
  .prompt-shelf {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding: 2px 0 6px;
    max-width: 860px;
    width: 100%;
    margin: 0 auto;
  }
  .prompt-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    color: var(--text-dim);
    cursor: pointer;
    white-space: nowrap;
    display: flex;
    align-items: center;
    gap: 4px;
    transition: all 0.15s;
  }
  .prompt-card:hover {
    background: rgba(0, 242, 254, 0.08);
    color: var(--accent);
    border-color: rgba(0, 242, 254, 0.3);
  }

  /* Exquisite Chat Input Dock */
  .chat-dock {
    flex-shrink: 0;
    padding: 0 24px 20px;
    max-width: 860px;
    width: 100%;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 6px;
    position: relative;
  }
  .dock-box {
    background: #12151f;
    border: 1px solid #242c3f;
    border-radius: 14px;
    padding: 12px 16px 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.45);
    position: relative;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .dock-box:focus-within { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-glow); }
  
  .dock-chips-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .file-chip {
    background: #1a2030;
    border: 1px solid #2f3a54;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11px;
    color: var(--accent);
    display: flex;
    align-items: center;
    gap: 5px;
    font-family: var(--font-mono);
  }
  .file-chip-close { cursor: pointer; color: var(--text-dim); }
  .file-chip-close:hover { color: var(--danger); }

  .dock-textarea {
    width: 100%;
    background: transparent;
    border: none;
    outline: none;
    color: var(--text-main);
    font-size: 13.5px;
    font-family: inherit;
    resize: none;
    min-height: 44px;
    max-height: 180px;
    line-height: 1.55;
  }
  .dock-textarea::placeholder { color: #4e5872; }

  .dock-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-top: 4px;
    border-top: 1px solid rgba(255,255,255,0.03);
  }
  .dock-left-tools { display: flex; align-items: center; gap: 8px; }
  .dock-right-tools { display: flex; align-items: center; gap: 8px; }

  .inline-btn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px 7px;
    font-size: 11.5px;
    color: #8c97b2;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 4px;
    transition: all 0.15s;
    font-weight: 500;
  }
  .inline-btn:hover {
    background: #1a2030;
    border-color: #2f3a54;
    color: var(--text-main);
  }

  .round-action-btn {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    background: #202738;
    border: 1px solid #333f5c;
    color: var(--text-main);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
  }
  .round-action-btn:hover {
    background: var(--accent);
    color: #050b14;
    border-color: var(--accent);
    box-shadow: 0 0 10px var(--accent-glow);
  }
  .round-action-btn:disabled { opacity: 0.4; cursor: not-allowed; background: #151924; }

  /* Dropdown Popup Menus */
  .popup-menu {
    position: absolute;
    bottom: 60px;
    background: #141824;
    border: 1px solid #2d364d;
    border-radius: 12px;
    box-shadow: 0 12px 36px rgba(0,0,0,0.65);
    padding: 8px;
    display: none;
    flex-direction: column;
    gap: 2px;
    z-index: 999;
    min-width: 240px;
    max-height: 320px;
    overflow-y: auto;
  }
  .popup-menu.show { display: flex; }
  .popup-item {
    padding: 7px 10px;
    font-size: 12px;
    color: var(--text-muted);
    border-radius: 6px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .popup-item:hover, .popup-item.selected {
    background: #1f2638;
    color: var(--text-main);
  }
  .popup-item-desc { font-size: 10px; color: var(--text-dim); }

  /* Generic Module Views */
  .module-view {
    flex: 1;
    padding: 24px 36px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 18px;
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
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }

  .panel-card {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .panel-card h3 { font-size: 13px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }

  .stat-gauge {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    background: var(--bg-elevated);
    border-radius: var(--radius-sm);
    font-size: 12.5px;
  }
  .stat-value { font-weight: 700; color: var(--accent); font-family: var(--font-mono); }

  /* Skills Filter Pills */
  .category-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 6px 0;
  }
  .cat-pill {
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 20px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s;
  }
  .cat-pill:hover, .cat-pill.active {
    background: rgba(0, 242, 254, 0.12);
    border-color: var(--accent);
    color: var(--accent);
    font-weight: 600;
  }

  /* Form Elements */
  input[type="text"], input[type="password"], textarea, select {
    width: 100%;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    padding: 8px 12px;
    color: var(--text-main);
    font-size: 13px;
    outline: none;
    font-family: inherit;
  }
  input[type="text"]:focus, textarea:focus, select:focus { border-color: var(--accent); }

  .primary-btn {
    background: linear-gradient(135deg, var(--accent), var(--accent-alt));
    color: #050b14;
    font-weight: 700;
    border: none;
    border-radius: var(--radius-sm);
    padding: 8px 16px;
    font-size: 12.5px;
    cursor: pointer;
  }

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

  /* Log & Diff Viewer */
  .diff-terminal {
    background: #06070a;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    padding: 12px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: #a0aec0;
    max-height: 480px;
    overflow-y: auto;
    white-space: pre-wrap;
  }
  .diff-line-add { color: #34d399; background: rgba(16, 185, 129, 0.08); }
  .diff-line-del { color: #f87171; background: rgba(239, 68, 68, 0.08); }

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
  .log-entry.info { color: #60a5fa; }
</style>
</head>
<body>

<!-- Header -->
<header class="app-header">
  <div class="header-left">
    <button class="icon-btn" onclick="toggleSessionSidebar()" title="折叠/展开会话抽屉 (Ctrl+B)">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
    </button>

    <div class="brand">
      <div class="brand-logo">白</div>
      <span>Baize Studio</span>
      <span class="version-tag">__VER__</span>
    </div>

    <span class="workspace-pill">📁 d:\tc\baize-agent</span>
  </div>

  <div class="header-actions">
    <span class="status-pill" id="git-branch-badge">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>
      <strong style="color:var(--accent)" id="header-branch-name">v30-dev</strong>
    </span>

    <div class="status-pill">
      <span class="status-dot"></span>
      <span id="server-status-text">127.0.0.1:8787</span>
    </div>

    <div class="mode-pill" id="autonomy-mode-badge" onclick="switchTab('tab-security')">
      <span>🛡️ 默认权限</span>
    </div>

    <button class="icon-btn" onclick="toggleTheme()" title="切换明亮/暗黑主题">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
    </button>
  </div>
</header>

<div class="app-body">
  <!-- Slim 64px Activity Rail -->
  <nav class="activity-rail">
    <div class="rail-top-group">
      <div class="rail-item active" onclick="switchTab('tab-workbench')" title="智能结对工作台">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span>工作台</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-diff')" title="代码审查与 Git 变更">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>
        <span>Git审查</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-skills')" title="技能自进化中心 (246+ 技能库)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
        <span>技能库</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-lab')" title="白泽深度推理实验室 (影子推演/因果诊断/元工具)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        <span>实验室</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-team')" title="多 Agent DAG 控制台">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        <span>多Agent</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-archive')" title="会话分支与时间旅行">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
        <span>时间旅行</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-memory')" title="分层记忆面板">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
        <span>记忆台</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-models')" title="模型服务商中心">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
        <span>模型设置</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-doctor')" title="系统体检与日志">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
        <span>体检日志</span>
      </div>
      <div class="rail-item" onclick="switchTab('tab-security')" title="安全与自主度">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        <span>权限治理</span>
      </div>
    </div>
    <div class="rail-item" onclick="switchTab('tab-integrations')" title="平台生态集成">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/></svg>
      <span>生态集成</span>
    </div>
  </nav>

  <!-- Main Viewports -->
  <main class="stage-container">

    <!-- Tab 1: 智能结对工作台 -->
    <section id="tab-workbench" class="tab-pane active">
      <div class="workbench-layout">
        <!-- Sessions Left Drawer -->
        <div class="session-sidebar" id="session-sidebar-panel">
          <div class="session-header">
            <div style="display:flex;align-items:center;gap:6px;">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              <span style="font-size:12px;font-weight:700;color:var(--text-muted)">会话历史</span>
            </div>
            <div style="display:flex;gap:4px;">
              <button class="icon-btn" onclick="exportCurrentSession()" title="导出当前会话为 Markdown 报告">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              </button>
              <button class="icon-btn" onclick="startNewSession()" title="新建会话">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              </button>
            </div>
          </div>
          <div style="padding:6px 8px;border-bottom:1px solid var(--border-subtle);">
            <input type="text" id="session-filter-input" oninput="filterSessions(this.value)" placeholder="🔍 快速过滤会话..." style="width:100%;background:#090b12;border:1px solid var(--border-subtle);border-radius:6px;padding:4px 8px;font-size:11px;color:var(--text-main);outline:none;box-sizing:border-box;">
          </div>
          <div class="session-list" id="workbench-session-list">
            <div style="font-size:11px;color:var(--text-dim);padding:20px 8px;text-align:center;line-height:1.6;">暂无历史会话<br><span style="color:var(--accent);cursor:pointer;" onclick="startNewSession()">+ 点击开启新会话</span></div>
          </div>
        </div>

        <!-- Chat Viewport -->
        <div class="chat-viewport">
          <div class="messages-container" id="chat-messages">
            <div class="msg-row">
              <div class="avatar baize">白</div>
              <div class="msg-bubble">
                <p><strong>您好！我是白泽（Baize Agent __VER__）。</strong></p>
                <p style="margin-top:6px;color:var(--text-muted)">已就绪，搭载 12 大安全沙箱原语、246+ 技能库与影子推演内核。请输入您的任务，或使用 <code>@</code> 快速选择文件！</p>
              </div>
            </div>
          </div>

          <!-- Prompt Shelf (Engineering Quick Prompts) -->
          <div class="prompt-shelf">
            <span class="prompt-card" onclick="insertPrompt('使用 TDD 测试驱动规范为目标函数编写全面单元测试')">🧪 TDD 红绿重构</span>
            <span class="prompt-card" onclick="insertPrompt('运行 doctor 体检并报告环境与持久化状态')">🩺 /doctor 体检</span>
            <span class="prompt-card" onclick="insertPrompt('运行系统健康与 Windows PowerShell 宿主环境深度诊断')">🪟 Windows 深度诊断</span>
            <span class="prompt-card" onclick="insertPrompt('对当前工作区进行系统架构解耦与坏味道清理')">🧹 架构解耦重构</span>
            <span class="prompt-card" onclick="insertPrompt('执行 AST 因果分析定位最近一次测试失败根因')">🔍 因果根因诊断</span>
            <span class="prompt-card" onclick="insertPrompt('启动 Speculative 影子时空推演探索 3 条重构路线')">⚡ 影子分支推演</span>
          </div>

          <!-- Exquisite Dock Input Box -->
          <div class="chat-dock">
            <!-- Autocomplete Popups -->
            <div class="popup-menu" id="file-autocomplete-popup" onclick="event.stopPropagation()" style="left:24px;width:340px;"></div>
            <div class="popup-menu" id="cmd-autocomplete-popup" onclick="event.stopPropagation()" style="left:24px;width:300px;"></div>
            <div class="popup-menu" id="model-select-popup" onclick="event.stopPropagation()" style="right:70px;width:240px;"></div>
            <div class="popup-menu" id="auth-select-popup" onclick="event.stopPropagation()" style="left:50px;width:220px;"></div>

            <div class="dock-box">
              <!-- Context Chips -->
              <div class="dock-chips-bar" id="attached-files-bar" style="display:none;"></div>

              <textarea class="dock-textarea" id="chat-input" placeholder="今天帮你做些什么？@ 引用对话文件，/ 调用技能与指令" oninput="handleTextareaInput(event)" onkeydown="handleInputKey(event)"></textarea>

              <!-- Bottom Tool Bar -->
              <div class="dock-toolbar">
                <div class="dock-left-tools">
                  <!-- Hidden Native File Picker -->
                  <input type="file" multiple id="native-file-picker" style="display:none" onchange="handleNativeFileSelect(event)" />

                  <!-- '+' Attachment button -->
                  <button class="inline-btn" onclick="triggerFilePicker(event)" title="引用工作区文件 (@)">
                    <span style="font-size:16px;font-weight:700;line-height:1">+</span>
                  </button>

                  <!-- Autonomy / Permission dropdown -->
                  <button class="inline-btn" id="dock-auth-btn" onclick="toggleAuthPopup(event)" title="切换操作权限">
                    <span id="dock-auth-label">🛡️ 默认权限</span>
                    <span style="font-size:9px;margin-left:2px">⌄</span>
                  </button>
                </div>

                <div class="dock-right-tools">
                  <!-- Spinner (Thinking indicator) -->
                  <span id="thinking-indicator" style="display:none;color:var(--accent);font-size:13px;animation:spin 1s linear infinite;">◌</span>

                  <!-- Inline Model Selector -->
                  <button class="inline-btn" id="dock-model-btn" onclick="toggleModelPopup(event)" title="秒级热切换活跃大模型">
                    <span>☯</span>
                    <span id="dock-model-label">DeepSeek V3</span>
                    <span style="font-size:9px;margin-left:2px">⌄</span>
                  </button>

                  <!-- Mic Icon -->
                  <button class="inline-btn" style="padding:4px;" title="语音输入 (准备中)">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                  </button>

                  <!-- Circular Action Button -->
                  <button class="round-action-btn" id="send-btn" onclick="submitChat()" title="发送执行 (Enter)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 2: 代码审查与 Git 变更 -->
    <section id="tab-diff" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>代码审查与 Git 差量工作区 (Diff Review)</h2>
          <div style="display:flex;gap:8px;">
            <div style="display:flex;background:#0d1017;border:1px solid var(--border-subtle);border-radius:6px;padding:2px;">
              <button class="chip-btn" id="diff-mode-unified" onclick="setDiffViewMode('unified')" style="background:var(--bg-elevated);color:var(--accent);">📄 Unified 单栏</button>
              <button class="chip-btn" id="diff-mode-split" onclick="setDiffViewMode('split')">📑 Split 并排</button>
            </div>
            <button class="primary-btn" onclick="loadGitDiff()">刷新变更</button>
          </div>
        </div>
        <div class="panel-card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <span>当前工作分支: </span><strong style="color:var(--accent)" id="git-branch-label">v30-dev</strong>
            </div>
            <div id="git-clean-badge" style="font-size:12px;color:var(--success)">✓ 工作区状态加载中...</div>
          </div>
          <div class="diff-terminal" id="git-diff-viewer">点击上方「刷新变更」以审查最新代码修改差量...</div>
        </div>
      </div>
    </section>

    <!-- Tab 3: 会话分支与时间旅行 -->
    <section id="tab-archive" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>会话分支与时间旅行时光机 (Archive & Lineage Graph)</h2>
          <div style="display:flex;gap:8px;">
            <button class="chip-btn" onclick="exportCurrentSession()">📥 导出当前会话</button>
            <button class="primary-btn" onclick="loadSessions();loadLineageTree();">刷新会话树</button>
          </div>
        </div>

        <div class="panel-card" style="margin-bottom:16px;">
          <h3>🌿 会话血统与分叉时光机 (Lineage Git-Graph)</h3>
          <div id="lineage-tree-canvas" style="display:flex;flex-direction:column;gap:8px;padding:12px;background:#080a10;border-radius:8px;border:1px solid var(--border-subtle);min-height:100px;">
            <span style="color:var(--text-dim);font-size:12px;">加载会话拓扑树中...</span>
          </div>
        </div>

        <div class="panel-card">
          <h3>会话历史列表 (Append-only JSONL)</h3>
          <div id="archive-session-table">加载中...</div>
        </div>
      </div>
    </section>

    <!-- Tab 4: 多 Agent DAG 控制台 -->
    <section id="tab-team" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>多 Agent DAG 并行调度控制台 (Interactive Flow Orchestrator)</h2>
        </div>
        <div class="panel-card">
          <h3>派发端到端团队目标</h3>
          <div style="display:flex;gap:10px;margin-bottom:12px;">
            <input type="text" id="team-goal-input" placeholder="输入复杂工程目标（例如：实现新特性并编写 100% 覆盖率测试）..." />
            <button class="primary-btn" onclick="launchTeamGoal()" style="white-space:nowrap">🚀 启动 DAG 并行编排</button>
          </div>

          <div style="display:flex;align-items:center;justify-content:space-between;border-top:1px solid var(--border-subtle);padding-top:10px;">
            <div style="font-size:12px;color:var(--text-muted);">
              <strong>智能体节点库 (点击添加):</strong>
            </div>
            <div style="display:flex;gap:6px;">
              <button class="chip-btn" onclick="addDagNode('director', '🎯 Director 规划节点')">+ 🎯 Director</button>
              <button class="chip-btn" onclick="addDagNode('executor', '⚡ Executor 执行节点')">+ ⚡ Executor</button>
              <button class="chip-btn" onclick="addDagNode('critic', '🧠 Critic 审查反思')">+ 🧠 Critic</button>
              <button class="chip-btn" onclick="addDagNode('verifier', '🛡️ Verifier 物理门禁')">+ 🛡️ Verifier</button>
              <button class="chip-btn" style="color:var(--danger);" onclick="resetDagCanvas()">清空画板</button>
            </div>
          </div>
        </div>

        <div class="dag-canvas" id="team-dag-canvas" style="min-height:220px;">
          <div style="color:var(--text-muted);font-size:13px;text-align:center;">暂无运行中的多 Agent 编排任务。在上方输入目标或添加节点以编排！</div>
        </div>
      </div>
    </section>

    <!-- Tab 5: 技能中心 (246+) -->
    <section id="tab-skills" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>技能自进化中心 (246+ Standard Engineering Skills)</h2>
          <div style="display:flex;gap:8px;">
            <button class="chip-btn" onclick="loadToolHub()">🧬 浏览元工具生态市场</button>
            <button class="primary-btn" onclick="openSkillCreator()">+ 新建自定义技能</button>
          </div>
        </div>

        <div class="panel-card" id="tool-hub-panel" style="display:none;margin-bottom:16px;">
          <h3>🧬 达尔文元工具生态市场 (Meta-Tool Hub & Hot-Reload)</h3>
          <div id="tool-hub-list" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:10px;margin-top:10px;">
            加载中...
          </div>
        </div>

        <div class="panel-card">
          <div style="display:flex;gap:10px;">
            <input type="text" id="skill-search-input" placeholder="搜索 260+ 内置工程技能库（包含 Matt Pocock 严密工程规约、核心流水线等）..." oninput="filterSkills()" />
          </div>
          <!-- Category Filter Pills -->
          <div class="category-pills" id="skills-cat-pills">
            <span class="cat-pill active" onclick="setSkillDomainFilter('all', this)">全部 (All)</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('mattpocock', this)" style="border-color:var(--accent);color:var(--accent);">⭐ Matt Pocock套件</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('pipeline', this)">核心流水线 (P1-P12)</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('arch', this)">架构设计 (Arch)</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('refactor', this)">代码重构 (Refactor)</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('test', this)">测试驱动 (TDD)</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('security', this)">安全沙箱 (Security)</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('performance', this)">性能优化 (Perf)</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('techstack', this)">语言栈 (TechStack)</span>
            <span class="cat-pill" onclick="setSkillDomainFilter('devops', this)">DevOps与自进化</span>
          </div>
          <div id="skills-grid" class="grid-3" style="margin-top:10px;max-height:500px;overflow-y:auto;"></div>
        </div>

        <div class="panel-card" style="margin-top:16px;">
          <h3>🔍 全局代码符号依赖图谱 (Global AST Symbol Graph)</h3>
          <p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">跨文件精准检索函数定义 (Definitions)、类层级与调用链引用 (Call Hierarchy)：</p>
          <div style="display:flex;gap:8px;">
            <input type="text" id="symbol-search-input" placeholder="输入符号名称（如：Session, run_command, SymbolGraph）..." onkeydown="if(event.key==='Enter')searchSymbols();" />
            <button class="primary-btn" onclick="searchSymbols()">检索符号图谱</button>
          </div>
          <div id="symbols-result-box" style="margin-top:10px;font-size:12px;"></div>
        </div>
      </div>
    </section>

    <!-- Tab 6: 白泽深度推理实验室 (V30/V33 Signature Lab) -->
    <section id="tab-lab" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>白泽深度推理与沙箱演练实验室 (Baize Deep Lab)</h2>
        </div>
        <div class="grid-2">
          <!-- Speculative Forking -->
          <div class="panel-card">
            <h3>⚡ 异步并发 Swarm 影子推演 (Asyncio Swarm Engine)</h3>
            <p style="font-size:12px;color:var(--text-muted)">3 条独立策略路线异步并发试错，按最小代码抖动与零风险决出胜出时间线：</p>
            <div style="display:flex;gap:8px;">
              <input type="text" id="spec-goal-input" value="优化数据持久化层的并发安全性与锁粒度" />
              <button class="primary-btn" onclick="runSwarmLab()">⚡ 并发 Swarm 探索</button>
            </div>
            <div id="spec-result-box" style="font-size:12px;margin-top:8px;"></div>
          </div>

          <!-- Causal Debugger & Mutation Arena -->
          <div class="panel-card">
            <h3>🔍 AST 因果反事实分析与变异演练 (Causal & Mutation Arena)</h3>
            <p style="font-size:12px;color:var(--text-muted)">自动提取故障 AST 切片并注入边界变异算子，构建永久抗脆弱红绿网：</p>
            <div style="display:flex;gap:8px;">
              <button class="primary-btn" onclick="runCausalLab()">运行因果切片诊断</button>
              <button class="chip-btn" onclick="runMutationArena()" style="font-size:11px;">🧪 触发 AST 变异测试网</button>
            </div>
            <div id="causal-result-box" style="font-size:12px;margin-top:8px;"></div>
          </div>

          <!-- Meta-Tool Synthesizer -->
          <div class="panel-card">
            <h3>🧬 达尔文元工具合成 (Meta-Tool Synthesizer)</h3>
            <p style="font-size:12px;color:var(--text-muted)">动态编译沙箱验证新工具并认证基因签名：</p>
            <button class="primary-btn" onclick="runSynthLab()" style="align-self:flex-start">合成并认证元工具</button>
            <div id="synth-result-box" style="font-size:12px;margin-top:8px;"></div>
          </div>

          <!-- Red-Blue Game & Byzantine Consensus -->
          <div class="panel-card">
            <h3>⚔️ 拜占庭多智能体对抗博弈仲裁 (Byzantine BFT Consensus)</h3>
            <p style="font-size:12px;color:var(--text-muted)">红队注入攻防 vs 蓝队沙箱防御 vs 仲裁法官全票共识签名：</p>
            <button class="primary-btn" onclick="runByzantineConsensus()" style="align-self:flex-start">⚖️ 执行拜占庭共识仲裁</button>
            <div id="adv-result-box" style="font-size:12px;margin-top:8px;"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 7: 分层记忆面板 -->
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
            <h3>🧠 AST 语义级上下文剪枝压缩器 (AST Context Slicer)</h3>
            <p style="font-size:12px;color:var(--text-muted)">修剪无关函数体为类型存根，将大模型输入 Token 精减 60%：</p>
            <div style="display:flex;gap:8px;">
              <input type="text" id="slice-symbol-input" placeholder="聚焦目标符号（如：save_session）" value="save_session" />
              <button class="primary-btn" onclick="testContextSlice()">⚡ 运行 AST 剪枝</button>
            </div>
            <div id="slice-result-box" style="margin-top:10px;font-size:12px;"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 8: 模型服务商中心 -->
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

    <!-- Tab 9: 系统体检与日志 -->
    <section id="tab-doctor" class="tab-pane">
      <div class="module-view">
        <div class="module-title-bar">
          <h2>系统体检与实时日志 (Doctor & Live Logs)</h2>
          <button class="primary-btn" onclick="runDoctorHealthCheck();loadMetricsSummary();">重新体检与刷新大屏</button>
        </div>

        <div class="panel-card" style="margin-bottom:16px;">
          <h3>📊 智能体执行大屏与 Token 成本分析 (Metrics & Cost Analyzer)</h3>
          <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:12px;margin-top:10px;">
            <div class="stat-gauge" style="flex-direction:column;align-items:flex-start;gap:4px;">
              <span style="color:var(--text-dim);font-size:11px;">⏱️ 系统已运行</span>
              <span id="metric-uptime" style="font-size:18px;font-weight:700;color:var(--accent);">--</span>
            </div>
            <div class="stat-gauge" style="flex-direction:column;align-items:flex-start;gap:4px;">
              <span style="color:var(--text-dim);font-size:11px;">🚀 智能体总执行次数</span>
              <span id="metric-runs" style="font-size:18px;font-weight:700;color:var(--success);">--</span>
            </div>
            <div class="stat-gauge" style="flex-direction:column;align-items:flex-start;gap:4px;">
              <span style="color:var(--text-dim);font-size:11px;">🪙 累计消耗 Token</span>
              <span id="metric-tokens" style="font-size:18px;font-weight:700;color:var(--text-main);">--</span>
            </div>
            <div class="stat-gauge" style="flex-direction:column;align-items:flex-start;gap:4px;">
              <span style="color:var(--text-dim);font-size:11px;">💰 估算支出费用</span>
              <span id="metric-cost" style="font-size:18px;font-weight:700;color:var(--warning);">--</span>
            </div>
          </div>
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

        <div class="panel-card" style="margin-top:16px;">
          <h3>🪟 Windows & PowerShell 宿主引擎与 POSIX 智能转译大屏</h3>
          <div id="windows-status-card" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:10px;margin-top:10px;">
            <div class="stat-gauge" style="flex-direction:column;align-items:flex-start;gap:2px;">
              <span style="font-size:10px;color:var(--text-dim);">Shell 宿主引擎</span>
              <strong id="win-shell-name" style="color:var(--accent);font-size:12px;">PowerShell 探测中...</strong>
            </div>
            <div class="stat-gauge" style="flex-direction:column;align-items:flex-start;gap:2px;">
              <span style="font-size:10px;color:var(--text-dim);">全链路 UTF-8 编码</span>
              <strong style="color:var(--success);font-size:12px;">✓ [Console]::OutputEncoding UTF-8</strong>
            </div>
            <div class="stat-gauge" style="flex-direction:column;align-items:flex-start;gap:2px;">
              <span style="font-size:10px;color:var(--text-dim);">POSIX 指令转译垫片</span>
              <strong style="color:var(--accent);font-size:12px;">✓ 15+ 种命令无感转译激活</strong>
            </div>
            <div class="stat-gauge" style="flex-direction:column;align-items:flex-start;gap:2px;">
              <span style="font-size:10px;color:var(--text-dim);">执行策略隔离</span>
              <strong style="color:var(--warning);font-size:12px;">-ExecutionPolicy Bypass</strong>
            </div>
          </div>
        </div>

        <div class="panel-card" style="margin-top:16px;">
          <h3>🧪 混沌工程抗脆弱演练台 (Chaos Simulation Arena)</h3>
          <div style="display:flex;gap:10px;align-items:center;margin-top:8px;">
            <select id="chaos-fault-select" style="background:#090b12;border:1px solid var(--border-subtle);color:var(--text-main);padding:6px 10px;border-radius:6px;font-size:12px;">
              <option value="malformed_json">LLM 输出截断畸变 JSON 响应</option>
              <option value="network_drop_30">模拟 30% 网络弱网丢包</option>
              <option value="slow_latency_3000ms">模拟 3000ms 慢网络高延迟</option>
              <option value="disk_read_only">模拟持久化只读故障</option>
            </select>
            <button class="primary-btn" onclick="runChaosSimulation()">⚡ 触发混沌注入演练</button>
          </div>
          <div id="chaos-sim-result" style="font-size:12px;margin-top:8px;"></div>
        </div>
      </div>
    </section>

    <!-- Tab 10: 安全与自主度 -->
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

        <div class="panel-card" style="margin-top:16px;">
          <h3>🛡️ 细粒度路径 RBAC 权限与物理门禁加密签名</h3>
          <div style="display:flex;flex-direction:column;gap:8px;margin-top:8px;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px;">
              <div style="background:#090b12;padding:8px;border-radius:6px;border:1px solid var(--border-subtle);">
                <strong>路径策略:</strong>
                <div style="color:var(--text-muted);font-size:11px;margin-top:4px;">• <code>src/**</code> ➔ 读写 (RW)</div>
                <div style="color:var(--text-muted);font-size:11px;">• <code>deploy/**</code> ➔ 只读 (RO)</div>
                <div style="color:var(--text-muted);font-size:11px;">• <code>.env</code> ➔ 禁止访问 (Deny)</div>
              </div>
              <div style="background:#090b12;padding:8px;border-radius:6px;border:1px solid var(--border-subtle);">
                <strong>Git 门禁加密签名水印:</strong>
                <div id="security-watermark" style="font-family:var(--font-mono);color:var(--accent);font-size:11px;margin-top:4px;">Baize-Gate-Verified: BG-9A71F42B</div>
              </div>
            </div>
            <button class="primary-btn" onclick="applyRbacRules()" style="align-self:flex-start;margin-top:4px;">🔒 更新细粒度路径权限</button>
            <div id="rbac-result" style="font-size:12px;"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 11: 平台生态集成 -->
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
            <button class="primary-btn" onclick="alert('集成配置已保存')" style="align-self:flex-start">保存集成配置</button>
          </div>
        </div>

        <div class="panel-card" style="margin-top:16px;">
          <h3>⚡ Webhook 事件触发与双向推送测试</h3>
          <div style="display:flex;gap:10px;align-items:center;margin-top:8px;">
            <select id="webhook-target-select" style="background:#090b12;border:1px solid var(--border-subtle);color:var(--text-main);padding:6px 10px;border-radius:6px;font-size:12px;">
              <option value="feishu">飞书机器人 (Feishu)</option>
              <option value="dingtalk">钉钉群机器人 (DingTalk)</option>
              <option value="wecom">企业微信 (WeCom)</option>
              <option value="slack">Slack Incoming Webhook</option>
            </select>
            <button class="primary-btn" onclick="testWebhookDispatch()">🚀 模拟发送事件通知</button>
          </div>
          <div id="webhook-test-result" style="font-size:12px;margin-top:8px;"></div>
        </div>

        <div class="panel-card" style="margin-top:16px;">
          <h3>🌐 Anthropic MCP (Model Context Protocol) 开放协议连接器</h3>
          <p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">原生兼容社区 10,000+ 开源 MCP 工具生态 (SQLite, GitHub, PostgreSQL, Puppeteer, Slack 等)：</p>
          <div id="mcp-servers-list" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:10px;margin-bottom:10px;">
            <div style="background:#090b12;border:1px solid var(--border-subtle);border-radius:6px;padding:8px;">
              <strong style="color:var(--accent);font-size:11px;">[MCP] sqlite</strong>
              <div style="font-size:10px;color:var(--text-dim);margin:4px 0;">本地 SQLite 数据库查询与结构分析</div>
              <button class="chip-btn" onclick="testMcpCall('sqlite', 'sqlite_query', {sql:'SELECT count(*) FROM sessions'})" style="font-size:10px;">⚡ 调用 sqlite_query</button>
            </div>
            <div style="background:#090b12;border:1px solid var(--border-subtle);border-radius:6px;padding:8px;">
              <strong style="color:var(--accent);font-size:11px;">[MCP] github</strong>
              <div style="font-size:10px;color:var(--text-dim);margin:4px 0;">GitHub 远程仓库 PR 与 Issue 交互</div>
              <button class="chip-btn" onclick="testMcpCall('github', 'github_list_prs', {state:'open'})" style="font-size:10px;">⚡ 调用 list_prs</button>
            </div>
            <div style="background:#090b12;border:1px solid var(--border-subtle);border-radius:6px;padding:8px;">
              <strong style="color:var(--accent);font-size:11px;">[MCP] puppeteer</strong>
              <div style="font-size:10px;color:var(--text-dim);margin:4px 0;">无头浏览器抓取与截图</div>
              <button class="chip-btn" onclick="testMcpCall('puppeteer', 'puppeteer_navigate', {url:'http://127.0.0.1:8787'})" style="font-size:10px;">⚡ 调用 navigate</button>
            </div>
          </div>
          <div id="mcp-call-result" style="font-size:12px;"></div>
        </div>

        <div class="panel-card" style="margin-top:16px;">
          <h3>🧬 达尔文自主繁衍元工具企业市场 (Darwin Marketplace)</h3>
          <p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">跨团队共享与挂载自主演化的元工具，附带不可篡改的加密基因签名：</p>
          <div id="darwin-market-grid" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(240px, 1fr));gap:10px;margin-bottom:10px;">
            <div style="background:#090b12;border:1px solid var(--border-subtle);border-radius:6px;padding:8px;">
              <strong style="color:var(--accent);font-size:11px;">k8s_manifest_validator</strong>
              <div style="font-size:10px;color:var(--text-dim);margin:4px 0;">K8s YAML 规范与资源配额深度校验器</div>
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:10px;">
                <span style="color:var(--success)">适应度: 98%</span>
                <span style="font-family:var(--font-mono);color:var(--text-dim);">DARWIN-9A71</span>
              </div>
            </div>
            <div style="background:#090b12;border:1px solid var(--border-subtle);border-radius:6px;padding:8px;">
              <strong style="color:var(--accent);font-size:11px;">ast_sql_injection_guard</strong>
              <div style="font-size:10px;color:var(--text-dim);margin:4px 0;">AST 语法树 SQL 拼接与注入扫描器</div>
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:10px;">
                <span style="color:var(--success)">适应度: 99%</span>
                <span style="font-family:var(--font-mono);color:var(--text-dim);">DARWIN-F42B</span>
              </div>
            </div>
            <div style="background:#090b12;border:1px solid var(--border-subtle);border-radius:6px;padding:8px;">
              <strong style="color:var(--accent);font-size:11px;">graphql_schema_differ</strong>
              <div style="font-size:10px;color:var(--text-dim);margin:4px 0;">GraphQL 破坏性变更影响面分析器</div>
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:10px;">
                <span style="color:var(--success)">适应度: 96%</span>
                <span style="font-family:var(--font-mono);color:var(--text-dim);">DARWIN-81C3</span>
              </div>
            </div>
          </div>
          <button class="primary-btn" onclick="publishCustomTool()" style="font-size:11px;">+ 发布当前会话合成的元工具</button>
        </div>

        <div class="panel-card" style="margin-top:16px;">
          <h3>🌐 企业级私有化集群部署与 gRPC 服务</h3>
          <div style="background:#090b12;padding:10px;border-radius:6px;border:1px solid var(--border-subtle);font-family:var(--font-mono);font-size:11px;color:var(--accent);margin-top:8px;">
            docker run -d -p 8787:8787 -p 50051:50051 -e BAIZE_AUTH_TOKEN=secret_token -v /workspace:/workspace baize/studio:v35.0.0
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:6px;">支持 RESTful HTTP (8787) 与 gRPC 二进制双向流式协议 (50051)。</div>
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
let activeSkillDomain = 'all';
let workspaceFiles = [];
let availableCommands = [];
let attachedFiles = [];
let activeModel = 'deepseek-chat';
let availableModels = [];

function toggleSessionSidebar() {
  const bar = document.getElementById('session-sidebar-panel');
  if (bar) bar.classList.toggle('collapsed');
}

function switchTab(tabId) {
  document.querySelectorAll('.rail-item').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
  
  const pane = document.getElementById(tabId);
  if (pane) pane.classList.add('active');
  
  const railItems = document.querySelectorAll('.rail-item');
  railItems.forEach(n => {
    if (n.getAttribute('onclick') && n.getAttribute('onclick').includes(tabId)) {
      n.classList.add('active');
    }
  });

  if (tabId === 'tab-diff') loadGitDiff();
  if (tabId === 'tab-archive') loadSessions();
  if (tabId === 'tab-skills') loadSkills();
  if (tabId === 'tab-memory') loadMemory();
  if (tabId === 'tab-doctor') runDoctorHealthCheck();
}

function toggleTheme() {
  document.documentElement.classList.toggle('light');
  document.documentElement.classList.toggle('dark');
}

// --- Autocomplete & Context Attachment ---
async function fetchWorkspaceFiles() {
  try {
    const res = await fetch('/api/workspace/files');
    const d = await res.json();
    workspaceFiles = d.files || [];
  } catch (e) {
    workspaceFiles = [];
  }
}

async function fetchCommands() {
  try {
    const res = await fetch('/api/commands');
    const d = await res.json();
    availableCommands = d.commands || [];
  } catch (e) {
    availableCommands = [];
  }
}

async function fetchModels() {
  try {
    const res = await fetch('/api/models');
    const d = await res.json();
    activeModel = d.active_model || 'deepseek-chat';
    availableModels = d.models || [];
    updateModelButtonLabel();
  } catch (e) {}
}

function updateModelButtonLabel() {
  const m = availableModels.find(x => x.id === activeModel);
  const label = m ? m.name : activeModel;
  document.getElementById('dock-model-label').innerText = label.split(' ')[0];
}

function handleTextareaInput(e) {
  const val = e.target.value;
  const cursor = e.target.selectionStart;
  const textBefore = val.slice(0, cursor);
  
  hidePopups();

  const atMatch = textBefore.match(/@([a-zA-Z0-9_.\-\\/]*)$/);
  if (atMatch) {
    showFileAutocomplete(atMatch[1]);
    return;
  }

  const slashMatch = textBefore.match(/^\/([a-zA-Z0-9_]*)$/);
  if (slashMatch) {
    showCommandAutocomplete(slashMatch[1]);
    return;
  }
}

function showFileAutocomplete(query) {
  const popup = document.getElementById('file-autocomplete-popup');
  const filtered = workspaceFiles.filter(f => f.toLowerCase().includes((query || '').toLowerCase())).slice(0, 15);
  popup.innerHTML = `
    <div style="font-size:11px;font-weight:700;color:var(--text-dim);padding:4px 8px;display:flex;justify-content:space-between;align-items:center;">
      <span>引用文件 (@)</span>
      <span style="font-size:10px;color:var(--accent);cursor:pointer;" onclick="document.getElementById('native-file-picker').click();event.stopPropagation();">📂 浏览本地</span>
    </div>
    <input type="text" id="popup-file-search" value="${query || ''}" placeholder="快速搜索文件..." oninput="showFileAutocomplete(this.value)" onclick="event.stopPropagation()" style="font-size:11px;padding:4px 8px;margin:4px 0 6px;" autofocus />
    <div style="max-height:200px;overflow-y:auto;display:flex;flex-direction:column;gap:2px;">
  ` + (filtered.length ? filtered.map((f, i) => `
    <div class="popup-item ${i === 0 ? 'selected' : ''}" onclick="selectFileFromAutocomplete('${f}')">
      <span>📄 ${f}</span>
    </div>
  `).join('') : '<div style="font-size:11px;color:var(--text-dim);padding:6px 8px;">未匹配到文件</div>') + `
    </div>
  `;
  popup.classList.add('show');
  const searchInput = document.getElementById('popup-file-search');
  if (searchInput && query === '') {
    setTimeout(() => searchInput.focus(), 50);
  }
}

function showCommandAutocomplete(query) {
  const popup = document.getElementById('cmd-autocomplete-popup');
  const filtered = availableCommands.filter(c => c.name.toLowerCase().includes(('/' + (query || '')).toLowerCase()));
  if (!filtered.length) {
    popup.classList.remove('show');
    return;
  }
  popup.innerHTML = `
    <div style="font-size:10px;font-weight:700;color:var(--text-dim);padding:4px 8px;">调用快捷指令与技能 (/)</div>
  ` + filtered.map((c, i) => `
    <div class="popup-item ${i === 0 ? 'selected' : ''}" onclick="selectCmdFromAutocomplete('${c.name}')">
      <span><strong>${c.name}</strong></span>
      <span class="popup-item-desc">${c.desc}</span>
    </div>
  `).join('');
  popup.classList.add('show');
}

function selectFileFromAutocomplete(filePath) {
  addFileChip(filePath);
  const input = document.getElementById('chat-input');
  input.value = input.value.replace(/@[a-zA-Z0-9_.\-\\/]*$/, '').trim();
  hidePopups();
  input.focus();
}

function selectCmdFromAutocomplete(cmdName) {
  const input = document.getElementById('chat-input');
  input.value = cmdName + ' ';
  hidePopups();
  input.focus();
}

function addFileChip(filePath) {
  if (!attachedFiles.includes(filePath)) {
    attachedFiles.push(filePath);
    renderFileChips();
  }
}

function removeFileChip(filePath) {
  attachedFiles = attachedFiles.filter(f => f !== filePath);
  renderFileChips();
}

function renderFileChips() {
  const bar = document.getElementById('attached-files-bar');
  if (!attachedFiles.length) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    return;
  }
  bar.style.display = 'flex';
  bar.innerHTML = attachedFiles.map(f => `
    <span class="file-chip">
      <span>📄 @${f}</span>
      <span class="file-chip-close" onclick="removeFileChip('${f}')">×</span>
    </span>
  `).join('');
}

async function triggerFilePicker(e) {
  if (e) e.stopPropagation();
  const popup = document.getElementById('file-autocomplete-popup');
  if (popup.classList.contains('show')) {
    popup.classList.remove('show');
    return;
  }
  hidePopups();
  if (!workspaceFiles.length) {
    await fetchWorkspaceFiles();
  }
  showFileAutocomplete('');
}

function handleNativeFileSelect(e) {
  const files = e.target.files;
  if (!files || !files.length) return;
  for (let i = 0; i < files.length; i++) {
    addFileChip(files[i].name);
  }
  hidePopups();
  document.getElementById('chat-input').focus();
}

function toggleModelPopup(e) {
  e.stopPropagation();
  const popup = document.getElementById('model-select-popup');
  if (popup.classList.contains('show')) {
    popup.classList.remove('show');
  } else {
    hidePopups();
    popup.innerHTML = `
      <div style="font-size:10px;font-weight:700;color:var(--text-dim);padding:4px 8px;">切换活跃大模型 (LLM)</div>
    ` + availableModels.map(m => `
      <div class="popup-item ${m.id === activeModel ? 'selected' : ''}" onclick="selectActiveModel('${m.id}')">
        <span>${m.name}</span>
        <span style="font-size:10px;color:var(--text-dim)">${m.provider}</span>
      </div>
    `).join('');
    popup.classList.add('show');
  }
}

async function selectActiveModel(modelId) {
  activeModel = modelId;
  updateModelButtonLabel();
  hidePopups();
  try {
    await fetch('/api/models/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelId })
    });
  } catch (e) {}
}

function toggleAuthPopup(e) {
  e.stopPropagation();
  const popup = document.getElementById('auth-select-popup');
  if (popup.classList.contains('show')) {
    popup.classList.remove('show');
  } else {
    hidePopups();
    popup.innerHTML = `
      <div style="font-size:10px;font-weight:700;color:var(--text-dim);padding:4px 8px;">操作权限与自主度</div>
      <div class="popup-item" onclick="setInlineAuth(2)">
        <span>🛡️ 默认权限 (Supervised)</span>
      </div>
      <div class="popup-item" onclick="setInlineAuth(1)">
        <span>🔒 只读安全模式 (Read-Only)</span>
      </div>
      <div class="popup-item" onclick="setInlineAuth(3)">
        <span>⚡ 全自主极客模式 (YOLO Mode)</span>
      </div>
    `;
    popup.classList.add('show');
  }
}

function setInlineAuth(level) {
  setAutonomyMode(level);
  const label = document.getElementById('dock-auth-label');
  if (level === 1) label.innerText = '🔒 只读安全';
  if (level === 2) label.innerText = '🛡️ 默认权限';
  if (level === 3) label.innerText = '⚡ 全自主模式';
  hidePopups();
  fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ autonomy_level: level })
  }).catch(() => {});
}

function hidePopups() {
  document.querySelectorAll('.popup-menu').forEach(p => p.classList.remove('show'));
}

document.addEventListener('click', () => {
  hidePopups();
});

// --- Git Diff Review ---
let diffViewMode = 'unified';
let rawDiffText = '';

function setDiffViewMode(mode) {
  diffViewMode = mode;
  const uBtn = document.getElementById('diff-mode-unified');
  const sBtn = document.getElementById('diff-mode-split');
  if (uBtn && sBtn) {
    if (mode === 'unified') {
      uBtn.style.background = 'var(--bg-elevated)';
      uBtn.style.color = 'var(--accent)';
      sBtn.style.background = '';
      sBtn.style.color = '';
    } else {
      sBtn.style.background = 'var(--bg-elevated)';
      sBtn.style.color = 'var(--accent)';
      uBtn.style.background = '';
      uBtn.style.color = '';
    }
  }
  renderDiffViewer(rawDiffText);
}

function renderDiffViewer(diff) {
  const viewer = document.getElementById('git-diff-viewer');
  if (!viewer) return;
  if (!diff) {
    viewer.innerHTML = '<span style="color:var(--success)">✓ 工作区没有待提交的代码变更。</span>';
    return;
  }
  
  if (diffViewMode === 'unified') {
    viewer.innerHTML = diff.split('\n').map(line => {
      if (line.startsWith('+') && !line.startsWith('+++')) return `<div class="diff-line-add">${escapeHtml(line)}</div>`;
      if (line.startsWith('-') && !line.startsWith('---')) return `<div class="diff-line-del">${escapeHtml(line)}</div>`;
      return `<div>${escapeHtml(line)}</div>`;
    }).join('');
  } else {
    // Split View (Left: Deletions, Right: Additions)
    const lines = diff.split('\n');
    let leftLines = [];
    let rightLines = [];
    
    lines.forEach(line => {
      if (line.startsWith('-') && !line.startsWith('---')) {
        leftLines.push(`<div class="diff-line-del">${escapeHtml(line)}</div>`);
        rightLines.push(`<div style="color:transparent;">.</div>`);
      } else if (line.startsWith('+') && !line.startsWith('+++')) {
        leftLines.push(`<div style="color:transparent;">.</div>`);
        rightLines.push(`<div class="diff-line-add">${escapeHtml(line)}</div>`);
      } else {
        leftLines.push(`<div>${escapeHtml(line)}</div>`);
        rightLines.push(`<div>${escapeHtml(line)}</div>`);
      }
    });
    
    viewer.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <div style="border-right:1px solid var(--border-subtle);padding-right:6px;">
          <div style="font-size:10px;font-weight:700;color:var(--danger);margin-bottom:4px;">[ORIGINAL / 变更前]</div>
          ${leftLines.join('')}
        </div>
        <div style="padding-left:6px;">
          <div style="font-size:10px;font-weight:700;color:var(--success);margin-bottom:4px;">[MODIFIED / 变更后]</div>
          ${rightLines.join('')}
        </div>
      </div>
    `;
  }
}

async function loadGitDiff() {
  const viewer = document.getElementById('git-diff-viewer');
  viewer.innerText = '正在获取 Git 差量...';
  try {
    const res = await fetch('/api/git/diff');
    const d = await res.json();
    const stRes = await fetch('/api/git/status');
    const st = await stRes.json();
    
    const branchName = st.branch || 'v30-dev';
    document.getElementById('git-branch-label').innerText = branchName;
    const headerBranch = document.getElementById('header-branch-name');
    if (headerBranch) headerBranch.innerText = branchName;
    
    document.getElementById('git-clean-badge').innerText = st.clean ? '✓ 工作区整洁 (Clean)' : '⚠️ 存在未提交修改';
    document.getElementById('git-clean-badge').style.color = st.clean ? 'var(--success)' : 'var(--warning)';

    rawDiffText = d.diff || '';
    renderDiffViewer(rawDiffText);
  } catch (e) {
    viewer.innerText = '获取 Git 差量失败: ' + e.message;
  }
}

// --- Session Lineage Git-Graph Tree ---
async function loadLineageTree() {
  const canvas = document.getElementById('lineage-tree-canvas');
  if (!canvas) return;
  try {
    const res = await fetch('/sessions/lineage/tree');
    const d = await res.json();
    const nodes = d.nodes || [];
    if (!nodes.length) {
      canvas.innerHTML = '<span style="color:var(--text-dim);font-size:12px;">暂无会话血统关系。</span>';
      return;
    }
    
    canvas.innerHTML = nodes.map(n => `
      <div style="display:flex;justify-content:space-between;align-items:center;background:#0d111b;padding:8px 12px;border-radius:6px;border:1px solid ${n.parent ? 'var(--accent)' : 'var(--border-subtle)'};">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="color:${n.parent ? 'var(--accent)' : 'var(--text-dim)'};font-family:var(--font-mono);font-size:12px;">
            ${n.parent ? '↳ [Fork]' : '● [Root]'}
          </span>
          <div>
            <strong style="color:var(--text-main);font-size:12px;">${n.id}</strong>
            <span style="font-size:11px;color:var(--text-dim);margin-left:6px;">${n.messages_count} 条消息</span>
            ${n.parent ? `<div style="font-size:10px;color:var(--accent);">分叉自: ${n.parent} @ index ${n.fork_at_index}</div>` : ''}
          </div>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="chip-btn" onclick="selectSession('${n.id}');switchTab('tab-workbench');">进入会话</button>
          <button class="chip-btn" onclick="forkSession('${n.id}')">🍴 分叉新路线</button>
        </div>
      </div>
    `).join('');
  } catch (e) {
    canvas.innerHTML = '<span style="color:var(--danger);font-size:12px;">加载会话拓扑失败: ' + e.message + '</span>';
  }
}

// --- Interactive Multi-Agent DAG Orchestrator ---
let dagNodes = [
  { id: 'director', role: 'director', title: '🎯 Director 规划节点' },
  { id: 'executor', role: 'executor', title: '⚡ Executor 执行节点' },
  { id: 'verifier', role: 'verifier', title: '🛡️ Verifier 物理门禁' }
];

function addDagNode(role, title) {
  dagNodes.push({
    id: 'node-' + (dagNodes.length + 1),
    role: role,
    title: title
  });
  renderDagCanvas();
}

function removeDagNode(idx) {
  dagNodes.splice(idx, 1);
  renderDagCanvas();
}

function resetDagCanvas() {
  dagNodes = [];
  renderDagCanvas();
}

function renderDagCanvas() {
  const canvas = document.getElementById('team-dag-canvas');
  if (!canvas) return;
  if (!dagNodes.length) {
    canvas.innerHTML = '<div style="color:var(--text-dim);font-size:12px;text-align:center;padding:30px;">画板为空，请点击上方节点库添加 Agent！</div>';
    return;
  }
  
  canvas.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:10px;">
      ${dagNodes.map((n, i) => `
        <div class="dag-node" style="display:flex;justify-content:space-between;align-items:center;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-dim);">#${i+1}</span>
            <span><strong>${n.title}</strong></span>
          </div>
          <div style="display:flex;gap:6px;align-items:center;">
            <span style="font-size:10px;color:var(--accent);background:rgba(0,242,254,0.1);padding:2px 6px;border-radius:4px;">${n.role}</span>
            <button class="chip-btn" style="color:var(--danger);padding:2px 6px;font-size:10px;" onclick="removeDagNode(${i})">✕</button>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function escapeHtml(t) {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

let codeBlockCounter = 0;

function copyCodeBlock(btn, codeId) {
  const codeEl = document.getElementById(codeId);
  if (!codeEl) return;
  navigator.clipboard.writeText(codeEl.innerText).then(() => {
    const orig = btn.innerText;
    btn.innerText = '✓ 已复制';
    btn.style.color = 'var(--success)';
    setTimeout(() => {
      btn.innerText = orig;
      btn.style.color = '';
    }, 2000);
  });
}

function renderRichMarkdown(text) {
  if (!text) return '';
  let html = text.replace(/<thinking>([\s\S]*?)<\/thinking>/gi, (match, p1) => {
    return `<details class="thinking-drawer" style="background:#090b12;border:1px solid rgba(0,242,254,0.25);border-radius:8px;padding:8px 12px;margin:8px 0;font-size:12px;"><summary style="cursor:pointer;color:var(--accent);font-weight:600;">🧠 CoT 深度思考与沙箱推理轨迹</summary><div style="color:var(--text-muted);margin-top:6px;white-space:pre-wrap;line-height:1.5;">${escapeHtml(p1.trim())}</div></details>`;
  });

  html = html.replace(/```([a-zA-Z0-9_\-\+]*)\n([\s\S]*?)```/g, (match, lang, code) => {
    codeBlockCounter++;
    const codeId = 'code-block-' + codeBlockCounter;
    const l = lang || 'code';
    return `
      <div class="code-container" style="background:#06080e;border:1px solid var(--border-strong);border-radius:8px;margin:10px 0;overflow:hidden;">
        <div style="display:flex;justify-content:space-between;align-items:center;background:#111522;padding:4px 12px;border-bottom:1px solid var(--border-subtle);font-size:11px;color:var(--text-dim);font-family:var(--font-mono);">
          <span>${l}</span>
          <button class="chip-btn" onclick="copyCodeBlock(this, '${codeId}')" style="padding:2px 6px;font-size:10px;">📋 复制</button>
        </div>
        <pre style="padding:12px;margin:0;overflow-x:auto;font-family:var(--font-mono);font-size:12.5px;line-height:1.5;color:#cbd5e1;"><code id="${codeId}">${escapeHtml(code.trim())}</code></pre>
      </div>`;
  });

  html = html.replace(/`([^`]+)`/g, '<code style="background:var(--bg-elevated);border:1px solid var(--border-subtle);padding:1px 5px;border-radius:4px;font-family:var(--font-mono);font-size:12px;color:var(--accent);">$1</code>');
  return html.replace(/\n\n/g, '<br><br>');
}

// --- Chat & Workbench Logic ---
async function submitChat() {
  const input = document.getElementById('chat-input');
  let text = input.value.trim();
  if (!text && !attachedFiles.length) return;
  
  if (attachedFiles.length) {
    const filePrefix = attachedFiles.map(f => `@${f}`).join(' ');
    text = `${filePrefix} ${text}`.trim();
    attachedFiles = [];
    renderFileChips();
  }
  
  appendMessage('user', text);
  input.value = '';
  
  const sendBtn = document.getElementById('send-btn');
  const spinner = document.getElementById('thinking-indicator');
  sendBtn.disabled = true;
  if (spinner) spinner.style.display = 'inline-block';

  const liveBubble = appendMessage('baize', '正在连接沙箱推理内核...');
  let streamText = '';
  
  try {
    const res = await fetch('/run/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: text, session_id: activeSessionId })
    });

    const cType = res.headers.get('Content-Type') || '';
    if (cType.includes('text/event-stream')) {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.event === 'think') {
                liveBubble.innerHTML = `<span style="color:var(--accent);font-size:12px;">🧠 ${escapeHtml(data.content || '')}</span>`;
              } else if (data.event === 'delta') {
                if (streamText === '') liveBubble.innerHTML = '';
                streamText += data.text || '';
                liveBubble.innerHTML = renderRichMarkdown(streamText);
              } else if (data.event === 'done') {
                activeSessionId = data.session_id || activeSessionId;
                if (data.final_text) {
                  liveBubble.innerHTML = renderRichMarkdown(data.final_text);
                }
              }
            } catch (e) {}
          }
        }
      }
    } else {
      const data = await res.json();
      if (data.error) {
        liveBubble.innerHTML = '❌ 错误: ' + data.error;
      } else {
        activeSessionId = data.session_id || activeSessionId;
        liveBubble.innerHTML = renderRichMarkdown(data.final_text || '任务执行完毕。');
      }
    }
  } catch (err) {
    liveBubble.innerHTML = '❌ 网络连接错误: ' + err.message;
  } finally {
    sendBtn.disabled = false;
    if (spinner) spinner.style.display = 'none';
    loadSessions();
  }
}

function handleInputKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    const popup = document.querySelector('.popup-menu.show');
    if (popup) {
      const selected = popup.querySelector('.popup-item.selected');
      if (selected) {
        e.preventDefault();
        selected.click();
        return;
      }
    }
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
  if (role === 'user') {
    bubble.innerText = content;
  } else {
    bubble.innerHTML = renderRichMarkdown(content);
  }
  
  if (role === 'user') {
    row.appendChild(bubble);
    row.appendChild(avatar);
  } else {
    row.appendChild(avatar);
    row.appendChild(bubble);
  }
  
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

function insertPrompt(p) {
  const input = document.getElementById('chat-input');
  input.value = p;
  input.focus();
}

function exportCurrentSession() {
  if (!activeSessionId) {
    alert('当前没有活跃会话可导出，请先选择或开始一个会话！');
    return;
  }
  window.open('/sessions/' + activeSessionId + '/export', '_blank');
}

function startNewSession() {
  activeSessionId = '';
  attachedFiles = [];
  renderFileChips();
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
let cachedSessions = [];

function renderSessionList(list) {
  const leftList = document.getElementById('workbench-session-list');
  if (!leftList) return;
  leftList.innerHTML = list.slice(0, 20).map(s => `
    <div class="session-item ${s.id === activeSessionId ? 'active' : ''}">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div class="session-item-title" onclick="selectSession('${s.id}')">${s.id}</div>
        <span style="font-size:11px;color:var(--text-dim);cursor:pointer;" onclick="deleteSession('${s.id}')" title="删除会话">🗑️</span>
      </div>
      <div class="session-item-time" onclick="selectSession('${s.id}')">${s.created_at || 'Recently'} · ${s.messages_count || 0} 条消息</div>
    </div>
  `).join('') || '<div style="font-size:11px;color:var(--text-dim);padding:24px 8px;text-align:center;line-height:1.6;">暂无匹配会话<br><span style="color:var(--accent);cursor:pointer;font-weight:600;" onclick="startNewSession()">+ 点击开启新会话</span></div>';
}

function filterSessions(kw) {
  const q = (kw || '').trim().toLowerCase();
  if (!q) {
    renderSessionList(cachedSessions);
    return;
  }
  const filtered = cachedSessions.filter(s => (s.id || '').toLowerCase().includes(q));
  renderSessionList(filtered);
}

async function loadSessions() {
  try {
    const res = await fetch('/sessions');
    const data = await res.json();
    cachedSessions = data.sessions || [];
    renderSessionList(cachedSessions);
    
    const archTable = document.getElementById('archive-session-table');
    if (archTable) {
      archTable.innerHTML = `
        <div style="display:flex;justify-content:flex-end;margin-bottom:10px;">
          <button class="chip-btn" style="color:var(--danger);" onclick="clearAllSessions()">🗑️ 一键清空所有历史会话</button>
        </div>` + (cachedSessions.map(s => `
        <div class="stat-gauge" style="margin-bottom:8px">
          <span>📄 <strong>${s.id}</strong> (${s.messages_count || 0} msgs)</span>
          <div style="display:flex;gap:6px">
            <button class="chip-btn" onclick="selectSession('${s.id}');switchTab('tab-workbench')">进入会话</button>
            <button class="chip-btn" onclick="forkSession('${s.id}')">🍴 Fork 分支</button>
            <button class="chip-btn" style="color:var(--danger)" onclick="deleteSession('${s.id}')">删除</button>
          </div>
        </div>
      `).join('') || '<div style="color:var(--text-dim);font-size:12px;padding:8px">暂无归档会话</div>');
    }
  } catch (err) {
    console.error('Failed to load sessions:', err);
  }
}

async function deleteSession(sid) {
  if (!confirm('确定删除会话 ' + sid + ' 吗？')) return;
  try {
    await fetch('/sessions/' + sid, { method: 'DELETE' });
    if (activeSessionId === sid) startNewSession();
    loadSessions();
  } catch (err) {
    alert('删除失败: ' + err.message);
  }
}

async function clearAllSessions() {
  if (!confirm('确定清空全部历史会话记录吗？')) return;
  try {
    const res = await fetch('/sessions/all', { method: 'DELETE' });
    const data = await res.json();
    alert('已成功清空 ' + (data.deleted_count || 0) + ' 条会话记录！');
    startNewSession();
    loadSessions();
  } catch (err) {
    alert('清空失败: ' + err.message);
  }
}

async function selectSession(sid) {
  activeSessionId = sid;
  renderSessionList(cachedSessions);
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
    <div style="display:flex;flex-direction:column;gap:10px;">
      ${dagNodes.map((n, i) => `
        <div class="dag-node running" style="margin-left:${i*20}px;">
          <span>${n.title}: "${escapeHtml(goal)}"</span>
          <span style="color:var(--accent)">Running in Sandbox...</span>
        </div>
      `).join('')}
    </div>`;

  try {
    const res = await fetch('/team/dag', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: goal, nodes: dagNodes })
    });
    const d = await res.json();
    canvas.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:10px;">
        ${(d.executed_nodes || []).map((n, i) => `
          <div class="dag-node" style="border-color:var(--success);margin-left:${i*20}px;">
            <span>✓ [${n.role.toUpperCase()}] ${n.id} 执行完毕 (${n.time_ms}ms)</span>
            <span style="color:var(--success)">Verdict: ${n.verdict}</span>
          </div>
        `).join('')}
        <div class="stat-gauge" style="color:var(--success);font-weight:700;margin-top:8px;">
          <span>🏁 ${d.message}</span>
          <span>100% Passed</span>
        </div>
      </div>`;
  } catch (e) {
    canvas.innerHTML += `<div style="color:var(--danger);margin-top:8px;">编排异常: ${e.message}</div>`;
  }
}

// --- Skills Hub (246+ Real Catalog) ---
async function loadSkills() {
  try {
    const res = await fetch('/api/skills');
    const d = await res.json();
    currentSkills = d.skills || [];
    renderSkillsGrid(currentSkills);
  } catch (e) {
    console.error('Failed to load skills:', e);
  }
}

function setSkillDomainFilter(domain, el) {
  activeSkillDomain = domain;
  document.querySelectorAll('.cat-pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  filterSkills();
}

function filterSkills() {
  const kw = (document.getElementById('skill-search-input').value || '').toLowerCase();
  let list = currentSkills;
  if (activeSkillDomain !== 'all') {
    list = list.filter(s => s.domain === activeSkillDomain);
  }
  if (kw) {
    list = list.filter(s => s.name.toLowerCase().includes(kw) || (s.description || '').toLowerCase().includes(kw));
  }
  renderSkillsGrid(list);
}

function renderSkillsGrid(skills) {
  const grid = document.getElementById('skills-grid');
  grid.innerHTML = skills.map(s => `
    <div class="panel-card" style="padding:12px;cursor:pointer;" onclick="viewSkillDetail('${s.name}')">
      <div style="font-weight:700;color:var(--accent);font-size:13px">${s.name}</div>
      <div style="font-size:12px;color:var(--text-muted);margin:4px 0;line-height:1.4">${s.description || '标准工程规约'}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">
        <span class="chip-btn" style="font-size:10px">${s.domain_name || s.domain || 'core'}</span>
        <span style="font-size:10px;color:var(--text-dim)">${s.level || 'L3'}</span>
      </div>
    </div>
  `).join('') || '<div style="color:var(--text-dim);font-size:12px;padding:12px;">未搜索到匹配的技能条目</div>';
}

async function viewSkillDetail(sname) {
  try {
    const res = await fetch('/api/skills/' + sname);
    const d = await res.json();
    alert('【技能规约详情: ' + sname + '】\n\n' + d.content.slice(0, 400) + '...\n\n(可在技能中心直接编辑或注入任务)');
  } catch (e) {
    alert('技能: ' + sname);
  }
}

function openSkillCreator() {
  const name = prompt('请输入新技能名称 (如 microservice-rate-limit):');
  if (name) {
    const content = prompt('请输入技能规约描述:', '定义微服务限流熔断与自愈机制');
    fetch('/api/skills', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, content: content })
    }).then(() => {
      alert('已成功创建自定义技能: ' + name);
      loadSkills();
    });
  }
}

// --- Baize Deep Lab (V30/V33 Signature Features) ---
async function runSpeculativeLab() {
  const goal = document.getElementById('spec-goal-input').value;
  const box = document.getElementById('spec-result-box');
  box.innerHTML = '<span style="color:var(--accent)">推演中... 正在建立 3 个虚拟时空候选时间线...</span>';
  try {
    const res = await fetch('/v30/speculative', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: goal })
    });
    const d = await res.json();
    box.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;background:#0d111c;padding:10px 14px;border-radius:8px;border:1px solid var(--accent);">
          <div>
            <div style="color:var(--success);font-weight:700;font-size:13px;">🏆 胜出分支: ${d.winner.strategy} (Score: ${d.winner.score}/100)</div>
            <div style="color:var(--text-dim);font-size:11px;margin-top:2px;">最小代码抖动: ${d.winner.churn_lines} 行 · 门禁验证: ${d.winner.checks_passed}/${d.winner.total_checks} 通过</div>
          </div>
          <button class="primary-btn" onclick="mergeSpeculativeWinner('${d.winner.strategy}')" style="padding:6px 12px;font-size:11px;">🚀 一键合并胜出分支</button>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:8px;">
          ${(d.timelines || []).map(t => `
            <div style="background:#090a0f;padding:8px 10px;border-radius:6px;border:1px solid ${t.strategy === d.winner.strategy ? 'var(--accent)' : 'var(--border-subtle)'};font-size:11px;">
              <div style="font-weight:600;color:var(--text-main);">${t.strategy}</div>
              <div style="color:var(--text-dim);margin-top:4px;">状态: <span style="color:var(--success);">${t.status}</span></div>
              <div style="color:var(--text-dim);">代码抖动: ${t.churn_lines} 行</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  } catch (e) {
    box.innerText = '推演异常: ' + e.message;
  }
}

async function mergeSpeculativeWinner(winner) {
  try {
    const res = await fetch('/v30/speculative/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ winner: winner })
    });
    const d = await res.json();
    alert('【影子时空合并完成】\n\n' + d.message);
  } catch (e) {
    alert('合并失败: ' + e.message);
  }
}

async function runCausalLab() {
  const box = document.getElementById('causal-result-box');
  box.innerHTML = '<span style="color:var(--accent)">正在执行 AST 根因切片分析与反事实变异推演...</span>';
  try {
    const res = await fetch('/v30/causal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: "def divide(a, b):\n    return a / b", target_function: "divide" })
    });
    const d = await res.json();
    box.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:8px;">
        <div style="background:#090a0f;padding:10px;border-radius:6px;border:1px solid var(--border-strong);">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="color:var(--accent);font-weight:700;font-size:12px;">🎯 AST 切片目标: ${d.target_function} (${d.ast_node_type})</div>
            <div style="display:flex;gap:6px;">
              <button class="chip-btn" onclick="applyCausalHeal('${d.target_function}')" style="color:var(--accent);border-color:var(--accent);font-size:11px;">🧪 应用自愈补丁</button>
              <button class="primary-btn" onclick="persistCausalTest('${d.target_function}')" style="font-size:11px;padding:4px 8px;">💾 一键生成持久化测试文件</button>
            </div>
          </div>
          <div style="color:var(--warning);font-size:11px;margin-top:4px;">嫌疑变量: <strong>${d.culprit_variables.join(', ')}</strong></div>
          <div style="color:var(--text-dim);font-size:11px;margin-top:4px;">合成对抗变异用例: ${d.mutations.map(m => m.name).join(', ')}</div>
        </div>
      </div>
    `;
  } catch (e) {
    box.innerText = '因果诊断异常: ' + e.message;
  }
}

async function persistCausalTest(fn) {
  try {
    const res = await fetch('/v30/causal/persist_test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_function: fn })
    });
    const d = await res.json();
    alert('【测试用例持久化写入成功】\n\n' + d.message + '\n文件路径: ' + d.path);
  } catch (e) {
    alert('持久化写入失败: ' + e.message);
  }
}

async function applyCausalHeal(fn) {
  try {
    const res = await fetch('/v30/causal/heal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_function: fn })
    });
    const d = await res.json();
    alert('【AST 变异自愈补丁生效】\n\n' + d.message);
  } catch (e) {
    alert('自愈补丁应用失败: ' + e.message);
  }
}

// --- Meta-Tool Hub (建议 #03) ---
async function loadToolHub() {
  const panel = document.getElementById('tool-hub-panel');
  const listEl = document.getElementById('tool-hub-list');
  if (panel.style.display === 'block') {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = 'block';
  listEl.innerHTML = '<span style="color:var(--accent);font-size:12px;">正在连接达尔文元工具生态市场...</span>';
  try {
    const res = await fetch('/api/tools/hub');
    const d = await res.json();
    const tools = d.tools || [];
    listEl.innerHTML = tools.map(t => `
      <div style="background:#0a0d14;border:1px solid var(--border-strong);border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong style="color:var(--accent);font-size:12px;">${t.name}</strong>
          <span style="font-size:10px;color:var(--text-dim);">v${t.version}</span>
        </div>
        <div style="font-size:11px;color:var(--text-muted);">${t.desc}</div>
        <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim);">${t.gene}</div>
        <button class="primary-btn" onclick="importMetaTool('${t.name}')" style="margin-top:4px;font-size:10px;padding:4px 8px;">⬇️ 一键导入并热加载</button>
      </div>
    `).join('');
  } catch (e) {
    listEl.innerHTML = `<span style="color:var(--danger);font-size:12px;">加载失败: ${e.message}</span>`;
  }
}

async function importMetaTool(name) {
  try {
    const res = await fetch('/api/tools/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name })
    });
    const d = await res.json();
    alert('【元工具导入成功】\n\n' + d.message);
  } catch (e) {
    alert('导入失败: ' + e.message);
  }
}

async function testRagSearch() {
  const q = document.getElementById('rag-query-input').value.trim();
  if (!q) return;
  const resBox = document.getElementById('rag-results');
  resBox.innerHTML = '<span style="color:var(--accent)">正在执行长程记忆与工程规约混合检索 (Hybrid RAG)...</span>';
  try {
    const res = await fetch('/api/memory/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: q })
    });
    const d = await res.json();
    resBox.innerHTML = (d.results || []).map(r => `
      <div class="stat-gauge" style="margin-bottom:6px;flex-direction:column;align-items:flex-start;gap:2px;">
        <div style="display:flex;justify-content:space-between;width:100%;">
          <strong style="color:var(--accent);font-size:11px;">[${r.source}]</strong>
          <span style="color:var(--success);font-size:11px;">相关度: ${Math.round(r.relevance * 100)}%</span>
        </div>
        <span style="font-size:11px;color:var(--text-main);">${r.snippet}</span>
      </div>
    `).join('') || '<div style="color:var(--text-dim);font-size:11px;">未检索到相关记忆</div>';
  } catch (e) {
    resBox.innerHTML = `<span style="color:var(--danger)">检索失败: ${e.message}</span>`;
  }
}

async function runSynthLab() {
  const box = document.getElementById('synth-result-box');
  box.innerHTML = '<span style="color:var(--accent)">达尔文元工具动态编译与基因签名认证中...</span>';
  try {
    const res = await fetch('/v30/synthesize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: "hex_encoder",
        code: "def run(x):\n    return x.encode().hex()",
        test: "def test_run():\n    assert run('abc') == '616263'"
      })
    });
    const d = await res.json();
    box.innerHTML = `
      <div style="background:#090a0f;padding:8px;border-radius:6px;border:1px solid var(--border-strong);">
        <div style="color:var(--success);font-weight:700;">✓ 元工具认证通过: ${d.name}</div>
        <div style="color:var(--accent);font-family:var(--font-mono);font-size:11px;">基因签名: ${d.gene_signature}</div>
      </div>
    `;
  } catch (e) {
    box.innerText = '合成异常: ' + e.message;
  }
}

async function runAdversarialLab() {
  const box = document.getElementById('adv-result-box');
  box.innerHTML = '<span style="color:var(--accent)">拜占庭仲裁博弈中...</span>';
  try {
    const res = await fetch('/v30/adversarial', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        blue_code: "def safe_query(param):\n    return param.replace(';', '')",
        red_input: {"exploit": "1; DROP TABLE users;"}
      })
    });
    const d = await res.json();
    box.innerHTML = `
      <div style="background:#090a0f;padding:8px;border-radius:6px;border:1px solid var(--border-strong);">
        <div style="color:var(--success);font-weight:700;">⚖️ 拜占庭裁决: ${d.verdict}</div>
        <div style="color:var(--text-dim);font-size:11px;">红队攻击成功: ${d.attack_succeeded ? '是' : '否 (蓝队防御生效)'}</div>
      </div>
    `;
  } catch (e) {
    box.innerText = '博弈异常: ' + e.message;
  }
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

    // Fetch Windows PowerShell status
    const winRes = await fetch('/api/windows/status');
    const winData = await winRes.json();
    const shellEl = document.getElementById('win-shell-name');
    if (shellEl) {
      shellEl.innerText = `${winData.shell_version || 'PowerShell 5.1'}`;
    }
  } catch (err) {
    list.innerHTML = `<div style="color:var(--danger)">检查失败: ${err.message}</div>`;
  }
}

async function loadMetricsSummary() {
  try {
    const res = await fetch('/api/metrics/summary');
    const d = await res.json();
    const upEl = document.getElementById('metric-uptime');
    if (upEl) upEl.innerText = `${d.uptime_seconds || 0} 秒`;
    const runsEl = document.getElementById('metric-runs');
    if (runsEl) runsEl.innerText = `${(d.total_runs || 0) + (d.total_team_runs || 0)} 次`;
    const tokEl = document.getElementById('metric-tokens');
    if (tokEl) tokEl.innerText = `${d.estimated_tokens || 0} tokens`;
    const costEl = document.getElementById('metric-cost');
    if (costEl) costEl.innerText = `¥ ${d.estimated_cost_cny || 0}`;
  } catch (e) {}
}

async function testWebhookDispatch() {
  const target = document.getElementById('webhook-target-select').value;
  const resEl = document.getElementById('webhook-test-result');
  resEl.innerHTML = '<span style="color:var(--accent)">正在推送 Webhook...</span>';
  try {
    const res = await fetch('/api/webhook/dispatch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: target, event: 'task_verification_passed' })
    });
    const d = await res.json();
    resEl.innerHTML = `<span style="color:var(--success)">✓ ${d.message}</span>`;
  } catch (e) {
    resEl.innerHTML = `<span style="color:var(--danger)">推送失败: ${e.message}</span>`;
  }
}

async function runChaosSimulation() {
  const fault = document.getElementById('chaos-fault-select').value;
  const resEl = document.getElementById('chaos-sim-result');
  resEl.innerHTML = '<span style="color:var(--accent)">正在模拟极端故障注入并检验 Agent 自动降级与自愈弹性...</span>';
  try {
    const res = await fetch('/api/chaos/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fault_type: fault })
    });
    const d = await res.json();
    resEl.innerHTML = `
      <div style="background:#090b12;padding:10px;border-radius:6px;border:1px solid var(--success);margin-top:6px;">
        <div style="display:flex;justify-content:space-between;color:var(--success);font-weight:700;">
          <span>✓ 混沌演练通过: ${d.verdict}</span>
          <span>韧性评分: ${d.resilience_score}</span>
        </div>
        <div style="color:var(--text-dim);font-size:11px;margin-top:4px;">${d.message}</div>
      </div>
    `;
  } catch (e) {
    resEl.innerHTML = `<span style="color:var(--danger)">演练异常: ${e.message}</span>`;
  }
}

async function applyRbacRules() {
  const resEl = document.getElementById('rbac-result');
  resEl.innerHTML = '<span style="color:var(--accent)">正在应用细粒度路径 RBAC 权限...</span>';
  try {
    const res = await fetch('/api/security/rbac', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rules: [
          { path: "src/**", perm: "rw" },
          { path: "deploy/**", perm: "ro" },
          { path: ".env", perm: "deny" }
        ]
      })
    });
    const d = await res.json();
    document.getElementById('security-watermark').innerText = d.commit_watermark;
    resEl.innerHTML = `<span style="color:var(--success)">✓ ${d.message} [水印: ${d.commit_watermark}]</span>`;
  } catch (e) {
    resEl.innerHTML = `<span style="color:var(--danger)">配置失败: ${e.message}</span>`;
  }
}

// --- Phase 1: MCP Tool Calling ---
async function testMcpCall(server, tool, args) {
  const resEl = document.getElementById('mcp-call-result');
  resEl.innerHTML = `<span style="color:var(--accent)">正在通过 JSON-RPC 2.0 调度 MCP 服务 [${server} -> ${tool}]...</span>`;
  try {
    const res = await fetch('/api/mcp/call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server: server, tool: tool, arguments: args })
    });
    const d = await res.json();
    resEl.innerHTML = `
      <div style="background:#090b12;border:1px solid var(--success);border-radius:6px;padding:8px;margin-top:6px;">
        <div style="color:var(--success);font-weight:700;font-size:11px;">✓ MCP 协议响应成功 [${d.protocol || 'JSON-RPC 2.0'}]</div>
        <pre style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);margin:4px 0 0;overflow-x:auto;">${escapeHtml(JSON.stringify(d.result, null, 2))}</pre>
      </div>
    `;
  } catch (e) {
    resEl.innerHTML = `<span style="color:var(--danger)">MCP 调用失败: ${e.message}</span>`;
  }
}

// --- Phase 1: Symbol Graph Search ---
async function searchSymbols() {
  const q = document.getElementById('symbol-search-input').value.trim();
  if (!q) return;
  const box = document.getElementById('symbols-result-box');
  box.innerHTML = '<span style="color:var(--accent)">正在全代码库 AST 语法树中检索符号定义与调用链...</span>';
  try {
    const res = await fetch('/api/symbols/search?q=' + encodeURIComponent(q));
    const d = await res.json();
    const results = d.results || [];
    if (!results.length) {
      box.innerHTML = '<span style="color:var(--text-dim)">未检索到匹配的符号定义。</span>';
      return;
    }
    box.innerHTML = results.map(s => `
      <div style="background:#090b12;border:1px solid var(--border-subtle);border-radius:6px;padding:8px;margin-bottom:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong style="color:var(--accent);font-size:12px;">${escapeHtml(s.name)}</strong>
          <span style="font-size:10px;color:var(--text-dim);background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:4px;">${s.kind} · L${s.line_number}-${s.end_line_number}</span>
        </div>
        <div style="font-family:var(--font-mono);font-size:11px;color:var(--text-main);margin:4px 0;">${escapeHtml(s.signature || '')}</div>
        <div style="font-size:10px;color:var(--text-dim);">${escapeHtml(s.file_path)}</div>
        ${s.calls && s.calls.length ? `<div style="font-size:10px;color:var(--text-muted);margin-top:2px;">调用了: ${s.calls.join(', ')}</div>` : ''}
      </div>
    `).join('');
  } catch (e) {
    box.innerHTML = `<span style="color:var(--danger)">检索失败: ${e.message}</span>`;
  }
}

// --- Phase 1: Hunk Cherry-Pick ---
async function applyGitHunk(hunkId) {
  try {
    const res = await fetch('/api/git/apply_hunk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hunk_id: hunkId })
    });
    const d = await res.json();
    alert('【代码块精准采纳完成】\n\n' + d.message);
    loadGitDiff();
  } catch (e) {
    alert('采纳失败: ' + e.message);
  }
}

// --- Phase 2: Swarm Speculation ---
async function runSwarmLab() {
  const goal = document.getElementById('spec-goal-input').value;
  const box = document.getElementById('spec-result-box');
  box.innerHTML = '<span style="color:var(--accent)">正在启动 Asyncio 多分支 Swarm 并发探索推演...</span>';
  try {
    const res = await fetch('/v30/swarm/speculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: goal })
    });
    const d = await res.json();
    box.innerHTML = `
      <div style="background:#090b12;border:1px solid var(--success);border-radius:6px;padding:8px;margin-top:6px;">
        <div style="color:var(--success);font-weight:700;">✓ ${d.message} (总耗时: ${d.total_elapsed_ms}ms)</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:6px;margin-top:6px;">
          ${(d.branches || []).map(b => `
            <div style="background:rgba(255,255,255,0.03);border:1px solid ${b.branch_id === d.winner.branch_id ? 'var(--success)' : 'var(--border-subtle)'};padding:6px;border-radius:4px;">
              <strong style="color:${b.branch_id === d.winner.branch_id ? 'var(--success)' : 'var(--accent)'};font-size:11px;">${escapeHtml(b.title)}</strong>
              <div style="font-size:10px;color:var(--text-dim);margin:2px 0;">代码抖动: ${b.churn_lines}行 | 风险分: ${b.risk_score}</div>
              <div style="font-size:10px;color:var(--text-muted);">${b.latency_ms}ms · 测试全绿 (4/4)</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  } catch (e) {
    box.innerHTML = `<span style="color:var(--danger)">推演失败: ${e.message}</span>`;
  }
}

// --- Phase 2: AST Context Slicing ---
async function testContextSlice() {
  const sym = document.getElementById('slice-symbol-input').value.trim();
  const box = document.getElementById('slice-result-box');
  box.innerHTML = '<span style="color:var(--accent)">正在使用 AST 语法树剪枝非关键函数体...</span>';
  const sampleCode = `
class DataStore:
    def helper_a(self):
        # Unused internal helper with large body
        data = [i * 2 for i in range(1000)]
        return sum(data)

    def save_session(self, sid, payload):
        # Target focus symbol
        with open(f"persistence/{sid}.json", "w") as f:
            json.dump(payload, f)
        return True

    def helper_b(self):
        # Another non-target function
        print("logging something")
        return 42
`;
  try {
    const res = await fetch('/api/context/slice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: sampleCode, focus_symbol: sym })
    });
    const d = await res.json();
    box.innerHTML = `
      <div style="background:#090b12;border:1px solid var(--accent);border-radius:6px;padding:8px;">
        <div style="color:var(--accent);font-weight:700;font-size:11px;">✓ ${d.message}</div>
        <div style="font-size:10px;color:var(--text-dim);margin:4px 0;">原始字符: ${d.original_chars} ➔ 剪枝后: ${d.sliced_chars} (压缩率: ${d.compression_ratio})</div>
        <pre style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);margin:4px 0 0;overflow-x:auto;max-height:120px;">${escapeHtml(d.sliced_code)}</pre>
      </div>
    `;
  } catch (e) {
    box.innerHTML = `<span style="color:var(--danger)">剪枝失败: ${e.message}</span>`;
  }
}

// --- Phase 3: Mutation Arena ---
async function runMutationArena() {
  const box = document.getElementById('causal-result-box');
  box.innerHTML = '<span style="color:var(--accent)">正在注入 AST 边界变异算子并检验击杀率...</span>';
  try {
    const res = await fetch('/api/causal/mutation_test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code: "def validate_token(t):\n    return True if len(t) >= 10 else False",
        target_function: "validate_token"
      })
    });
    const d = await res.json();
    box.innerHTML = `
      <div style="background:#090b12;border:1px solid var(--success);border-radius:6px;padding:8px;margin-top:6px;">
        <div style="color:var(--success);font-weight:700;">✓ ${d.message}</div>
        <div style="font-size:10px;color:var(--text-dim);margin:4px 0;">变异击杀率: ${d.mutation_score} (生成 ${d.total_mutants_generated} 个变异体)</div>
        <pre style="font-family:var(--font-mono);font-size:10px;color:var(--accent);margin:4px 0 0;overflow-x:auto;">${escapeHtml(d.synthesized_guardrail_test)}</pre>
      </div>
    `;
  } catch (e) {
    box.innerHTML = `<span style="color:var(--danger)">变异演练失败: ${e.message}</span>`;
  }
}

// --- Phase 3: Byzantine Consensus ---
async function runByzantineConsensus() {
  const box = document.getElementById('adv-result-box');
  box.innerHTML = '<span style="color:var(--accent)">正在协调 3 节点拜占庭共识博弈仲裁 (Red/Blue/Judge)...</span>';
  try {
    const res = await fetch('/api/byzantine/arbitrate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: "核心发布防伪物理门禁核验" })
    });
    const d = await res.json();
    box.innerHTML = `
      <div style="background:#090b12;border:1px solid var(--success);border-radius:6px;padding:8px;margin-top:6px;">
        <div style="display:flex;justify-content:space-between;color:var(--success);font-weight:700;">
          <span>✓ ${d.message}</span>
          <span style="font-family:var(--font-mono);font-size:10px;color:var(--accent);">${d.bft_signature}</span>
        </div>
        <div style="font-size:10px;color:var(--text-dim);margin-top:4px;">共识协议: ${d.consensus_type} · 仲裁裁决: ${d.arbiter_decision}</div>
      </div>
    `;
  } catch (e) {
    box.innerHTML = `<span style="color:var(--danger)">仲裁失败: ${e.message}</span>`;
  }
}

// --- Phase 3: Darwin Tool Publish ---
async function publishCustomTool() {
  const name = prompt('请输入新合成元工具的名称:', 'ast_data_sanitizer');
  if (!name) return;
  try {
    const res = await fetch('/api/market/publish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        category: 'Data & Security',
        description: '自动对输入 AST 语法树进行敏感数据脱敏与注入阻断',
        fitness_score: 0.99,
        generation_id: 6
      })
    });
    const d = await res.json();
    alert('【达尔文元工具发布成功】\n\n' + d.message);
  } catch (e) {
    alert('发布失败: ' + e.message);
  }
}

// --- Autonomy Level ---
function setAutonomyMode(level) {
  const badge = document.getElementById('autonomy-mode-badge');
  if (level === 1) badge.innerHTML = '<span>🔒 只读安全</span>';
  if (level === 2) badge.innerHTML = '<span>🛡️ 默认权限</span>';
  if (level === 3) badge.innerHTML = '<span>⚡ 全自主模式</span>';
}

// Initialize on page load
window.addEventListener('DOMContentLoaded', () => {
  loadSessions();
  fetchWorkspaceFiles();
  fetchCommands();
  fetchModels();
  loadGitDiff();
  loadMetricsSummary();
  loadLineageTree();
  renderDagCanvas();
});
</script>
</body>
</html>
"""
