/* Syntra Slashes: Multi-Session Autonomous Desktop Execution Agent */
'use strict';

const $ = id => document.getElementById(id);
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const state = {
  sessions: [],
  current: null,
  activeSessionData: null,
  mode: 'background',
  files: [],
  workspace: '',
  health: null,
  eventSources: {},       // session_id -> EventSource
  memoryBySession: {},
  lastEventIds: {},       // session_id -> int
  runningSessionIds: new Set(),
  openTabs: [],           // array of {path, canonical_path, name, language, status, content, total_lines, diff}
  sessionTabs: {},        // session_id -> array of openTabs
  activeFilePath: null,
  filePanelOpen: false,
  initialized: false
};

let toastTimer, searchTimer;

function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.hidden = true, 4500);
}

function currentSession() {
  return state.sessions.find(s => s.id === state.current);
}

function timeLabel(timestamp) {
  const delta = Date.now() - timestamp;
  return delta < 60000 ? 'now' : delta < 3600000 ? `${Math.floor(delta/60000)}m` : delta < 86400000 ? `${Math.floor(delta/3600000)}h` : new Date(timestamp).toLocaleDateString(undefined, {month:'short', day:'numeric'});
}

function shortPath(path) {
  return String(path || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop() || 'Workspace';
}

function renderMarkdown(content) {
  if (window.DOMPurify && window.marked) {
    let raw = marked.parse(content || '');
    // Convert file:// links to clickable data-path links for the right-hand panel
    raw = raw.replace(/href="file:\/\/\/?([^"]+)"/g, 'href="#" class="chat-file-link" data-path="$1"');
    return DOMPurify.sanitize(raw, {
      FORBID_TAGS: ['iframe', 'form', 'input'],
      FORBID_ATTR: ['style']
    });
  }
  return escapeHTML(content).replace(/\n/g, '<br>');
}

function attachFileClickListeners(root) {
  if (!root) return;
  root.querySelectorAll('.activity-file-link, .activity-line-link, .chat-file-link').forEach(el => {
    el.onclick = e => {
      e.preventDefault();
      e.stopPropagation();
      const p = el.dataset.path;
      const line = el.dataset.line ? parseInt(el.dataset.line) : null;
      if (p) openFileInPanel(p, {line, forceOpen: true});
    };
  });
}

function addCodeCopyButtons(root) {
  root.querySelectorAll('pre > code').forEach(code => {
    const pre = code.parentElement;
    if (pre.parentElement.classList.contains('code-block')) return;
    const block = document.createElement('div');
    block.className = 'code-block';
    const toolbar = document.createElement('div');
    toolbar.className = 'code-block-toolbar';
    const label = document.createElement('span');
    label.textContent = [...code.classList].find(c => c.startsWith('language-'))?.slice(9) || 'Code';
    const button = document.createElement('button');
    button.className = 'copy-code-button';
    button.type = 'button';
    button.title = 'Copy code';
    button.setAttribute('aria-label', 'Copy code');
    button.innerHTML = `${icon('copy')}<span>Copy</span>`;
    button.onclick = async () => {
      const copied = await copyText(code.textContent, 'Code copied.');
      if (copied) {
        button.innerHTML = `${icon('check')}<span>Copied</span>`;
        setTimeout(() => { if (button.isConnected) button.innerHTML = `${icon('copy')}<span>Copy</span>`; }, 1800);
      }
    };
    toolbar.append(label, button);
    pre.before(block);
    block.append(toolbar, pre);
  });
}

function ensureSafeLinks(root) {
  addCodeCopyButtons(root);
  root.querySelectorAll('a').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (a.classList.contains('chat-file-link') || a.dataset.path) {
      a.onclick = e => {
        e.preventDefault();
        openFileInPanel(a.dataset.path, {forceOpen: true});
      };
    } else if (!/^https?:/i.test(href)) {
      a.removeAttribute('href');
    } else {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    }
  });
  attachFileClickListeners(root);
}

function scrollChat(force = false) {
  const el = $('conversation');
  if (force || el.scrollHeight - el.clientHeight - el.scrollTop < 160) {
    el.scrollTop = el.scrollHeight;
  }
}

function updateContext() {
  const previous = (state.activeSessionData?.events || []).filter(event => event.type === 'memory' && Array.isArray(event.payload?.recalled_layer_ids)).at(-1)?.payload;
  const memory = state.memoryBySession[state.current] || previous;
  const ids = [...new Set(memory?.recalled_layer_ids || [])];
  const label = ids.length ? `Recalled ${ids.length === 1 ? 'string' : 'strings'} ${ids.slice(0, 2).join(', ')}${ids.length > 2 ? ` +${ids.length - 2}` : ''}` : 'Local strings';
  $('stringsIndicator').querySelector('span').textContent = label;
  $('stringsIndicator').title = ids.length ? `Latest recall used local strings ${ids.join(', ')}. View memory details.` : 'Conversation strings are stored locally. View memory details.';
}

function renderFiles() {
  $('attachments').replaceChildren();
  state.files.forEach((file, index) => {
    const chip = document.createElement('span');
    chip.className = 'attachment-chip';
    chip.innerHTML = `${icon('file')}<span>${escapeHTML(file.name)}</span><button title="Remove" aria-label="Remove ${escapeHTML(file.name)}">×</button>`;
    chip.querySelector('button').onclick = () => {
      state.files.splice(index, 1);
      renderFiles();
    };
    $('attachments').append(chip);
  });
}

function resizePrompt() {
  const el = $('prompt');
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 240) + 'px';
  updateSend();
}

function updateSend() {
  const isRunning = state.runningSessionIds.has(state.current);
  $('sendButton').disabled = !state.initialized || !$('prompt').value.trim() || isRunning;
}

function updateRunningControls() {
  const isRunning = state.runningSessionIds.has(state.current);
  $('sendButton').hidden = isRunning;
  $('stopButton').hidden = !isRunning;
  $('prompt').readOnly = isRunning;
  updateSend();
}

// -------------------------------------------------------------
// Session Management & Switching
// -------------------------------------------------------------

async function loadSessionsList() {
  try {
    const res = await fetch('/api/sessions');
    if (!res.ok) throw new Error();
    const data = await res.json();
    state.sessions = Array.isArray(data.sessions) ? data.sessions : [];
    
    // Update active running set
    state.runningSessionIds.clear();
    for (const s of state.sessions) {
      if (['running', 'waiting_model', 'waiting_desktop', 'stopping'].includes(s.status)) {
        state.runningSessionIds.add(s.id);
      }
    }
    renderSessions();
  } catch (e) {
    toast('Could not refresh sessions list.');
  }
}

function renderSessions() {
  const search = $('sessionSearch').value.toLowerCase().trim();
  const list = $('sessionList');
  list.replaceChildren();

  const filtered = state.sessions.filter(s => (s.title || '').toLowerCase().includes(search));
  $('sessionCount').textContent = state.sessions.length;
  $('stopAllBtn').disabled = state.runningSessionIds.size === 0;

  if (!filtered.length) {
    const p = document.createElement('p');
    p.className = 'empty-sessions';
    p.textContent = search ? 'No matching sessions.' : 'Your next idea starts here.\nSessions will appear as you work.';
    list.append(p);
    return;
  }

  for (const session of filtered) {
    const b = document.createElement('button');
    b.className = 'session-item' + (session.id === state.current ? ' active' : '');
    b.setAttribute('aria-current', session.id === state.current ? 'page' : 'false');
    b.title = session.title;

    const statusBadge = `<span class="session-status-badge ${session.status || 'idle'}" title="Status: ${session.status || 'idle'}"></span>`;
    b.innerHTML = `${icon('chat')}<span class="session-name">${escapeHTML(session.title)}</span><time>${timeLabel(session.updated)}</time>${statusBadge}`;
    
    // Clicking switches session without stopping any background task
    b.onclick = () => selectSession(session.id);
    list.append(b);
  }
}

async function selectSession(id) {
  // Preserve current session's open tabs
  if (state.current && state.current !== id) {
    state.sessionTabs[state.current] = [...state.openTabs];
  }

  state.current = id;
  renderSessions();

  // Restore or initialize this session's tabs
  state.openTabs = state.sessionTabs[id] || [];
  state.activeFilePath = state.openTabs.length ? state.openTabs[0].path : null;
  renderFileTabs();
  if (state.activeFilePath) {
    activateTab(state.activeFilePath);
  } else {
    toggleFilePanel(false);
  }

  try {
    const res = await fetch(`/api/sessions/${id}`);
    if (!res.ok) throw new Error('Session not found');
    const session = await res.json();
    state.activeSessionData = session;

    state.mode = session.mode || 'background';
    setMode(state.mode, false);
    state.workspace = session.workspace || state.workspace;
    updateWorkspace();

    $('sessionTitle').textContent = session.title;
    const hasMessages = (session.messages || []).length > 0;
    $('app').classList.toggle('in-session', hasMessages);
    $('welcome').hidden = hasMessages;
    $('conversation').hidden = !hasMessages;
    $('prompt').placeholder = hasMessages ? 'Keep the momentum going…' : 'What would you like to make happen?';
    $('runStatus').textContent = session.status === 'running' ? 'Working on it…' : session.status === 'paused_limit' ? 'Paused at step limit' : hasMessages ? 'Ready when you are' : 'A fresh start';

    $('conversation').replaceChildren();
    (session.messages || []).forEach(m => renderMessage(m));

    // Replay session activity events into chronological expandable rows mapped to message IDs
    if (session.events && session.events.length) {
      session.events.forEach(ev => {
        if (ev.type === 'action_start' || ev.type === 'observation' || ev.type === 'memory') {
          const payload = ev.payload || {};
          let targetMsg = null;
          if (payload.message_id) {
            targetMsg = $('conversation').querySelector(`[data-message-id="${payload.message_id}"]`);
          }
          if (!targetMsg) {
            targetMsg = $('conversation').querySelector('.message.assistant:last-of-type');
          }
          if (targetMsg) {
            appendActivity(targetMsg, {
              type: ev.type === 'memory' ? 'observation' : ev.type,
              call_id: ev.type === 'memory' ? `memory-${id}-${ev.id || ev.event_id}` : payload.call_id,
              tool: ev.type === 'memory' ? 'local_memory' : payload.tool,
              args: ev.type === 'memory' ? payload : payload.args,
              result: ev.type === 'memory' ? payload : payload.result,
              path: payload.path,
              canonical_path: payload.canonical_path,
              step: ev.step,
              run_id: ev.run_id
            });
          }
        }
      });
    }

    $('conversation').querySelectorAll('.message.assistant').forEach(article => {
      const saved = (session.messages || []).find(message => message.id === article.dataset.messageId);
      setActivityState(article, saved?.status === 'running' ? session.status : saved?.status || 'complete');
    });

    // Render continuation card if paused at step limit
    if (session.status === 'paused_limit') {
      renderContinuationCard();
    }

    updateContext();
    updateRunningControls();
    scrollChat(true);

    // Connect to reconnectable event stream
    // Completed/paused messages already contain their final text. Resume after
    // the stored snapshot instead of appending historical token events again.
    if (!['running','waiting_model','waiting_desktop','stopping','awaiting_approval'].includes(session.status)) {
      state.lastEventIds[id] = Math.max(state.lastEventIds[id] || 0, session.event_high_watermark || 0);
    }
    connectSessionStream(id);
  } catch (e) {
    toast(`Could not load session ${id}.`);
  }
}

