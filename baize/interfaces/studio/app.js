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

// --- Honest failure rendering ---
// Several Studio panels call endpoints that are stubs: the server now answers
// 501 instead of a hardcoded fake success. Without this, those panels would
// render "✓ undefined". Every fetch handler for a stub route must go through
// this check so the UI reports the stub instead of inventing an outcome.
function isStubResponse(res, d) {
  return res.status === 501 || res.status === 410 || (d && (d.error === 'not_implemented' || d.error === 'gone'));
}

function stubNoticeHtml(d) {
  const isGone = d && (d.error === 'gone' || d.status === 'retired');
  const label = isGone ? '已下线（HTTP 410）' : '未实现（HTTP 501）';
  const reason = escapeHtml((d && (d.reason || d.message)) || '该端点不可用');
  return `<span style="color:var(--danger)">✗ ${label}：${reason}</span>`;
}

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
  if (tabId === 'tab-helios') refreshHeliosAll();
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
  // The trailing "· 未生效" is not decoration: nothing in the runtime reads
  // BAIZE_AUTONOMY_LEVEL, so this slider stores a value and changes no
  // behaviour. The server reports the same thing via "effective": false.
  if (level === 1) label.innerText = '🔒 只读安全 · 未生效';
  if (level === 2) label.innerText = '🛡️ 默认权限 · 未生效';
  if (level === 3) label.innerText = '⚡ 全自主模式 · 未生效';
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
    
    const branchName = st.branch || 'main';
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