async function newSession() {
  const id = crypto.randomUUID();
  const title = 'New session';
  try {
    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id, title, workspace: state.workspace, mode: state.mode})
    });
    if (!res.ok) throw new Error();
    await loadSessionsList();
    state.files = [];
    renderFiles();
    $('prompt').value = '';
    resizePrompt();
    await selectSession(id);
    $('prompt').focus();
  } catch (e) {
    toast('Could not create new session.');
  }
}

// -------------------------------------------------------------
// Reconnectable Event Streams (Last-Event-ID)
// -------------------------------------------------------------

function connectSessionStream(session_id) {
  // If already connected to this session, keep open
  if (state.eventSources[session_id]) return;

  // Close other active streams to save resources
  Object.keys(state.eventSources).forEach(sid => {
    if (sid !== session_id) {
      state.eventSources[sid].close();
      delete state.eventSources[sid];
    }
  });

  const lastId = state.lastEventIds[session_id] || 0;
  const url = `/api/agent/events?session_id=${encodeURIComponent(session_id)}&last_event_id=${lastId}`;
  const es = new EventSource(url);
  state.eventSources[session_id] = es;

  es.onmessage = e => {
    // Heartbeats
  };

  const handleLiveEvent = (eventType, data, eventId) => {
    if (eventId) {
      state.lastEventIds[session_id] = Math.max(state.lastEventIds[session_id] || 0, parseInt(eventId));
    }

    if (eventType === 'status') {
      const s = data.status;
      if (['running', 'waiting_model', 'waiting_desktop', 'stopping'].includes(s)) {
        state.runningSessionIds.add(session_id);
      } else {
        state.runningSessionIds.delete(session_id);
      }
      const item = state.sessions.find(x => x.id === session_id);
      if (item) item.status = s;
      renderSessions();
      if (state.current === session_id) {
        $('runStatus').textContent = s === 'waiting_model' ? 'Waiting in model queue…' : s === 'waiting_desktop' ? 'Waiting for desktop lock…' : s === 'stopping' ? 'Stopping…' : s === 'running' ? 'Working on it…' : 'Ready when you are';
        updateRunningControls();
        setActivityState($('conversation').lastElementChild, s);
      }
    }

    if (state.current !== session_id) return; // Background event for unviewed session

    const conv = $('conversation');
    let lastArticle = conv.lastElementChild;

    if (eventType === 'token') {
      if (!lastArticle || !lastArticle.classList.contains('assistant')) {
        lastArticle = renderMessage({role: 'assistant', content: '', status: 'running'});
      }
      const body = lastArticle.querySelector('.message-body');
      body.dataset.raw = (body.dataset.raw || '') + (data.token || '');
      body.innerHTML = renderMarkdown(body.dataset.raw);
      ensureSafeLinks(body);
      scrollChat();
    } else if (eventType === 'memory') {
      if (!lastArticle || !lastArticle.classList.contains('assistant')) {
        lastArticle = renderMessage({role:'assistant',content:'',status:'running'});
      }
      appendActivity(lastArticle, {type:'observation', tool:'local_memory',
        call_id:`memory-${session_id}-${eventId}`, result:data, args:data});
      if (Array.isArray(data.recalled_layer_ids)) {
        state.memoryBySession[session_id] = data;
        updateContext();
      }
    } else if (eventType === 'action_start' || eventType === 'observation') {
      if (!lastArticle || !lastArticle.classList.contains('assistant')) {
        lastArticle = renderMessage({role: 'assistant', content: '', status: 'running'});
      }
      appendActivity(lastArticle, {type: eventType, ...data});
      $('runStatus').textContent = eventType === 'action_start' ? `Executing ${data.tool}…` : 'Evaluating result…';
    } else if (eventType === 'paused_limit') {
      setActivityState(lastArticle, 'paused_limit');
      state.runningSessionIds.delete(session_id);
      updateRunningControls();
      renderContinuationCard();
    } else if (eventType === 'done' || eventType === 'interrupted' || eventType === 'error') {
      if (eventType === 'done' && typeof data.content === 'string' && lastArticle?.classList.contains('assistant')) {
        const body = lastArticle.querySelector('.message-body');
        body.dataset.raw = data.content;
        body.innerHTML = renderMarkdown(data.content);
        ensureSafeLinks(body);
      }
      setActivityState(lastArticle, eventType === 'done' ? 'complete' : eventType);
      const pending = lastArticle?.querySelector('.pending-text');
      if (pending) pending.remove();
      state.runningSessionIds.delete(session_id);
      updateRunningControls();
      loadSessionsList();
      if (lastArticle && lastArticle.classList.contains('assistant')) {
        const actions = lastArticle.querySelector('.message-actions');
        if (actions) actions.hidden = false;
        const errEl = lastArticle.querySelector('.message-error');
        if (errEl && data.error) {
          errEl.textContent = data.error;
          errEl.hidden = false;
        }
      }
    }
  };

  ['memory', 'status', 'step_start', 'token', 'action_start', 'observation', 'paused_limit', 'done', 'interrupted', 'error'].forEach(evt => {
    es.addEventListener(evt, e => {
      try {
        const data = JSON.parse(e.data);
        handleLiveEvent(evt, data, e.lastEventId);
      } catch (err) {}
    });
  });

  es.onerror = () => {
    // Auto-reconnects natively via EventSource protocol using Last-Event-ID
  };
}

// -------------------------------------------------------------
// Language Syntax Highlighting & Code Viewer (Screenshot Palette)
// -------------------------------------------------------------

function highlightCode(text, language = 'python') {
  const lines = (text || '').split('\n');
  const lang = (language || 'python').toLowerCase();
  const isPyLike = ['python', 'powershell', 'shell', 'bash'].includes(lang);

  const kwSet = new Set(['def', 'class', 'return', 'if', 'else', 'elif', 'for', 'while', 'import', 'from', 'as', 'in', 'try', 'except', 'finally', 'with', 'None', 'True', 'False', 'async', 'await', 'const', 'let', 'var', 'function', 'export', 'default', 'require', 'select', 'where', 'insert', 'update', 'delete', 'echo', 'public', 'private', 'static', 'void', 'new', 'this']);
  const typSet = new Set(['int', 'str', 'float', 'list', 'dict', 'set', 'tuple', 'bool', 'self', 'print', 'len', 'range', 'sum', 'open', 'isinstance', 'document', 'window', 'console', 'Math', 'Array', 'Object', 'String', 'Number']);

  return lines.map((line, idx) => {
    const lineNum = idx + 1;
    if (!line) {
      return `<span class="code-line" data-line="${lineNum}"> </span>`;
    }

    let out = '';
    let i = 0;
    const len = line.length;

    while (i < len) {
      // 1. Comments
      if ((isPyLike && line[i] === '#') || (!isPyLike && line[i] === '/' && line[i + 1] === '/')) {
        const commentText = line.slice(i);
        out += `<span class="tok-cmt">${escapeHTML(commentText)}</span>`;
        break;
      }

      // 2. Strings
      if (line[i] === '"' || line[i] === "'" || line[i] === '`') {
        const quote = line[i];
        let j = i + 1;
        while (j < len && line[j] !== quote) {
          if (line[j] === '\\') j++;
          j++;
        }
        if (j < len) j++;
        const strText = line.slice(i, j);
        out += `<span class="tok-str">${escapeHTML(strText)}</span>`;
        i = j;
        continue;
      }

      // 3. Numbers
      if (/\d/.test(line[i]) && (i === 0 || !/[a-zA-Z0-9_$]/.test(line[i - 1]))) {
        let j = i;
        while (j < len && /[\d.]/.test(line[j])) j++;
        out += `<span class="tok-num">${escapeHTML(line.slice(i, j))}</span>`;
        i = j;
        continue;
      }

      // 4. Identifiers / Keywords / Types
      if (/[a-zA-Z_$]/.test(line[i])) {
        let j = i;
        while (j < len && /[a-zA-Z0-9_$]/.test(line[j])) j++;
        const word = line.slice(i, j);
        if (kwSet.has(word)) {
          out += `<span class="tok-kw">${escapeHTML(word)}</span>`;
        } else if (typSet.has(word)) {
          out += `<span class="tok-typ">${escapeHTML(word)}</span>`;
        } else {
          out += escapeHTML(word);
        }
        i = j;
        continue;
      }

      // 5. Plain whitespace / punctuation
      out += escapeHTML(line[i]);
      i++;
    }

    return `<span class="code-line" data-line="${lineNum}">${out || ' '}</span>`;
  }).join('');
}