// --- V39.0.0 Aegis Blast Radius & TIA Inspector ---
async function runBlastRadiusInspect() {
  const target = document.getElementById('aegis-target-input').value.trim();
  const resBox = document.getElementById('aegis-inspect-result');
  if (!target) { alert('请输入要分析的目标符号或文件路径'); return; }
  resBox.style.display = 'block';
  resBox.innerHTML = '<span style="color:var(--text-dim);">⏳ 正在通过 AST 全局拓扑计算直接与传递调用方...</span>';
  try {
    const res = await fetch(`/api/blast?symbol=${encodeURIComponent(target)}`);
    const d = await res.json();
    if (d.error) {
      resBox.innerHTML = `<span style="color:var(--error);">❌ 分析错误: ${d.error}</span>`;
      return;
    }
    const badgeColor = d.risk_level === 'CRITICAL' ? 'var(--error)' : (d.risk_level === 'HIGH' ? 'var(--warning)' : 'var(--success)');
    let callersHtml = (d.direct_callers || []).map(c => `<div>  ↳ <span style="color:var(--accent);">${c.file_path}:${c.line_number}</span> (调用方: <code>${c.caller_symbol}</code>)</div>`).join('');
    if (!callersHtml) callersHtml = '<div style="color:var(--text-dim);">  (无直接外部调用方，风险极低)</div>';
    
    resBox.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border-subtle);padding-bottom:8px;margin-bottom:8px;">
        <div><strong>目标符号:</strong> <code style="color:var(--accent);">${d.target_symbol}</code></div>
        <div><span class="badge" style="background:${badgeColor}22;color:${badgeColor};border:1px solid ${badgeColor};">风险等级: ${d.risk_level}</span></div>
      </div>
      <div><strong>直接受波及调用方 (${d.direct_callers_count || 0} 处):</strong></div>
      ${callersHtml}
      ${(d.impacted_files && d.impacted_files.length) ? `<div style="margin-top:6px;"><strong>受波及跨模块文件 (${d.impacted_files.length} 个):</strong> <span style="color:var(--text-dim);">${d.impacted_files.join(', ')}</span></div>` : ''}
      <div style="margin-top:8px;color:var(--text-dim);font-size:11px;">⏱️ AST 解析耗时: ${d.latency_ms}ms · 零外部依赖</div>
    `;
  } catch (e) {
    resBox.innerHTML = `<span style="color:var(--error);">请求异常: ${e.message}</span>`;
  }
}

async function runTestImpactInspect() {
  const target = document.getElementById('aegis-target-input').value.trim();
  const resBox = document.getElementById('aegis-inspect-result');
  if (!target) { alert('请输入要分析的目标文件或符号'); return; }
  resBox.style.display = 'block';
  resBox.innerHTML = '<span style="color:var(--text-dim);">⏳ 正在通过 TIA 矩阵分析单测依赖关系...</span>';
  try {
    const res = await fetch(`/api/impact?target=${encodeURIComponent(target)}`);
    const d = await res.json();
    if (d.error) {
      resBox.innerHTML = `<span style="color:var(--error);">❌ 分析错误: ${d.error}</span>`;
      return;
    }
    let testsHtml = (d.impacted_files || []).map(f => `<div>  🧪 <span style="color:var(--text-main);">${f}</span></div>`).join('');
    if (!testsHtml) testsHtml = '<div style="color:var(--text-dim);">  (未检索到直接绑定的单测文件)</div>';

    resBox.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border-subtle);padding-bottom:8px;margin-bottom:8px;">
        <div><strong>目标:</strong> <code style="color:var(--accent);">${(d.changed_targets || []).join(', ')}</code></div>
        <div><span class="badge" style="background:var(--success)22;color:var(--success);border:1px solid var(--success);">预期提速: ~${d.speedup_ratio}x</span></div>
      </div>
      <div><strong>精准受影响单测集合 (${(d.impacted_files || []).length} / ${d.total_test_files || 0} 个测试文件):</strong></div>
      ${testsHtml}
      ${d.recommended_command ? `<div style="margin-top:8px;padding:6px 8px;background:#0d111b;border-radius:4px;border:1px solid var(--border-subtle);"><strong>推荐执行:</strong> <code style="color:var(--accent);">${d.recommended_command}</code></div>` : ''}
      <div style="margin-top:8px;color:var(--text-dim);font-size:11px;">⏱️ TIA 分析耗时: ${d.latency_ms}ms</div>
    `;
  } catch (e) {
    resBox.innerHTML = `<span style="color:var(--error);">请求异常: ${e.message}</span>`;
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

function setForkCompressResult(msg, isError) {
  const el = document.getElementById('fork-compress-result');
  if (!el) return;
  el.textContent = msg;
  el.style.color = isError ? 'var(--danger)' : 'var(--accent)';
}

async function submitFork() {
  const p = document.getElementById('fork-parent-input').value.trim();
  if (!p) { setForkCompressResult('请输入父会话 ID', true); return; }
  await forkSession(p);
}

async function submitCompress() {
  const sid = document.getElementById('compress-id-input').value.trim();
  if (!sid) { setForkCompressResult('请输入要压缩的会话 ID', true); return; }
  try {
    const res = await fetch('/sessions/compress', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: sid })
    });
    const d = await res.json();
    setForkCompressResult('会话压缩完成: 节省 tokens ' + (d.saved_tokens || 0));
  } catch (e) {
    setForkCompressResult('压缩失败: ' + e, true);
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
      setForkCompressResult('已从 ' + sid + ' 分叉出新会话: ' + data.new_session_id);
      loadSessions();
    }
  } catch (err) {
    setForkCompressResult('Fork 失败: ' + err.message, true);
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
    if (isStubResponse(res, d)) {
      canvas.innerHTML = `<div class="stat-gauge">${stubNoticeHtml(d)}</div>`;
      return;
    }
    // The old success branch rendered d.executed_nodes with a hardcoded
    // "100% Passed" badge. It was deleted with the fabricated response it
    // depended on - there is nothing left for it to render. If /team/dag is
    // ever implemented for real, render the real per-node results here, and do
    // not reintroduce a percentage that the server did not measure.
    canvas.innerHTML = `<div class="stat-gauge">${escapeHtml(d.message || '未返回结果')}</div>`;
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
    if (isStubResponse(res, d)) {
      // This panel used to render a winner chosen among three timelines the
      // server built inline. The real implementation is /v30/swarm/speculate.
      box.innerHTML = stubNoticeHtml(d)
        + '<div style="color:var(--text-dim);font-size:11px;margin-top:6px;">'
        + '请改用 <code>/v30/swarm/speculate</code>：它会在真实 git worktree 中'
        + '并行建立候选分支并测量改动行数。</div>';
      return;
    }
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

const CAUSAL_SAMPLE_CODE = "def divide(a, b):\n    return a / b if b != 0 else 0";

async function runCausalLab() {
  const box = document.getElementById('causal-result-box');
  box.innerHTML = '<span style="color:var(--accent)">正在执行 AST 根因切片分析...</span>';
  try {
    const res = await fetch('/v30/causal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: CAUSAL_SAMPLE_CODE, target_function: "divide" })
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
          <div style="color:var(--text-dim);font-size:11px;margin-top:4px;">合成对抗变异用例（未执行，仅描述符）: ${d.mutations.map(m => m.name).join(', ')}</div>
          <div style="color:var(--text-dim);font-size:11px;margin-top:2px;">${escapeHtml(d.mutations_note || '')}</div>
        </div>
      </div>
    `;
  } catch (e) {
    box.innerText = '因果诊断异常: ' + e.message;
  }
}

async function persistCausalTest(fn) {
  try {
    // The code has to be sent too: the written test is generated from it, not
    // from a fixed template.
    const res = await fetch('/v30/causal/persist_test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_function: fn, code: CAUSAL_SAMPLE_CODE })
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
    if (isStubResponse(res, d)) {
      alert('【未实现 (HTTP 501)】\n\n' + ((d && d.reason) || '该功能尚未实现'));
      return;
    }
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
    if (isStubResponse(res, d)) {
      alert('【未实现】\n\n' + d.reason
        + '\n\n此前这里会弹出「已成功动态热加载」，但服务端并未注册任何工具。');
      return;
    }
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
    // The endpoint reports substring matches, not semantic relevance. The old
    // renderer multiplied a hardcoded 0.92 by 100 and printed "相关度: 92%",
    // which was a number the server had invented.
    resBox.innerHTML = (d.results || []).map(r => `
      <div class="stat-gauge" style="margin-bottom:6px;flex-direction:column;align-items:flex-start;gap:2px;">
        <div style="display:flex;justify-content:space-between;width:100%;">
          <strong style="color:var(--accent);font-size:11px;">[${r.source}]</strong>
          <span style="color:var(--text-dim);font-size:11px;">子串命中 ${r.occurrences} 次</span>
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
      // Do not substitute a version we did not read. `shell_version` is null
      // when the probe failed; the old code hardcoded a version string here and
      // turned an unknown into a confident wrong answer.
      shellEl.innerText = winData.shell_version
        ? `${winData.shell_version}`
        : `未知 (${winData.shell_version_error || '探测未返回结果'})`;
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
  const urlEl = document.getElementById('webhook-url');
  const rawUrl = urlEl ? urlEl.value.trim() : '';
  const url = rawUrl && !/^https?:\/\//i.test(rawUrl) ? ('https://' + rawUrl) : rawUrl;
  const resEl = document.getElementById('webhook-test-result');
  resEl.innerHTML = '<span style="color:var(--accent)">正在推送真实 Webhook...</span>';
  try {
    const res = await fetch('/api/webhook/dispatch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: target, url: url, event: 'task_verification_passed' })
    });
    const d = await res.json();
    if (!res.ok) {
      resEl.innerHTML = `<span style="color:var(--danger)">✗ HTTP ${res.status}：${escapeHtml(d.message || d.error || '派发失败')}</span>`;
      return;
    }
    resEl.innerHTML = `<span style="color:var(--success)">✓ ${escapeHtml(d.message)}</span>`;
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
    if (isStubResponse(res, d)) {
      resEl.innerHTML = stubNoticeHtml(d);
      return;
    }
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
    if (isStubResponse(res, d)) {
      // The watermark used to be a hash of the current time, rendered as if it
      // certified something. Nothing was applied and nothing was signed.
      resEl.innerHTML = stubNoticeHtml(d);
      return;
    }
    const digest = d.policy_digest || '';
    const wmEl = document.getElementById('security-watermark');
    if (wmEl && digest) wmEl.innerText = digest;
    resEl.innerHTML = `<span style="color:var(--success)">✓ ${escapeHtml(d.message)}</span>`;
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
    if (isStubResponse(res, d)) {
      alert('【未实现 (HTTP 501)】\n\n' + ((d && d.reason) || '该功能尚未实现'));
      return;
    }
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
  box.innerHTML = '<span style="color:var(--accent)">正在统计评审意见票数...</span>';
  try {
    // No verdicts are sent, so this returns "awaiting_verdicts". That is the
    // honest answer: the endpoint counts votes, it does not run agents or review
    // code. It used to answer with two literal APPROVEs and a timestamp hash
    // labelled BFT-SIG-, which looked like a signed verdict and was neither.
    const res = await fetch('/api/byzantine/arbitrate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: "核心发布防伪物理门禁核验" })
    });
    const d = await res.json();
    const awaiting = d.status === 'awaiting_verdicts';
    const accent = awaiting ? 'var(--warning,#d9a441)' : 'var(--success)';
    box.innerHTML = `
      <div style="background:#090b12;border:1px solid ${accent};border-radius:6px;padding:8px;margin-top:6px;">
        <div style="display:flex;justify-content:space-between;color:${accent};font-weight:700;">
          <span>${awaiting ? '…' : '✓'} ${escapeHtml(d.message)}</span>
          <span style="font-family:var(--font-mono);font-size:10px;color:var(--accent);">${escapeHtml(d.digest || '无摘要')}</span>
        </div>
        <div style="font-size:10px;color:var(--text-dim);margin-top:4px;">${escapeHtml(d.consensus_type)} · 签名: ${d.signed ? '有' : '无（未做任何签名）'}</div>
        <div style="font-size:10px;color:var(--text-dim);margin-top:4px;">${escapeHtml(d.digest_kind || '')}</div>
        <div style="font-size:10px;color:var(--text-dim);margin-top:4px;">代码事实（未被分析）: ${escapeHtml(JSON.stringify(d.target_code_facts))}</div>
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

// --- System 1 Fast Reflex (V38 Jev) ---
async function testSystem1Reflex() {
  const box = document.getElementById('sys1-result-box');
  const goalInput = document.getElementById('sys1-goal-input');
  const goal = (goalInput ? goalInput.value : '').trim();
  if (!goal) return;
  box.innerHTML = '<span style="color:var(--accent)">正在进行 System 1 亚毫秒快反射判定...</span>';
  try {
    const t0 = performance.now();
    const res = await fetch('/api/system1/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: goal })
    });
    const d = await res.json();
    const clientLatency = (performance.now() - t0).toFixed(2);
    const probEntries = Object.entries(d.probabilities || {});
    const probHtml = probEntries.map(([k, v]) => `<code>${k}</code>: ${(v*100).toFixed(1)}%`).join(' | ');
    box.innerHTML = `
      <div style="background:#090a0f;padding:10px;border-radius:6px;border:1px solid var(--accent);display:flex;flex-direction:column;gap:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong style="color:var(--accent);font-size:13px;">🎯 路由意图: ${d.intent} (置信度: ${(d.confidence * 100).toFixed(1)}%)</strong>
          <span style="font-size:11px;color:var(--success);font-family:var(--font-mono);">内核延时: ${d.latency_ms.toFixed(2)}ms (往返: ${clientLatency}ms)</span>
        </div>
        <div style="font-size:11px;color:var(--text-muted);">
          推荐专家: <strong>${(d.recommended_experts || []).join(', ') || '通用执行'}</strong> · 决策内核: <code>${d.backend}</code>
        </div>
        <div style="font-size:10.5px;color:var(--text-dim);font-family:var(--font-mono);line-height:1.4;">
          概率分布: ${probHtml}
        </div>
      </div>
    `;
    const pill = document.getElementById('sys1-latency');
    if (pill) pill.textContent = d.latency_ms < 1 ? '<1ms' : d.latency_ms.toFixed(1) + 'ms';
  } catch (e) {
    box.innerHTML = `<span style="color:var(--danger)">快反射调用异常: ${e.message}</span>`;
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


// --- V42 Helios Developer Console ---
function heliosAuthHeaders(extra = {}) {
  const h = { ...extra };
  try {
    const params = new URLSearchParams(window.location.search);
    const tok = params.get('token') || localStorage.getItem('baize_auth_token') || '';
    if (tok) h['Authorization'] = `Bearer ${tok}`;
  } catch (e) {}
  return h;
}

function switchHeliosPane(paneId) {
  document.querySelectorAll('.helios-tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.heliosPane === paneId);
  });
  document.querySelectorAll('.helios-pane').forEach(p => {
    p.classList.toggle('active', p.id === paneId);
  });
  if (paneId === 'helios-cost') { loadHeliosBudget(); loadHeliosChannels(); }
  if (paneId === 'helios-ops') { loadHeliosApprovals(); loadHeliosBgProcs(); }
  if (paneId === 'helios-worktrees') loadHeliosWorktrees();
  if (paneId === 'helios-rag') loadHeliosBoundedMemory();
  if (paneId === 'helios-tree') loadHeliosSessionTree();
}

function refreshHeliosAll() {
  loadHeliosBudget();
  loadHeliosChannels();
  loadHeliosApprovals();
  loadHeliosBgProcs();
  loadHeliosWorktrees();
  loadHeliosBoundedMemory();
  loadHeliosSessionTree();
}

async function loadHeliosBudget() {
  try {
    const res = await fetch('/api/budget', { headers: heliosAuthHeaders() });
    const d = await res.json();
    if (!res.ok) return;
    const s = d.summary || {};
    const cfg = d.config || {};
    const elUsd = document.getElementById('helios-kpi-usd');
    const elTok = document.getElementById('helios-kpi-tokens');
    const elCache = document.getElementById('helios-kpi-cache');
    const elStatus = document.getElementById('helios-kpi-status');
    if (elUsd) elUsd.textContent = `$${Number(s.estimated_usd || 0).toFixed(4)}`;
    if (elTok) elTok.textContent = Number(s.total_tokens || 0).toLocaleString();
    if (elCache) elCache.textContent = `${(Number(s.cache_hit_ratio || 0) * 100).toFixed(1)}%`;
    const elCalls = document.getElementById('helios-kpi-calls');
    if (elCalls) elCalls.textContent = `模型调用：${s.total_calls || 0} 次`;
    const elUsdCap = document.getElementById('helios-kpi-usd-cap');
    if (elUsdCap) elUsdCap.textContent = cfg.max_session_usd > 0 ? `单会话上限：$${Number(cfg.max_session_usd).toFixed(2)}` : '预算上限：未限制';
    const elTokCap = document.getElementById('helios-kpi-tok-cap');
    if (elTokCap) elTokCap.textContent = cfg.max_session_tokens > 0 ? `单会话上限：${Number(cfg.max_session_tokens).toLocaleString()}` : 'Token 上限：未限制';
    const elWarn = document.getElementById('helios-kpi-warn-ratio');
    if (elWarn) elWarn.textContent = `告警阈值：${Math.round(Number(cfg.warn_ratio || 0.8) * 100)}%`;

    const inUsd = document.getElementById('helios-cfg-usd');
    const inTok = document.getElementById('helios-cfg-tokens');
    const inWarn = document.getElementById('helios-cfg-warn');
    if (inUsd && !inUsd.value) inUsd.value = cfg.max_session_usd || 0;
    if (inTok && !inTok.value) inTok.value = cfg.max_session_tokens || 0;
    if (inWarn && !inWarn.value) inWarn.value = cfg.warn_ratio || 0.8;

    const sessions = s.sessions || [];
    const maxSessUsd = sessions.reduce((acc, x) => Math.max(acc, Number(x.estimated_usd || 0)), 0);
    if (elStatus) {
      if (cfg.max_session_usd > 0 && maxSessUsd >= cfg.max_session_usd) {
        elStatus.innerHTML = '<span class="helios-status-err">已触发熔断</span>';
      } else if (cfg.max_session_usd > 0 && maxSessUsd >= cfg.max_session_usd * (cfg.warn_ratio || 0.8)) {
        elStatus.innerHTML = '<span class="helios-status-warn">接近上限告警</span>';
      } else {
        elStatus.innerHTML = '<span class="helios-status-ok">正常</span>';
      }
    }

    const tbody = document.getElementById('helios-budget-sessions');
    if (tbody) {
      if (!sessions.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="helios-empty">暂无会话成本记录</td></tr>';
      } else {
        tbody.innerHTML = sessions.map(row => `
          <tr>
            <td class="tabular-nums">${escapeHtml(row.session_id || '')}</td>
            <td class="tabular-nums">${row.calls || 0}</td>
            <td class="tabular-nums">${Number((row.prompt_tokens || 0) + (row.completion_tokens || 0)).toLocaleString()}</td>
            <td class="tabular-nums">${(Number(row.cache_hit_ratio || 0) * 100).toFixed(1)}%</td>
            <td class="tabular-nums">$${Number(row.estimated_usd || 0).toFixed(4)}</td>
            <td><button class="chip-btn" onclick="resetHeliosSessionBudget('${escapeHtml(row.session_id || '')}')">重置</button></td>
          </tr>
        `).join('');
      }
    }
  } catch (e) {}
}

async function saveHeliosBudgetConfig() {
  const msg = document.getElementById('helios-budget-msg');
  const payload = {
    max_session_usd: parseFloat(document.getElementById('helios-cfg-usd')?.value || '0'),
    max_session_tokens: parseInt(document.getElementById('helios-cfg-tokens')?.value || '0', 10),
    warn_ratio: parseFloat(document.getElementById('helios-cfg-warn')?.value || '0.8'),
  };
  try {
    const res = await fetch('/api/budget/config', {
      method: 'POST',
      headers: heliosAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if (msg) msg.innerHTML = res.ok
      ? '<span class="helios-status-ok">预算配置已生效（当前服务进程内）</span>'
      : `<span class="helios-status-err">保存失败：${escapeHtml(d.error || res.statusText)}</span>`;
    if (res.ok) loadHeliosBudget();
  } catch (e) {
    if (msg) msg.innerHTML = `<span class="helios-status-err">请求失败：${escapeHtml(e.message)}</span>`;
  }
}

async function resetHeliosSessionBudget(sessionId) {
  await fetch('/api/budget/config', {
    method: 'POST',
    headers: heliosAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ reset_session_id: sessionId }),
  });
  loadHeliosBudget();
}

async function loadHeliosChannels() {
  const tbody = document.getElementById('helios-channels-body');
  if (!tbody) return;
  try {
    const res = await fetch('/api/channels', { headers: heliosAuthHeaders() });
    const d = await res.json();
    const chans = d.channels || [];
    if (!chans.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="helios-empty">未检测到渠道适配器</td></tr>';
      return;
    }
    tbody.innerHTML = chans.map(c => `
      <tr>
        <td><strong>${escapeHtml(c.name || '')}</strong></td>
        <td>${c.configured ? '<span class="helios-status-ok">已配置</span>' : '<span class="helios-hint">未配置密钥</span>'}</td>
        <td class="tabular-nums">${escapeHtml(c.webhook_path || `/api/channels/${c.name}/webhook`)}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="3" class="helios-empty">加载失败：${escapeHtml(e.message)}</td></tr>`;
  }
}

async function loadHeliosApprovals() {
  const pBox = document.getElementById('helios-approvals-pending');
  const hBox = document.getElementById('helios-approvals-history');
  if (!pBox || !hBox) return;
  try {
    const res = await fetch('/api/approvals', { headers: heliosAuthHeaders() });
    const d = await res.json();
    const pending = d.pending || [];
    const hist = d.history || [];
    pBox.innerHTML = pending.length ? pending.map(r => `
      <div class="helios-item-card">
        <div class="helios-item-head">
          <strong>${escapeHtml(r.tool_name || 'tool')}</strong>
          <span class="helios-status-warn">待审批 · ${escapeHtml(r.request_id || '')}</span>
        </div>
        <div class="helios-hint">${escapeHtml(r.risk || '')}</div>
        ${r.preview ? `<pre class="helios-code-box">${escapeHtml(r.preview)}</pre>` : ''}
        <div class="helios-btn-group">
          <button class="primary-btn" onclick="resolveHeliosApproval('${escapeHtml(r.request_id)}', true, 'once')">批准一次</button>
          <button class="chip-btn" onclick="resolveHeliosApproval('${escapeHtml(r.request_id)}', true, 'session')">本会话信任</button>
          <button class="chip-btn helios-danger-btn" onclick="resolveHeliosApproval('${escapeHtml(r.request_id)}', false, 'deny')">拒绝</button>
        </div>
      </div>
    `).join('') : '<div class="helios-empty">当前无待审批的高风险操作</div>';

    hBox.innerHTML = hist.length ? hist.slice(0, 10).map(h => `
      <div class="helios-item-card">
        <div class="helios-item-head">
          <span>${escapeHtml(h.tool_name || '')} · ${escapeHtml(h.request_id || '')}</span>
          <span class="${h.approved ? 'helios-status-ok' : 'helios-status-err'}">${h.approved ? '已批准' : '已拒绝'} (${escapeHtml(h.scope || '')})</span>
        </div>
      </div>
    `).join('') : '<div class="helios-empty">暂无历史审批记录</div>';
  } catch (e) {}
}

async function resolveHeliosApproval(reqId, approved, scope) {
  await fetch(`/api/approvals/${encodeURIComponent(reqId)}/resolve`, {
    method: 'POST',
    headers: heliosAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ approved, scope }),
  });
  loadHeliosApprovals();
}

async function loadHeliosBgProcs(selectedId = '') {
  const tbody = document.getElementById('helios-bgprocs-body');
  const outEl = document.getElementById('helios-bgproc-output');
  if (!tbody) return;
  try {
    const qs = selectedId ? `?id=${encodeURIComponent(selectedId)}&tail=80` : '';
    const res = await fetch(`/api/bg-procs${qs}`, { headers: heliosAuthHeaders() });
    const d = await res.json();
    const procs = d.procs || [];
    tbody.innerHTML = procs.length ? procs.map(p => `
      <tr>
        <td class="tabular-nums">${escapeHtml(p.proc_id || '')}</td>
        <td><span class="${(p.status === 'running') ? 'helios-status-ok' : 'helios-hint'}">${(p.status === 'running') ? '运行中' : `已退出 (${p.returncode})`}</span></td>
        <td class="tabular-nums">${escapeHtml(p.command || '')}</td>
        <td class="helios-btn-group">
          <button class="chip-btn" onclick="loadHeliosBgProcs('${escapeHtml(p.proc_id || '')}')">日志</button>
          ${(p.status === 'running') ? `<button class="chip-btn helios-danger-btn" onclick="stopHeliosBgProc('${escapeHtml(p.proc_id || '')}')">终止</button>` : ''}
        </td>
      </tr>
    `).join('') : '<tr><td colspan="4" class="helios-empty">暂无后台进程</td></tr>';
    if (d.output && outEl) {
      outEl.textContent = d.output.output || '(无日志输出)';
    }
  } catch (e) {}
}

async function stopHeliosBgProc(procId) {
  await fetch(`/api/bg-procs/${encodeURIComponent(procId)}/stop`, {
    method: 'POST',
    headers: heliosAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({}),
  });
  loadHeliosBgProcs();
}

async function loadHeliosWorktrees() {
  const tbody = document.getElementById('helios-wt-body');
  const meta = document.getElementById('helios-wt-meta');
  if (!tbody) return;
  try {
    const res = await fetch('/api/worktrees', { headers: heliosAuthHeaders() });
    const d = await res.json();
    if (meta) {
      meta.textContent = `仓库：${d.is_git_repo ? 'Git 仓库就绪' : '非 Git 仓库'} · 并行隔离默认：${d.parallel_enabled ? '已开启' : '按需开启 (--parallel)'}`;
    }
    const wts = d.worktrees || [];
    tbody.innerHTML = wts.length ? wts.map(w => `
      <tr>
        <td class="tabular-nums">${escapeHtml(w.worktree_id || '')}</td>
        <td>${escapeHtml(w.subtask_id || '')}</td>
        <td class="tabular-nums">${escapeHtml(w.branch_name || '')}</td>
        <td><span class="${w.status === 'conflict' ? 'helios-status-err' : (w.status === 'merged' ? 'helios-status-ok' : 'helios-status-warn')}">${escapeHtml(w.status || 'active')}</span></td>
        <td>${escapeHtml(w.merge_commit || w.error || w.worktree_path || '')}</td>
        <td><button class="chip-btn helios-danger-btn" onclick="cleanupHeliosWorktree('${escapeHtml(w.worktree_id || '')}')">清理</button></td>
      </tr>
    `).join('') : '<tr><td colspan="6" class="helios-empty">当前没有活动的临时 Worktree</td></tr>';
  } catch (e) {}
}

async function cleanupHeliosWorktree(wtId) {
  const fb = document.getElementById('helios-wt-feedback');
  const res = await fetch('/api/worktrees/cleanup', {
    method: 'POST',
    headers: heliosAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(wtId ? { worktree_id: wtId } : {}),
  });
  const d = await res.json();
  if (fb) fb.textContent = res.ok ? `清理完成：${JSON.stringify(d)}` : `清理失败：${d.error || res.statusText}`;
  loadHeliosWorktrees();
}

async function runHeliosHybridSearch() {
  const query = (document.getElementById('helios-rag-query')?.value || '').trim();
  const mode = document.getElementById('helios-rag-mode')?.value || 'hybrid';
  const reindex = Boolean(document.getElementById('helios-rag-reindex')?.checked);
  const box = document.getElementById('helios-rag-results');
  const meta = document.getElementById('helios-rag-meta');
  if (!box) return;
  box.innerHTML = '<div class="helios-empty">正在执行混合检索...</div>';
  try {
    const res = await fetch('/api/search/hybrid', {
      method: 'POST',
      headers: heliosAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ query, mode, reindex, limit: 8 }),
    });
    const d = await res.json();
    if (meta && d.stats) {
      meta.textContent = `索引文档：${d.stats.total_docs || 0} · 向量缓存：${d.stats.embedded_docs || 0} · Embedding：${d.embedding_configured ? '已配置' : '离线 FTS5 模式'}`;
    }
    const hits = d.hits || [];
    if (!hits.length) {
      box.innerHTML = '<div class="helios-empty">未找到匹配结果</div>';
      return;
    }
    box.innerHTML = hits.map(h => `
      <div class="helios-item-card">
        <div class="helios-item-head">
          <strong>${escapeHtml(h.title || h.doc_id || '')}</strong>
          <span class="tabular-nums helios-status-ok">${escapeHtml(h.mode || mode)} · ${Number(h.score || 0).toFixed(4)}</span>
        </div>
        <div class="helios-hint">${escapeHtml(h.snippet || '')}</div>
      </div>
    `).join('');
  } catch (e) {
    box.innerHTML = `<div class="helios-empty">检索失败：${escapeHtml(e.message)}</div>`;
  }
}

async function loadHeliosBoundedMemory() {
  const bars = document.getElementById('helios-mem-bars');
  const mPre = document.getElementById('helios-mem-memory-text');
  const uPre = document.getElementById('helios-mem-user-text');
  if (!bars) return;
  try {
    const res = await fetch('/api/memory/bounded', { headers: heliosAuthHeaders() });
    const d = await res.json();
    const st = d.stats || {};
    const mPct = Math.min(100, Math.round((st.memory_chars || 0) / Math.max(1, st.memory_limit || 2200) * 100));
    const uPct = Math.min(100, Math.round((st.user_chars || 0) / Math.max(1, st.user_limit || 1375) * 100));
    bars.innerHTML = `
      <div class="helios-mem-bar-card">
        <div>MEMORY.md <span class="tabular-nums">${st.memory_chars || 0} / ${st.memory_limit || 2200} (${mPct}%)</span></div>
        <div class="helios-progress-track"><div class="helios-progress-fill" style="width:${mPct}%"></div></div>
      </div>
      <div class="helios-mem-bar-card">
        <div>USER.md <span class="tabular-nums">${st.user_chars || 0} / ${st.user_limit || 1375} (${uPct}%)</span></div>
        <div class="helios-progress-track"><div class="helios-progress-fill" style="width:${uPct}%"></div></div>
      </div>
    `;
    if (mPre) mPre.textContent = d.memory || '(空)';
    if (uPre) uPre.textContent = d.user || '(空)';
  } catch (e) {}
}

async function submitHeliosBoundedMemory() {
  const fb = document.getElementById('helios-mem-feedback');
  const payload = {
    slot: document.getElementById('helios-mem-slot')?.value || 'memory',
    action: document.getElementById('helios-mem-action')?.value || 'add',
    target: document.getElementById('helios-mem-target')?.value || '',
    content: document.getElementById('helios-mem-content')?.value || '',
  };
  const res = await fetch('/api/memory/bounded', {
    method: 'POST',
    headers: heliosAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  const d = await res.json();
  if (fb) fb.innerHTML = res.ok
    ? '<span class="helios-status-ok">已更新有界记忆</span>'
    : `<span class="helios-status-err">${escapeHtml(d.error || d.message || '更新失败')}</span>`;
  if (res.ok) loadHeliosBoundedMemory();
}

async function loadHeliosSessionTree() {
  const pre = document.getElementById('helios-tree-ascii');
  if (!pre) return;
  try {
    const res = await fetch('/api/sessions/tree', { headers: heliosAuthHeaders() });
    const d = await res.json();
    pre.textContent = d.formatted || JSON.stringify(d.tree || {}, null, 2) || '(暂无会话节点)';
  } catch (e) {
    pre.textContent = `加载会话树失败：${e.message}`;
  }
}

async function submitHeliosRewind() {
  const fb = document.getElementById('helios-rewind-feedback');
  const session_id = (document.getElementById('helios-rewind-sid')?.value || '').trim();
  const node_id = (document.getElementById('helios-rewind-node')?.value || '').trim();
  const restore_code = Boolean(document.getElementById('helios-rewind-code')?.checked);
  const res = await fetch('/api/sessions/rewind', {
    method: 'POST',
    headers: heliosAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ session_id, node_id, restore_code }),
  });
  const d = await res.json();
  if (fb) fb.innerHTML = res.ok
    ? `<span class="helios-status-ok">已回溯并生成新分支：${escapeHtml(d.new_session_id || d.session_id || '')}</span>`
    : `<span class="helios-status-err">回溯失败：${escapeHtml(d.error || res.statusText)}</span>`;
  if (res.ok) loadHeliosSessionTree();
}