function renderDiff(diffText) {
  const lines = (diffText || '').split('\n');
  return lines.map(line => {
    const esc = escapeHTML(line);
    if (line.startsWith('+++') || line.startsWith('---')) {
      return `<span class="diff-line diff-hunk-line">${esc}</span>`;
    } else if (line.startsWith('@@')) {
      return `<span class="diff-line diff-hunk-line">${esc}</span>`;
    } else if (line.startsWith('+')) {
      return `<span class="diff-line diff-add-line">${esc}</span>`;
    } else if (line.startsWith('-')) {
      return `<span class="diff-line diff-del-line">${esc}</span>`;
    }
    return `<span class="diff-line">${esc || ' '}</span>`;
  }).join('');
}

function toggleFilePanel(force = null) {
  const panel = $('filePanel');
  if (!panel) return;
  const shouldOpen = force !== null ? force : panel.hidden;
  panel.hidden = !shouldOpen;
  $('app').classList.toggle('has-file-panel', shouldOpen);
  state.filePanelOpen = shouldOpen;
  $('toggleFilePanel')?.classList.toggle('active', shouldOpen);
}

function renderFileTabs() {
  const tabsContainer = $('filePanelTabs');
  if (!tabsContainer) return;
  tabsContainer.replaceChildren();

  if (!state.openTabs.length) {
    $('fileMetaPath').textContent = 'No file open';
    $('fileMetaStatus').textContent = 'None';
    $('fileMetaStatus').className = 'file-status-tag';
    $('fileMetaLines').textContent = '0 lines';
    $('codeGutter').replaceChildren();
    $('codeBody').textContent = 'Select or click a file from chat to view its code.';
    $('editorContainer').hidden = false;
    $('diffContainer').hidden = true;
    return;
  }

  state.openTabs.forEach(tab => {
    const btn = document.createElement('button');
    btn.className = 'file-tab' + (tab.path === state.activeFilePath ? ' active' : '');
    btn.role = 'tab';
    btn.innerHTML = `<span class="tab-icon">${icon('code')}</span><span>${escapeHTML(tab.name)}</span><span class="tab-close" title="Close tab">×</span>`;
    btn.onclick = e => {
      if (e.target.classList.contains('tab-close')) {
        e.stopPropagation();
        closeFileTab(tab.path);
      } else {
        activateTab(tab.path);
      }
    };
    tabsContainer.append(btn);
  });
}

async function openFileInPanel(path, {line = null, diff = null, status = 'inspected', forceOpen = true} = {}) {
  if (!path) return;
  if (forceOpen) toggleFilePanel(true);

  // Tab identity must match by canonical path or exact path (never by simple basename)
  let tab = state.openTabs.find(t => t.canonical_path === path || t.path === path);

  if (!tab) {
    try {
      const res = await fetch(`/api/file?path=${encodeURIComponent(path)}&session_id=${encodeURIComponent(state.current || '')}`);
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Failed to read file.');
      }
      const data = await res.json();
      tab = {
        path: data.path,
        canonical_path: data.canonical_path || data.path,
        name: data.name,
        language: data.language,
        content: data.content,
        total_lines: data.total_lines,
        size: data.size,
        status: status,
        diff: diff || null
      };
      state.openTabs.push(tab);
    } catch (e) {
      toast(`Could not open ${shortPath(path)}: ${e.message}`);
      return;
    }
  } else {
    if (diff) tab.diff = diff;
    if (status) tab.status = status;
  }

  activateTab(tab.path, {line, showDiff: Boolean(diff && !line)});
}

function activateTab(path, {line = null, showDiff = false} = {}) {
  const tab = state.openTabs.find(t => t.path === path || t.canonical_path === path);
  if (!tab) return;

  state.activeFilePath = tab.path;
  renderFileTabs();

  $('fileMetaPath').textContent = tab.canonical_path || tab.path;
  $('fileMetaPath').title = tab.canonical_path || tab.path;
  $('fileMetaStatus').textContent = (tab.status || 'inspected').toUpperCase();
  $('fileMetaStatus').className = `file-status-tag ${(tab.status || 'inspected').toLowerCase()}`;
  $('fileMetaLines').textContent = `${tab.total_lines} lines · ${(tab.size || 0).toLocaleString()} bytes`;

  if (showDiff && tab.diff) {
    $('editorContainer').hidden = true;
    $('diffContainer').hidden = false;
    $('diffHeader').innerHTML = `Unified Diff for <strong>${escapeHTML(tab.name)}</strong>`;
    $('diffContent').innerHTML = renderDiff(tab.diff);
  } else {
    $('diffContainer').hidden = true;
    $('editorContainer').hidden = false;

    const isImage = ['png', 'jpg', 'jpeg', 'svg', 'gif'].includes((tab.language || '').toLowerCase());
    if (isImage) {
      $('codeGutter').replaceChildren();
      $('codeBody').innerHTML = `<div style="text-align:center;padding:24px"><img src="/api/file/raw?path=${encodeURIComponent(tab.canonical_path || tab.path)}&session_id=${encodeURIComponent(state.current || '')}" alt="${escapeHTML(tab.name)}" style="max-width:100%;max-height:75vh;border-radius:6px;border:1px solid #1e1e26;box-shadow:0 8px 24px rgba(0,0,0,0.6)"></div>`;
    } else {
      const gutterHtml = Array.from({length: tab.total_lines}, (_, i) => `<span>${i + 1}</span>`).join('');
      $('codeGutter').innerHTML = gutterHtml;
      $('codeBody').innerHTML = highlightCode(tab.content, tab.language);

      if (line) {
        setTimeout(() => {
          const targetLine = $('codeBody').querySelector(`.code-line[data-line="${line}"]`);
          if (targetLine) {
            document.querySelectorAll('.highlight-line').forEach(el => el.classList.remove('highlight-line'));
            targetLine.classList.add('highlight-line');
            targetLine.scrollIntoView({behavior: 'smooth', block: 'center'});
          }
        }, 60);
      }
    }
  }
}

function closeFileTab(path) {
  const idx = state.openTabs.findIndex(t => t.path === path || t.canonical_path === path);
  if (idx < 0) return;
  state.openTabs.splice(idx, 1);
  if (state.activeFilePath === path) {
    const nextTab = state.openTabs[Math.max(0, idx - 1)];
    state.activeFilePath = nextTab ? nextTab.path : null;
    if (nextTab) {
      activateTab(nextTab.path);
    } else {
      renderFileTabs();
      toggleFilePanel(false);
    }
  } else {
    renderFileTabs();
  }
}

async function copyActiveFileCode() {
  const tab = state.openTabs.find(t => t.path === state.activeFilePath || t.canonical_path === state.activeFilePath);
  if (tab?.content) {
    await navigator.clipboard.writeText(tab.content);
    toast(`Copied ${tab.name} to clipboard.`);
  }
}

function downloadActiveFile() {
  const tab = state.openTabs.find(t => t.path === state.activeFilePath || t.canonical_path === state.activeFilePath);
  if (tab) {
    const targetPath = tab.canonical_path || tab.path;
    const url = `/api/file/raw?path=${encodeURIComponent(targetPath)}&download=1&session_id=${encodeURIComponent(state.current || '')}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = tab.name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    toast(`Downloaded ${tab.name}`);
  }
}

// -------------------------------------------------------------
// Message & Chronological Expandable Activity Rendering
// -------------------------------------------------------------


function createActivityFeed(article) {
  const feed = document.createElement('details');
  feed.className = 'activity-feed';
  feed.hidden = true;
  feed.open = article.dataset.workState === 'running';
  feed.innerHTML = `<summary class="work-summary">${icon('activity')}<span class="work-label" role="status" aria-live="polite">Working…</span><svg class="work-chevron" aria-hidden="true"><use href="#i-chevron"/></svg><span class="work-indicator" aria-hidden="true"></span></summary><div class="activity-list" role="list" aria-label="Work activity"></div>`;
  return feed;
}

function updateActivitySummary(article) {
  const feed = article.querySelector('.activity-feed');
  if (!feed) return;
  const rows = [...feed.querySelectorAll('.activity-row')];
  feed.hidden = rows.length === 0;
  if (!rows.length) return;
  const active = ['running', 'waiting_model', 'waiting_desktop', 'stopping', 'awaiting_approval'].includes(article.dataset.workState);
  const categories = new Set(rows.map(row => row.dataset.category));
  const descriptions = [
    ['browser', 'using the browser', 'used the browser'],
    ['write', 'editing files', 'edited files'],
    ['execute', 'running commands', 'ran commands'],
    ['search', 'searching files', 'searched files'],
    ['read', 'reading files', 'read files'],
    ['desktop', 'using desktop apps', 'used desktop apps'],
    ['memory', 'recalling local memory', 'recalled local memory'],
    ['verify', 'checking results', 'checked results']
  ].filter(([category]) => categories.has(category)).map(item => item[active ? 1 : 2]);
  let label = descriptions.join(', ') || (active ? 'working' : 'finished working');
  label = label[0].toUpperCase() + label.slice(1);
  const workState = article.dataset.workState;
  const prefix = {waiting_model: 'Waiting for model', waiting_desktop: 'Waiting for desktop', awaiting_approval: 'Waiting for approval', stopping: 'Stopping', paused_limit: 'Paused', interrupted: 'Stopped', stopped: 'Stopped', error: 'Stopped with an error', failed: 'Stopped with an error'}[workState];
  if (prefix) label = `${prefix} · ${label[0].toLowerCase() + label.slice(1)}`;
  else if (active) label = `Working · ${label[0].toLowerCase() + label.slice(1)}`;
  const failed = rows.filter(row => row.dataset.state === 'error').length;
  if (failed) label += ` · ${failed} failed ${failed === 1 ? 'action' : 'actions'}`;
  const labelNode = feed.querySelector('.work-label');
  if (labelNode.textContent !== label) labelNode.textContent = label;
  feed.querySelector('.work-summary').title = label;
  feed.classList.toggle('is-working', active);
}

function setActivityState(article, workState) {
  if (!article || !article.classList.contains('assistant')) return;
  article.dataset.workState = workState;
  const active = ['running', 'waiting_model', 'waiting_desktop', 'stopping', 'awaiting_approval'].includes(workState);
  const actions = article.querySelector('.message-actions');
  if (actions) {
    actions.hidden = active;
    const label = actions.querySelector('.response-state');
    if (label) label.textContent = active ? 'Working' : ['interrupted', 'stopped'].includes(workState) ? 'Stopped' : ['error', 'failed'].includes(workState) ? 'Failed' : workState === 'paused_limit' ? 'Paused' : 'Complete';
  }
  if (!active) {
    article.querySelectorAll('.activity-row[data-state="running"]').forEach(row => {
      row.dataset.state = workState === 'error' || workState === 'failed' ? 'error' : 'interrupted';
      row.querySelector('.activity-row-status').textContent = row.dataset.state === 'error' ? 'Failed' : 'Interrupted';
    });
  }
  updateActivitySummary(article);
}

function activityPresentation(tool, args, result, isStart, path) {
  const failed = !isStart && (result.success === false || result.error || (result.exit_code != null && Number(result.exit_code) !== 0));
  let category = 'desktop', glyph = 'activity', title = '';
  const verb = (present, past) => isStart ? present : past;
  const file = value => `<span class="activity-filename">${escapeHTML(shortPath(value))}</span>`;
  if (tool === 'read_document' || tool === 'read_image' || tool === 'read_skill' || tool === 'list_skills') {
    category = 'read'; glyph = 'file';
    title = `${verb('Reading','Read')} ${escapeHTML(path ? shortPath(path) : tool === 'read_skill' ? result.name || 'skill instructions' : 'installed skills')}`;
  } else if (tool === 'write_file') {
    category = 'write'; glyph = 'edit';
    const diff = String(result.diff || '');
    const lines = diff.split('\n');
    const added = lines.filter(line => line.startsWith('+') && !line.startsWith('+++')).length;
    const removed = lines.filter(line => line.startsWith('-') && !line.startsWith('---')).length;
    const created = diff.includes('--- /dev/null') || result.created === true;
    title = `${verb('Editing', created ? 'Created' : 'Edited')} ${file(path)}`;
    if (!isStart && !failed && diff) title += ` <span class="activity-change">+${added} −${removed}</span>`;
  } else if (tool === 'read_file' || tool === 'list_directory') {
    category = 'read'; glyph = tool === 'list_directory' ? 'folder' : 'file';
    title = `${verb('Reading', 'Read')} ${file(path || args.path || args.directory || '')}`;
  } else if (['run_python', 'run_powershell', 'start_process', 'poll_process', 'stop_process'].includes(tool)) {
    category = 'execute'; glyph = 'terminal';
    const target = args.command || args.script_path || args.path || args.executable || (args.pid ? `process ${args.pid}` : 'command');
    title = `${verb(tool === 'stop_process' ? 'Stopping' : tool === 'poll_process' ? 'Checking' : 'Running', tool === 'stop_process' ? 'Stopped' : tool === 'poll_process' ? 'Checked' : 'Ran')} ${escapeHTML(target)}`;
  } else if (['find_folder', 'search_filesystem', 'search_file_content'].includes(tool)) {
    category = 'search'; glyph = 'search';
    title = `${verb('Searching', 'Searched')} ${escapeHTML(args.query || args.pattern || args.text || 'files')}`;
  } else if (tool === 'local_memory' || tool === 'recall_memory') {
    category = 'memory'; glyph = 'memory';
    title = result.dossier ? 'Saved local memory dossier' : `${verb('Searching', 'Recalled')} local memory${args.query ? ` · ${escapeHTML(args.query)}` : ''}`;
  } else if (tool === 'complete_task' || tool === 'register_artifact') {
    category = 'verify'; glyph = 'check';
    title = tool === 'complete_task' ? verb('Checking task completion', 'Checked task completion') : `${verb('Registering', 'Registered')} ${escapeHTML(args.title || 'artifact')}`;
  } else {
    const labels = {
      inspect_environment: ['Checking environment', 'Checked environment'],
      launch_app: [`Opening ${args.app_name || 'application'}`, `Opened ${args.app_name || 'application'}`],
      switch_window: [`Finding ${args.title || 'window'}`, `Selected ${args.title || 'window'}`],
      inspect_ui: ['Inspecting application', 'Inspected application'],
      take_screenshot: ['Capturing screenshot', 'Captured screenshot'],
      open_path: [`Opening ${path || args.url || 'item'}`, `Opened ${path || args.url || 'item'}`],
      type_text: ['Entering text', 'Entered text'], press_hotkey: ['Pressing keyboard shortcut', 'Pressed keyboard shortcut'],
      mouse_move: ['Moving pointer', 'Moved pointer'], mouse_click: ['Clicking application', 'Clicked application'],
      mouse_drag: ['Dragging in application', 'Dragged in application'], mouse_scroll: ['Scrolling application', 'Scrolled application']
    };
    const label = labels[tool] || [`Using ${tool.replaceAll('_', ' ')}`, `Used ${tool.replaceAll('_', ' ')}`];
    title = escapeHTML(label[isStart ? 0 : 1]);
    // A browser category is shown only when the actual target is a URL.
    if (tool === 'open_path' && /^https?:\/\//i.test(path || args.url || '')) { category = 'browser'; glyph = 'globe'; }
    if (tool === 'inspect_environment') { category = 'verify'; glyph = 'check'; }
  }
  if (failed) title = `Failed · ${title}`;
  return {category, glyph, title, state: isStart ? 'running' : failed ? 'error' : 'complete'};
}

function renderMessage(message) {
  const article = document.createElement('article');
  article.className = 'message ' + message.role;
  article.dataset.messageId = message.id || '';
  const timestamp = new Date(message.time || Date.now()).toLocaleTimeString(undefined, {hour:'2-digit', minute:'2-digit'});
  const isUser = message.role === 'user';

  article.innerHTML = `<div class="message-heading"><span class="message-avatar ${isUser ? '' : 'assistant-avatar'}">${isUser ? 'RY' : icon('spark')}</span><span>${isUser ? 'You' : 'Syntra'} <span style="color:#776982;font-weight:400">/ Max Aperion</span></span><time>${timestamp}</time></div>`;

  if (isUser) {
    const body = document.createElement('div');
    body.className = 'user-content';
    body.textContent = message.content;
    article.append(body);
    if (message.files?.length) {
      const label = document.createElement('div');
      label.className = 'attachment-label';
      label.textContent = message.files.map(f => f.name).join(' · ');
      article.append(label);
    }
  } else {
    article.dataset.workState = message.status || 'complete';
    article.append(createActivityFeed(article));

    const body = document.createElement('div');
    body.className = 'message-body';
    body.dataset.raw = message.content || '';
    body.innerHTML = message.content ? renderMarkdown(message.content) : '<span class="pending-text">Investigating and executing…</span>';
    ensureSafeLinks(body);
    article.append(body);

    const error = document.createElement('div');
    error.className = 'message-error';
    error.hidden = !message.error;
    error.textContent = message.error || '';
    article.append(error);

    const actions = document.createElement('div');
    actions.className = 'message-actions';
    actions.hidden = message.status === 'running';
    actions.innerHTML = `<button class="icon-button copy-response" title="Copy response" aria-label="Copy response">${icon('copy')}</button><span class="response-state">${message.status === 'interrupted' ? 'Stopped' : message.status === 'error' ? 'Failed' : 'Complete'}</span>`;
    actions.querySelector('button').onclick = () => copyText(body.dataset.raw);
    article.append(actions);
  }

  $('conversation').append(article);
  return article;
}

function appendActivity(article, event) {
  let feed = article.querySelector('.activity-feed');
  if (!feed) {
    feed = createActivityFeed(article);
    const body = article.querySelector('.message-body');
    article.insertBefore(feed, body);
  }

  const tool = event.tool || '';
  const step = event.step || 0;
  const isStart = event.type === 'action_start';
  const callId = event.call_id || event.payload?.call_id || (event.step ? `act-${event.run_id || 'run'}-${event.step}-${tool}` : `act-${Date.now()}`);

  let row = [...feed.querySelectorAll('.activity-row')].find(item => item.dataset.actId === String(callId));
  if (!row) {
    row = document.createElement('details');
    row.className = 'activity-row';
    row.setAttribute('role', 'listitem');
    row.dataset.actId = callId;
    feed.querySelector('.activity-list').append(row);
  }

  // Preserve arguments on row so observation turn never loses filenames or parameters
  if (isStart && event.args) {
    row._args = event.args;
  }
  const effectiveArgs = event.args || row._args || {};
  const effectivePath = event.canonical_path || event.path || event.result?.canonical_path || event.result?.path || effectiveArgs.path || effectiveArgs.script_path || '';

  let category = 'read';
  let title = '';
  let pills = [];
  let detailsHtml = '';

  if (['read_document','read_image','read_skill','list_skills'].includes(tool)) {
    category = 'read';
    title = `${isStart ? 'Reading' : 'Read'} ${escapeHTML(effectivePath || tool.replaceAll('_',' '))}`;
    const result = event.result || {};
    detailsHtml = `<pre class="activity-pre">${escapeHTML(isStart ? JSON.stringify(effectiveArgs,null,2) : result.output || JSON.stringify(result,null,2))}</pre>${result.warning ? `<p>${escapeHTML(result.warning)}</p>` : ''}`;
  } else if (tool === 'local_memory') {
    category = 'search';
    const memory = event.result || {};
    title = memory.dossier ? 'Saved local memory dossier' : `Recalled ${(memory.recalled_layer_ids || []).length} local memory layer(s)`;
    detailsHtml = memory.dossier
      ? `<a class="activity-file-link" data-path="${escapeHTML(memory.dossier.path)}">${escapeHTML(memory.dossier.filename)}</a><p>Extracted facts with source references; original history retained.</p>`
      : `<div class="activity-field"><strong>Recent context:</strong> ${memory.hot_tokens}/${memory.hot_limit} tokens</div><div class="activity-field"><strong>Recalled evidence:</strong> ${memory.recall_tokens}/${memory.recall_limit} tokens</div><div class="activity-field"><strong>Source layers:</strong> ${escapeHTML((memory.recalled_layer_ids || []).join(', ') || 'No matching older facts')}</div><div class="activity-field"><strong>Preparation:</strong> ${memory.retrieval_ms} ms</div>`;
  } else if (tool === 'find_folder') {
    category = 'search';
    const query = effectiveArgs.query || '';
    if (isStart) {
      title = `Searching folders for “${escapeHTML(query)}”…`;
      pills.push('<span class="pill pill-cyan">Searching</span>');
      detailsHtml = `
        <div class="activity-field"><strong>Query:</strong> <span>${escapeHTML(query)}</span></div>
        <div class="activity-field"><strong>Status:</strong> <span>Deep bounded search across Windows user folders and workspace…</span></div>
      `;
    } else {
      const res = event.result || {};
      const matches = res.matches || res.folders || [];
      title = `Searched ${res.searched_locations?.length || 5} locations · found ${matches.length} matching folder(s)`;
      pills.push(`<span class="pill pill-green">${matches.length} match(es)</span>`);

      let matchesHtml = matches.map(m => `
        <div style="margin:4px 0">
          <a class="activity-file-link" data-path="${escapeHTML(m.path)}">${icon('folder')} ${escapeHTML(m.path)}</a>
          ${m.canonical_path && m.canonical_path !== m.path ? `<span style="color:#71717a;font-size:10px"> (Canonical: ${escapeHTML(m.canonical_path)})</span>` : ''}
        </div>
      `).join('');

      detailsHtml = `
        <div class="activity-field"><strong>Query:</strong> <span>${escapeHTML(query)}</span></div>
        <div class="activity-field"><strong>Locations:</strong> <span>${(res.searched_locations || []).map(l => escapeHTML(shortPath(l))).join(' · ') || 'Desktop, Downloads, Documents'}</span></div>
        <div class="activity-field"><strong>Matches:</strong> <div style="flex:1">${matchesHtml || 'No matches found.'}</div></div>
        <div class="activity-field"><strong>Duration:</strong> <span>${res.duration_ms || 20}ms</span></div>
      `;
    }
  } else if (tool === 'search_filesystem') {
    category = 'search';
    const pattern = effectiveArgs.pattern || effectiveArgs.query || '*';
    if (isStart) {
      title = `Searching filesystem for “${escapeHTML(pattern)}”…`;
      pills.push('<span class="pill pill-cyan">Searching</span>');
      detailsHtml = `<div class="activity-field"><strong>Pattern:</strong> <span>${escapeHTML(pattern)}</span></div>`;
    } else {
      const res = event.result || {};
      const count = res.total_matches || (res.matches || []).length;
      title = `Filesystem search for “${escapeHTML(pattern)}” · found ${count} item(s)`;
      pills.push(`<span class="pill pill-green">${count} found</span>`);
      let listHtml = (res.matches || []).slice(0, 20).map(m => `
        <div><a class="activity-file-link" data-path="${escapeHTML(m.path)}">${escapeHTML(m.path)}</a></div>
      `).join('');
      detailsHtml = `
        <div class="activity-field"><strong>Pattern:</strong> <span>${escapeHTML(pattern)}</span></div>
        <div class="activity-field"><strong>Results:</strong> <div style="flex:1">${listHtml || 'None'}</div></div>
        <div class="activity-field"><strong>Duration:</strong> <span>${res.duration_ms || 30}ms</span></div>
      `;
    }
  } else if (tool === 'search_file_content') {
    category = 'search';
    const query = effectiveArgs.query || effectiveArgs.text || '';
    if (isStart) {
      title = `Searching file contents for “${escapeHTML(query)}”…`;
      pills.push('<span class="pill pill-cyan">Searching</span>');
      detailsHtml = `<div class="activity-field"><strong>Content Query:</strong> <span>${escapeHTML(query)}</span></div>`;
    } else {
      const res = event.result || {};
      const count = res.total_matches || (res.results || []).length;
      title = `Content search for “${escapeHTML(query)}” · ${count} match(es)`;
      pills.push(`<span class="pill pill-green">${count} matches</span>`);
      let listHtml = (res.results || []).slice(0, 15).map(r => `
        <div style="margin:2px 0"><a class="activity-file-link" data-path="${escapeHTML(r.file)}" data-line="${r.line}">${escapeHTML(shortPath(r.file))}:${r.line}</a> <span style="color:#a1a1aa">${escapeHTML(r.content)}</span></div>
      `).join('');
      detailsHtml = `
        <div class="activity-field"><strong>Query:</strong> <span>${escapeHTML(query)}</span></div>
        <div class="activity-field"><strong>Hits:</strong> <div style="flex:1">${listHtml || 'None'}</div></div>
        <div class="activity-field"><strong>Duration:</strong> <span>${res.duration_ms || 40}ms</span></div>
      `;
    }
  } else if (tool === 'read_file') {
    category = 'read';
    const path = effectivePath || effectiveArgs.path || '';
    const offset = effectiveArgs.line_offset || 1;
    const limit = effectiveArgs.line_limit || 500;
    if (isStart) {
      title = `Reading ${escapeHTML(shortPath(path))}…`;
      pills.push('<span class="pill pill-cyan">Reading</span>');
      detailsHtml = `<div class="activity-field"><strong>File:</strong> <a class="activity-file-link" data-path="${escapeHTML(path)}">${escapeHTML(path)}</a></div>`;
    } else {
      const res = event.result || {};
      const endLine = offset + (res.displayed_lines || res.total_lines || 1) - 1;
      const lineRange = `lines ${offset}–${endLine}`;
      title = `Read ${escapeHTML(shortPath(path))} · ${lineRange}`;
      pills.push(`<span class="pill pill-cyan">${lineRange}</span>`);
      detailsHtml = `
        <div class="activity-field"><strong>Inspected File:</strong> <a class="activity-file-link" data-path="${escapeHTML(path)}" data-line="${offset}">${escapeHTML(path)}</a></div>
        <div class="activity-field"><strong>Line Range:</strong> <a class="activity-line-link" data-path="${escapeHTML(path)}" data-line="${offset}">${lineRange}</a> (${res.total_lines || endLine} total lines)</div>
        <pre class="activity-pre">${escapeHTML((res.output || '').slice(0, 1500))}</pre>
      `;
      if (res.success !== false && path) {
        openFileInPanel(path, {line: offset, status: 'inspected', forceOpen: false});
      }
    }
  } else if (tool === 'write_file') {
    category = 'write';
    const path = effectivePath || effectiveArgs.path || '';
    const content = effectiveArgs.content || '';
    const lineCount = content.split('\n').length;
    if (isStart) {
      title = `Writing ${escapeHTML(shortPath(path))}…`;
      pills.push('<span class="pill pill-cyan">Writing</span>');
      detailsHtml = `<div class="activity-field"><strong>Target:</strong> <a class="activity-file-link" data-path="${escapeHTML(path)}">${escapeHTML(path)}</a></div>`;
    } else {
      const res = event.result || {};
      const diff = res.diff || '';
      let added = 0, deleted = 0;
      diff.split('\n').forEach(l => {
        if (l.startsWith('+') && !l.startsWith('+++')) added++;
        if (l.startsWith('-') && !l.startsWith('---')) deleted++;
      });
      const isNew = res.created === true || diff.includes('--- /dev/null');
      const changeText = isNew ? `+${added || lineCount} lines` : `+${added} / −${deleted} lines`;
      title = `${isNew ? 'Created' : 'Edited'} ${escapeHTML(shortPath(path))} · ${changeText}`;
      if (added > 0) pills.push(`<span class="pill pill-green">+${added || lineCount}</span>`);
      if (deleted > 0) pills.push(`<span class="pill pill-red">−${deleted}</span>`);

      detailsHtml = `
        <div class="activity-field"><strong>Status:</strong> <span class="file-status-tag ${isNew ? 'created' : 'modified'}">${isNew ? 'CREATED' : 'MODIFIED'}</span></div>
        <div class="activity-field"><strong>File:</strong> <a class="activity-file-link" data-path="${escapeHTML(path)}">${escapeHTML(path)}</a></div>
        <div class="activity-field"><strong>Changes:</strong> <span style="color:#4ade80">+${added}</span> / <span style="color:#f87171">−${deleted}</span> lines</div>
        ${diff ? `<button class="diff-view-btn" data-diff-path="${escapeHTML(path)}">${icon('code')} Open Diff in Right Panel</button>
                  <pre class="activity-pre">${escapeHTML(diff.slice(0, 1200))}</pre>` : ''}
      `;
      if (path && res.success !== false) {
        openFileInPanel(path, {diff, status: isNew ? 'created' : 'modified', forceOpen: false});
      }
    }
  } else if (tool === 'run_python' || tool === 'run_powershell') {
    category = 'execute';
    const script = effectivePath || effectiveArgs.path || effectiveArgs.script_path || effectiveArgs.command || '';
    if (isStart) {
      title = `Running ${escapeHTML(shortPath(script))}…`;
      pills.push('<span class="pill pill-amber">Running</span>');
      detailsHtml = `<div class="activity-field"><strong>Executing:</strong> <span>${escapeHTML(script)}</span></div>`;
    } else {
      const res = event.result || {};
      const hasCode = res.exit_code !== undefined && res.exit_code !== null;
      const code = hasCode ? res.exit_code : null;
      const isSuccess = res.success !== false && (code === 0 || (!hasCode && Boolean(res.output)));
      const badgeText = hasCode ? `exit ${code}` : (res.success === false ? 'failed' : 'executed');

      title = `Ran ${escapeHTML(shortPath(script))} · ${badgeText}`;
      pills.push(`<span class="pill ${isSuccess ? 'pill-green' : 'pill-red'}">${badgeText}</span>`);

      const out = res.stdout || res.output || '';
      const err = res.stderr || '';
      detailsHtml = `
        <div class="activity-field"><strong>Target:</strong> ${tool === 'run_python' && script ? `<a class="activity-file-link" data-path="${escapeHTML(script)}">${escapeHTML(script)}</a>` : `<span>${escapeHTML(script)}</span>`}</div>
        <div class="activity-field"><strong>Status:</strong> <span style="color:${isSuccess ? '#4ade80' : '#f87171'}">${badgeText.toUpperCase()}</span></div>
        <div class="activity-field"><strong>Duration:</strong> <span>${res.duration_ms || 400}ms</span></div>
        ${out ? `<div style="margin-top:6px"><strong>Stdout:</strong><pre class="activity-pre">${escapeHTML(out)}</pre></div>` : ''}
        ${err ? `<div style="margin-top:6px"><strong>Stderr:</strong><pre class="activity-pre" style="color:#f87171">${escapeHTML(err)}</pre></div>` : ''}
      `;
    }
  } else if (tool === 'start_process' || tool === 'poll_process' || tool === 'stop_process') {
    category = 'execute';
    const pid = event.result?.pid || effectiveArgs.pid || '';
    title = `${tool.replace('_', ' ').toUpperCase()} ${pid ? `(PID ${pid})` : ''}`;
    pills.push(`<span class="pill pill-cyan">${tool}</span>`);
    detailsHtml = `<pre class="activity-pre">${escapeHTML(JSON.stringify(event.result || effectiveArgs, null, 2))}</pre>`;
  } else if (tool === 'register_artifact') {
    category = 'verify';
    const titleText = effectiveArgs.title || event.result?.artifact?.title || 'Artifact';
    const pathText = effectivePath || effectiveArgs.path || '';
    title = `Registered artifact “${escapeHTML(titleText)}”`;
    pills.push('<span class="pill pill-green">Artifact</span>');
    detailsHtml = `
      <div class="activity-field"><strong>Artifact:</strong> <span>${escapeHTML(titleText)}</span></div>
      <div class="activity-field"><strong>Path:</strong> <a class="activity-file-link" data-path="${escapeHTML(pathText)}">${escapeHTML(pathText)}</a></div>
    `;
  } else if (tool === 'complete_task') {
    category = 'verify';
    const sum = effectiveArgs.summary || (event.result?.summary) || 'Task verified and finished.';
    title = `Verified & completed · ${escapeHTML(sum.slice(0, 60))}`;
    pills.push('<span class="pill pill-green">Verified</span>');
    detailsHtml = `<div class="activity-field"><strong>Summary:</strong> <span>${escapeHTML(sum)}</span></div>`;
  } else {
    category = 'desktop';
    title = `${escapeHTML(tool)} (Step ${step})`;
    detailsHtml = `<pre class="activity-pre">${escapeHTML(JSON.stringify(effectiveArgs || event.result, null, 2))}</pre>`;
  }

  const presentation = activityPresentation(tool, effectiveArgs, event.result || {}, isStart, effectivePath);
  if (presentation.state === 'error') {
    detailsHtml = `<div class="activity-field"><strong>Action failed</strong><span>The action did not finish successfully.</span></div><pre class="activity-pre">${escapeHTML(JSON.stringify(event.result || {}, null, 2))}</pre>`;
  }
  const wasOpen = row.open;
  row.dataset.category = presentation.category;
  row.dataset.state = presentation.state;
  row.innerHTML = `
    <summary class="activity-summary">
      <span class="activity-icon-badge">${icon(presentation.glyph)}</span>
      <span class="activity-title">${presentation.title}</span>
      <span class="activity-row-status">${presentation.state === 'running' ? 'Running' : presentation.state === 'error' ? 'Failed' : 'Complete'}</span>
      <span class="activity-running-dot" aria-hidden="true"></span>
      <svg class="activity-chevron-icon" aria-hidden="true"><use href="#i-chevron"/></svg>
    </summary>
    <div class="activity-details">${detailsHtml}</div>
  `;
  row.open = wasOpen;

  const sumEl = row.querySelector('.activity-summary');
  const detEl = row.querySelector('.activity-details');

  if (tool === 'write_file' && !isStart && event.result?.success !== false) {
    const copyButton = document.createElement('button');
    copyButton.type = 'button';
    copyButton.className = 'copy-code-button copy-generated-file';
    copyButton.title = 'Copy generated code';
    copyButton.setAttribute('aria-label', 'Copy generated code');
    copyButton.innerHTML = icon('copy');
    copyButton.onclick = async e => {
      e.stopPropagation();
      try {
        let content = effectiveArgs.content;
        if (typeof content !== 'string') {
          const response = await fetch(`/api/file?path=${encodeURIComponent(effectivePath)}&session_id=${encodeURIComponent(state.current || '')}`);
          if (!response.ok) throw new Error('Could not read generated code.');
          content = (await response.json()).content;
        }
        if (await copyText(content, 'Generated code copied.')) {
          copyButton.innerHTML = icon('check');
          setTimeout(() => { if (copyButton.isConnected) copyButton.innerHTML = icon('copy'); }, 1800);
        }
      } catch (error) { toast(error.message || 'Could not copy generated code.'); }
    };
    detEl.prepend(copyButton);
  }
  updateActivitySummary(article);
  article.querySelector('.pending-text')?.remove();

  attachFileClickListeners(detEl);
  detEl.querySelectorAll('[data-diff-path]').forEach(btn => {
    btn.onclick = () => {
      const p = btn.dataset.diffPath;
      if (p) openFileInPanel(p, {diff: event.result?.diff, forceOpen: true});
    };
  });

  scrollChat();
}

function renderContinuationCard() {
  const existing = document.querySelector('.continue-card');
  if (existing) existing.remove();

  const card = document.createElement('div');
  card.className = 'continue-card';
  card.innerHTML = `<span><strong>Step Limit Reached:</strong> Syntra completed 15 investigative steps. Progress is preserved.</span><button class="continue-btn" id="continueBtn">Continue Task</button>`;
  card.querySelector('#continueBtn').onclick = () => submitContinuation();
  $('conversation').append(card);
  scrollChat(true);
}

// -------------------------------------------------------------
// User Submission & Actions
// -------------------------------------------------------------

async function submit() {
  const text = $('prompt').value.trim();
  if (!text || !state.current || state.runningSessionIds.has(state.current)) return;

  if (text === '/new') { $('prompt').value = ''; newSession(); return; }
  if (text === '/export') { $('prompt').value = ''; resizePrompt(); exportSession(); return; }
  if (text === '/compact') { $('prompt').value = ''; resizePrompt(); await archiveSession(); return; }

  const files = [...state.files];
  state.files = [];
  renderFiles();
  $('prompt').value = '';
  resizePrompt();

  $('app').classList.add('in-session');
  $('welcome').hidden = true;
  $('conversation').hidden = false;

  renderMessage({role: 'user', content: text, files});
  state.runningSessionIds.add(state.current);
  updateRunningControls();
  scrollChat(true);

  try {
    const res = await fetch('/api/agent/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session_id: state.current,
        prompt: text,
        files: files,
        workspace: state.workspace,
        mode: state.mode
      })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to start execution.');
    }
    loadSessionsList();
  } catch (e) {
    state.runningSessionIds.delete(state.current);
    updateRunningControls();
    toast(e.message);
  }
}

async function submitContinuation() {
  const card = document.querySelector('.continue-card');
  if (card) card.remove();

  state.runningSessionIds.add(state.current);
  updateRunningControls();

  try {
    const res = await fetch('/api/agent/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session_id: state.current,
        is_continuation: true,
        workspace: state.workspace,
        mode: state.mode
      })
    });
    if (!res.ok) throw new Error();
  } catch (e) {
    state.runningSessionIds.delete(state.current);
    updateRunningControls();
    toast('Could not continue task.');
  }
}

async function stop() {
  if (!state.current) return;
  $('runStatus').textContent = 'Stopping…';
  try {
    await fetch('/api/agent/stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: state.current})
    });
  } catch (e) {
    toast('Stop request failed.');
  }
}

async function stopAll() {
  try {
    await fetch('/api/agent/stop_all', {method: 'POST'});
    toast('Stopping all active session workers…');
    await loadSessionsList();
  } catch (e) {
    toast('Stop all failed.');
  }
}

function setMode(mode, save = true) {
  state.mode = mode;
  $('modeLabel').textContent = mode === 'transparent' ? 'Transparent' : 'Background';
  $('modeIcon').innerHTML = `<use href="#i-${mode === 'transparent' ? 'screen' : 'terminal'}"/>`;
  $('footerMode').textContent = mode === 'transparent' ? 'Transparent' : 'Background';
  $('desktopNotice').hidden = mode !== 'transparent';
  document.querySelectorAll('.mode-option').forEach(el => el.classList.toggle('selected', el.dataset.mode === mode));
  closeModes();
  if (save && state.current) {
    fetch('/api/sessions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: state.current, mode})
    });
  }
}

function closeModes() {
  $('modeMenu').hidden = true;
  $('modeButton').setAttribute('aria-expanded', 'false');
}

// -------------------------------------------------------------
// Dialogs & Explanations
// -------------------------------------------------------------

function openDialog(title, html) {
  closeModes();
  $('dialogTitle').textContent = title;
  $('dialogBody').innerHTML = html;
  if (!$('dialog').open) $('dialog').showModal();
}

let extensionsData = {skills:[],plugins:[]};
let mcpData = {servers:[]};
let extensionsDiscover = false;
let extensionsFilter = '';

async function extensionsRequest(path,payload) {
  const response = await fetch(path,payload ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)} : {});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Extension request failed.');
  return data;
}

async function showExtensions(discover=false) {
  extensionsDiscover = discover || extensionsDiscover;
  openDialog('Skills, plugins & MCP', `<p class="dialog-copy">Loading local skills…</p>`);
  $('dialog').classList.add('extensions-modal');
  try {
    [extensionsData,mcpData] = await Promise.all([extensionsRequest(`/api/extensions?discover=${extensionsDiscover?1:0}&workspace=${encodeURIComponent(state.workspace || '')}`),extensionsRequest('/api/mcp')]);
    renderExtensions();
  } catch(error) { $('dialogBody').textContent=error.message; }
}

function renderExtensions() {
  const items=extensionsData.skills.filter(item => `${item.name} ${item.provider} ${item.description}`.toLowerCase().includes(extensionsFilter.toLowerCase()));
  $('dialogBody').innerHTML=`<p class="dialog-copy">Built-in skills are ready to use. Import local skill instructions from Codex and Antigravity, then enable the ones you want.</p>
    <div class="extensions-toolbar"><input class="dialog-input" id="skillSearch" type="search" placeholder="Search skills or provider" aria-label="Search skills" value="${escapeHTML(extensionsFilter)}"><button class="secondary-button" id="scanSkills">Scan Codex & Antigravity</button><button class="secondary-button" id="importAllSkills">Import all found</button></div>
    <p class="extensions-note">Imported skills start disabled. Their original apps’ connectors, logins, hooks and model capabilities are not transferred. Review dependencies before enabling.</p>
    <div class="skill-list">${items.map(item=>`<article class="skill-card"><div><strong>${escapeHTML(item.name)}</strong><span class="skill-provider">${escapeHTML(item.provider)}${item.builtin?' · Included':''}</span><p>${escapeHTML(item.description)}</p><small>${escapeHTML(item.compatibility)}</small></div>${item.installed?`<label class="skill-switch"><input type="checkbox" data-skill-enable="${escapeHTML(item.id)}" ${item.enabled?'checked':''}><span>Enabled</span></label>`:`<button class="secondary-button" data-skill-install="${escapeHTML(item.id)}">Import</button>`}</article>`).join('') || '<p class="dialog-copy">No matching skills.</p>'}</div>
    <h3 class="plugin-heading">MCP servers</h3><p class="extensions-note">REA 6.8.0 and a private Node runtime are included. Connect to discover tools. Deep native analysis may need separate engines.</p><div class="mcp-servers">${mcpData.servers.map(server=>`<div class="mcp-server"><div><strong>${escapeHTML(server.name)}</strong><small>${server.connected?`${server.tool_count} tools connected`:server.installed?'Installed · ready to connect':'Runtime missing'}${server.package?` · ${escapeHTML(server.package)}`:''}</small></div><button class="secondary-button" data-mcp-name="${escapeHTML(server.name)}" data-mcp-action="${server.connected?'disconnect':'connect'}">${server.connected?'Disconnect':'Connect'}</button></div>`).join('')}</div>
    <details class="mcp-config"><summary>Add a local MCP server</summary><div class="extensions-toolbar"><input class="dialog-input" id="mcpName" placeholder="Server name" aria-label="MCP server name"><input class="dialog-input" id="mcpCommand" placeholder="C:\\path\\server.exe" aria-label="MCP executable"></div><input class="dialog-input" id="mcpArgs" placeholder='["argument"]' aria-label="MCP arguments as JSON"><button class="secondary-button" id="saveMcp">Save local server</button></details>
    <h3 class="plugin-heading">Local plugin bundles</h3><p class="extensions-note">Plugin bundles group local skills. Import a folder containing plugin.json and its skill folders. Scripts do not execute during installation.</p>
    <div class="plugin-list">${extensionsData.plugins.map(plugin=>`<div class="plugin-row"><strong>${escapeHTML(plugin.name)}</strong><span>${plugin.skills.length} skills · ${plugin.builtin?'Included':'Imported'}</span></div>`).join('')}</div>
    <div class="extensions-toolbar"><input class="dialog-input" id="pluginPath" placeholder="C:\\MyPlugins\\my-plugin" aria-label="Local plugin folder"><button class="secondary-button" id="importPlugin">Import plugin folder</button></div><p class="extensions-note" id="extensionStatus" role="status"></p>`;
  $('skillSearch').oninput=e=>{const start=e.target.selectionStart;extensionsFilter=e.target.value;renderExtensions();$('skillSearch').focus();$('skillSearch').setSelectionRange(start,start);};
  $('scanSkills').onclick=()=>showExtensions(true);
  document.querySelectorAll('[data-mcp-name]').forEach(button=>button.onclick=()=>extensionAction(button,'/api/mcp/'+button.dataset.mcpAction,{name:button.dataset.mcpName}));
  $('saveMcp').onclick=()=>{try{const args=JSON.parse($('mcpArgs').value || '[]');extensionAction($('saveMcp'),'/api/mcp/save',{name:$('mcpName').value,command:$('mcpCommand').value,args,enabled:true});}catch(error){$('extensionStatus').textContent='Arguments must be a JSON array.';}};
  document.querySelectorAll('[data-skill-install]').forEach(button=>button.onclick=()=>extensionAction(button,'/api/extensions/install',{id:button.dataset.skillInstall,workspace:state.workspace}));
  document.querySelectorAll('[data-skill-enable]').forEach(input=>input.onchange=()=>extensionAction(input,'/api/extensions/enable',{id:input.dataset.skillEnable,enabled:input.checked}));
  $('importPlugin').onclick=()=>extensionAction($('importPlugin'),'/api/extensions/plugin',{path:$('pluginPath').value});
  $('importAllSkills').onclick=async()=>{
    const button=$('importAllSkills');button.disabled=true;
    const candidates=extensionsData.skills.filter(item=>!item.installed);let imported=0;let failures=[];
    for(const item of candidates){try{await extensionsRequest('/api/extensions/install',{id:item.id,workspace:state.workspace});imported++;}catch(error){failures.push(`${item.name}: ${error.message}`);}}
    await showExtensions(extensionsDiscover);
    $('extensionStatus').textContent=`Imported ${imported} skills, disabled for review.${failures.length?' '+failures.length+' could not be imported: '+failures.join('; '):''}`;
  };
}

async function extensionAction(button,path,payload){
  button.disabled=true;
  try{await extensionsRequest(path,payload);await showExtensions(extensionsDiscover);}
  catch(error){button.disabled=false;$('extensionStatus').textContent=error.message;}
}

async function showStringDetails() {
  const sessionId = state.current;
  const memory = state.memoryBySession[sessionId] || (state.activeSessionData?.events || []).filter(event => event.type === 'memory' && Array.isArray(event.payload?.recalled_layer_ids)).at(-1)?.payload;
  const ids = [...new Set(memory?.recalled_layer_ids || [])];
  openDialog('Local strings', `
    <p class="dialog-copy">Older conversation and task results are saved as searchable strings on your PC. Syntra retrieves relevant excerpts when needed.</p>
    <div class="detail-row"><span>Latest recalled strings</span><strong>${escapeHTML(ids.join(', ') || 'None in this session yet')}</strong></div>
    <div class="detail-row"><span>Saved strings</span><strong id="savedStrings">${sessionId ? 'Checking…' : 'Start a conversation'}</strong></div>
    <p class="dialog-copy" style="margin-top:14px">The indicator shows strings used in the latest automatic recall. Original conversation history stays saved locally.</p>`);
  if (!sessionId) return;
  try {
    const response = await fetch(`/api/memory/status?session_id=${encodeURIComponent(sessionId)}`);
    if (!response.ok) throw new Error();
    const data = await response.json();
    if ($('savedStrings') && state.current === sessionId) $('savedStrings').textContent = String(data.layers ?? 0);
  } catch (error) {
    if ($('savedStrings')) $('savedStrings').textContent = 'Unavailable';
  }
}

function showModel() {
  const h = state.health;
  openDialog('Meet Max Aperion', `
  <p class="dialog-copy">Your local autonomous agent for code, filesystem discovery, and desktop automation.</p>
  <div class="detail-row"><span>Model</span><strong>Syntra Max Aperion</strong></div>
  <div class="detail-row"><span>Tool Calling</span><strong>Native structured tool calling</strong></div>
  <div class="detail-row"><span>Python Interpreter</span><strong>${escapeHTML(h?.python_interpreter || 'Not found')}</strong></div>
  <div class="detail-row"><span>Desktop Perception</span><strong>Windows UI Automation (UIA) Hierarchy</strong></div>
  <div class="detail-row"><span>Vision Boundary</span><strong>Text LLM · Grounded via UIA element bounds</strong></div>
  <div class="detail-row"><span>Connection Status</span><strong>${escapeHTML(h?.status === 'ready' ? 'Syntra Engine connected and ready' : 'Syntra Engine unavailable')}</strong></div>
  <p class="dialog-copy" style="margin-top:16px">The model operates standard Windows desktop applications via accessibility trees. Perception is grounded directly in Windows UI Automation elements.</p>
  <div class="dialog-actions"><button class="primary-button" id="recheckModel">Re-check System</button></div>`);
  $('recheckModel').onclick = async () => { await checkHealth(); showModel(); };
}

function showWorkspace() {
  openDialog('Your working folder', `
  <p class="dialog-copy">Direct file modifications and script creation are strictly confined to this folder.</p>
  <label class="dialog-label" for="workspacePath">Folder path</label>
  <input class="dialog-input" id="workspacePath" placeholder="C:\\Projects\\my-project" value="${escapeHTML(state.workspace)}">
  <div class="dialog-actions"><button class="secondary-button" id="cancelWorkspace">Cancel</button><button class="primary-button" id="saveWorkspace">Use folder</button></div>`);
  $('cancelWorkspace').onclick = () => $('dialog').close();
  $('saveWorkspace').onclick = async () => {
    try {
      const r = await fetch('/api/workspace/check', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: $('workspacePath').value.trim()})
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error);
      state.workspace = data.path;
      updateWorkspace();
      if (state.current) {
        fetch('/api/sessions', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({id: state.current, workspace: state.workspace})
        });
      }
      $('dialog').close();
      toast('Working folder updated.');
    } catch (e) {
      toast(e.message);
    }
  };
}

function updateWorkspace() {
  const name = shortPath(state.workspace);
  $('workspaceName').textContent = name;
  $('composerWorkspace').textContent = name;
  $('workspaceButton').title = state.workspace;
  $('composerWorkspace').title = state.workspace;
}

function renameSession() {
  const session = currentSession();
  if (!session) return;
  openDialog('Rename session', `
  <label class="dialog-label" for="renameInput">Session name</label>
  <input class="dialog-input" id="renameInput" maxlength="100" value="${escapeHTML(session.title)}">
  <div class="dialog-actions"><button class="primary-button" id="saveName">Save name</button></div>`);
  $('saveName').onclick = async () => {
    const title = $('renameInput').value.trim();
    if (!title) return;
    session.title = title;
    $('sessionTitle').textContent = title;
    await fetch('/api/sessions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: session.id, title})
    });
    renderSessions();
    $('dialog').close();
  };
  $('renameInput').focus();
  $('renameInput').select();
}

function exportSession() {
  const msgs = state.activeSessionData?.messages || [];
  if (!msgs.length) {
    toast('Start a conversation to export a session.');
    return;
  }
  const title = state.activeSessionData?.title || 'Syntra Session';
  const content = `# ${title}\n\nSyntra Slashes Export · ${new Date().toLocaleString()}\nWorkspace: ${state.workspace}\n\n` +
    msgs.map(m => `## ${m.role === 'user' ? 'You' : 'Syntra'}\n\n${m.content}${m.error ? '\n\nError: ' + m.error : ''}\n`).join('\n');
  const url = URL.createObjectURL(new Blob([content], {type: 'text/markdown;charset=utf-8'}));
  const a = document.createElement('a');
  a.href = url;
  a.download = `${title.replace(/[^a-z0-9 -]/gi, '').slice(0, 50) || 'syntra-session'}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('Session exported as Markdown (.md).');
}

async function archiveSession() {
  if (!state.current) return;
  const msgs = state.activeSessionData?.messages || [];
  if (!msgs.length) { toast('Start a conversation first.'); return; }
  try {
    const r = await fetch('/api/session/compact', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: state.current})
    });
    const result = await r.json();
    if (!r.ok) throw new Error(result.error);
    toast(`Saved local memory dossier: ${result.filename}`);
  } catch (e) {
    toast(e.message || 'Could not save transcript.');
  }
}

async function copyText(text, successMessage = 'Response copied.') {
  try {
    await navigator.clipboard.writeText(text);
    toast(successMessage);
    return true;
  } catch (e) {
    toast('Copy is unavailable.');
    return false;
  }
}

async function checkHealth() {
  try {
    const res = await fetch('/api/health');
    if (!res.ok) throw new Error();
    const data = await res.json();
    state.health = data;
    const ready = data.status === 'ready';
    $('engineSidebar').textContent = ready ? 'Max Aperion connected' : data.status === 'missing' ? 'Model not installed' : 'Syntra Engine offline';
    $('engineFooter').textContent = ready ? 'Syntra ready' : data.status === 'missing' ? 'Model unavailable' : 'Syntra offline';
    for (const id of ['engineDot', 'footerDot']) $(id).className = 'status-dot ' + (ready ? 'ready' : 'offline');
    if (!state.workspace) {
      state.workspace = data.workspace;
      updateWorkspace();
    }
  } catch (e) {
    state.health = {status: 'offline'};
    $('engineSidebar').textContent = 'Server offline';
    $('engineFooter').textContent = 'Server offline';
    for (const id of ['engineDot', 'footerDot']) $(id).className = 'status-dot offline';
  }
}

// -------------------------------------------------------------
// Event Listeners Initialization
// -------------------------------------------------------------

$('extensionsButton').onclick = () => showExtensions();
$('dialog').addEventListener('close',()=>$('dialog').classList.remove('extensions-modal'));
$('newSession').onclick = newSession;
$('stopAllBtn').onclick = stopAll;
$('brandHome').onclick = e => { e.preventDefault(); newSession(); };
$('toggleSidebar').onclick = () => {
  $('app').classList.toggle('sidebar-collapsed');
  $('toggleSidebar').setAttribute('aria-expanded', !$('app').classList.contains('sidebar-collapsed'));
};
$('sessionSearch').oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderSessions, 100);
};

$('modeButton').onclick = () => {
  const opening = $('modeMenu').hidden;
  $('modeMenu').hidden = !opening;
  $('modeButton').setAttribute('aria-expanded', opening);
};
document.querySelectorAll('.mode-option').forEach(b => b.onclick = () => setMode(b.dataset.mode));
document.addEventListener('click', e => {
  if (!e.target.closest('#modeMenu') && !e.target.closest('#modeButton')) closeModes();
});

$('sendButton').onclick = submit;
$('stopButton').onclick = stop;
$('prompt').oninput = resizePrompt;
$('prompt').onkeydown = e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submit();
  }
};

$('attachButton').onclick = () => $('fileInput').click();
$('fileInput').onchange = async e => {
  for (const file of e.target.files) {
    if (state.files.length >= 5) { toast('Attach up to 5 files.'); break; }
    const binaryReader=/\.(pdf|docx|png|jpe?g|webp|bmp|tiff)$/i.test(file.name);
    if(binaryReader){
      if(file.size>16*1024*1024){toast(`${file.name} exceeds 16 MB.`);continue;}
      try{
        const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
        const result=await extensionsRequest('/api/documents/attachment',{name:file.name,data});
        state.files.push({name:file.name,content:`[Local reader: ${result.method}; bounded excerpt]\n${result.warning || ''}\n${result.content}`});
        if(result.warning)toast(result.warning);
      }catch(error){toast(`${file.name}: ${error.message}`);}
      continue;
    }
    if (file.size > 150000) { toast(`${file.name} is too large (>150 KB).`); continue; }
    const text = await file.text();
    if (text.includes('\0')) { toast(`${file.name} is not a text file.`); continue; }
    state.files.push({name: file.name, content: text});
  }
  e.target.value = '';
  renderFiles();
  $('prompt').focus();
};

$('workspaceButton').onclick = showWorkspace;
$('workspaceEdit').onclick = showWorkspace;
$('settingsButton').onclick = showModel;
$('sessionTitle').onclick = renameSession;
$('modelButton').onclick = showModel;
$('engineButton').onclick = showModel;
$('exportButton').onclick = exportSession;
$('stringsIndicator').onclick = showStringDetails;

// File Panel Controls
$('toggleFilePanel').onclick = () => toggleFilePanel();
$('closeFilePanel').onclick = () => toggleFilePanel(false);
$('copyFileCode').onclick = copyActiveFileCode;
$('downloadFileCode').onclick = downloadActiveFile;

$('closeDialog').onclick = () => $('dialog').close();
$('dialog').onclick = e => {
  if (e.target === $('dialog')) {
    const r = $('dialog').getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) $('dialog').close();
  }
};

document.querySelectorAll('[data-template]').forEach(button => button.onclick = () => {
  const templates = {
    build: 'Build a Python program that ',
    explore: 'Find the folder ',
    automate: 'Inspect my environment and list '
  };
  $('prompt').value = templates[button.dataset.template] || '';
  resizePrompt();
  $('prompt').focus();
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeModes();
    stopAll(); // Global Esc stops all active session workers
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    $('app').classList.remove('sidebar-collapsed');
    $('sessionSearch').focus();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
    e.preventDefault();
    if (!$('dialog').open) newSession();
  }
});

async function init() {
  if (window.innerWidth <= 580) $('app').classList.add('sidebar-collapsed');
  await checkHealth();
  await loadSessionsList();
  state.initialized = true;

  if (state.sessions.length > 0) {
    await selectSession(state.sessions[0].id);
  } else {
    await newSession();
  }
}

init();
setInterval(() => {
  checkHealth();
  loadSessionsList();
}, 15000);
