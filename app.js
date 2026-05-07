const state = {
  jobId: null,
  accounts: [],
  proxies: [],
  emails: [],
  ws: null,
  reconnectTimer: null,
};

const proxyRegex = /^(\d{1,3}(?:\.\d{1,3}){3}:\d{2,5})(?::[^:\s]+:[^:\s]+)?$/;

const elements = {
  threads: document.getElementById('threads'),
  threadsValue: document.getElementById('threadsValue'),
  progressBar: document.getElementById('progressBar'),
  progressLabel: document.getElementById('progressLabel'),
  successCount: document.getElementById('successCount'),
  smsCount: document.getElementById('smsCount'),
  errorCount: document.getElementById('errorCount'),
  liveLog: document.getElementById('liveLog'),
  resultsBody: document.getElementById('resultsBody'),
  accountsCount: document.getElementById('accountsCount'),
  proxiesCount: document.getElementById('proxiesCount'),
  emailsCount: document.getElementById('emailsCount'),
  startBtn: document.getElementById('startBtn'),
  pauseBtn: document.getElementById('pauseBtn'),
  stopBtn: document.getElementById('stopBtn')
};

function setProgress(pct) {
  const safePct = Math.max(0, Math.min(100, pct));
  elements.progressBar.style.width = `${safePct}%`;
  elements.progressLabel.textContent = `${safePct}%`;
}

function addLog(line) {
  const div = document.createElement('div');
  div.textContent = line;
  elements.liveLog.appendChild(div);
  elements.liveLog.scrollTop = elements.liveLog.scrollHeight;
}

function addResultRow(row) {
  const tr = document.createElement('tr');
  tr.className = 'border-b border-slate-900';
  tr.innerHTML = `
    <td class="py-2 pr-4">${row.account ?? '-'}</td>
    <td class="py-2 pr-4">${row.stats ?? '-'}</td>
    <td class="py-2 pr-4">${row.screenshot_url ? `<a class="text-cyan-400" href="${row.screenshot_url}" target="_blank">View</a>` : '-'}</td>
    <td class="py-2 pr-4 break-all">${row.result ?? '-'}</td>
    <td class="py-2"><button class="copy-btn text-xs rounded bg-slate-800 px-2 py-1">Copy</button></td>
  `;
  tr.querySelector('.copy-btn').addEventListener('click', async () => {
    await navigator.clipboard.writeText(row.result ?? '');
  });
  elements.resultsBody.prepend(tr);
}

function parseFileLines(text) {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
}

async function handleFile(inputId, kind) {
  const input = document.getElementById(inputId);
  const file = input.files?.[0];
  if (!file) return;
  const text = await file.text();
  const lines = parseFileLines(text);

  if (kind === 'accounts') {
    state.accounts = lines;
    elements.accountsCount.textContent = lines.length;
  } else if (kind === 'proxies') {
    const valid = lines.filter((l) => proxyRegex.test(l));
    state.proxies = valid;
    elements.proxiesCount.textContent = `${valid.length}/${lines.length}`;
  } else if (kind === 'emails') {
    state.emails = lines;
    elements.emailsCount.textContent = lines.length;
  }
}

function bindDropzones() {
  document.querySelectorAll('.drop-zone').forEach((zone) => {
    const inputId = zone.getAttribute('data-input');
    const input = document.getElementById(inputId);
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('border-cyan-500');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('border-cyan-500'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('border-cyan-500');
      if (e.dataTransfer.files.length > 0) {
        input.files = e.dataTransfer.files;
        input.dispatchEvent(new Event('change'));
      }
    });

    input.addEventListener('change', () => {
      if (inputId === 'accountsInput') handleFile(inputId, 'accounts');
      if (inputId === 'proxiesInput') handleFile(inputId, 'proxies');
      if (inputId === 'emailsInput') handleFile(inputId, 'emails');
    });
  });
}

function connectWs(jobId) {
  if (state.ws) state.ws.close();
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${protocol}://${location.host}/ws/jobs/${jobId}`);
  state.ws = ws;

  ws.onopen = () => addLog(`[UI] WS connected for job ${jobId}`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'progress_update') {
      const p = msg.payload;
      setProgress(p.progress_pct ?? 0);
      elements.successCount.textContent = p.success ?? 0;
      elements.smsCount.textContent = p.sms_2fa ?? 0;
      elements.errorCount.textContent = p.error ?? 0;
    }

    if (msg.type === 'log_line') {
      addLog(msg.payload?.line ?? '[empty log]');
    }

    if (msg.type === 'result_row') {
      addResultRow(msg.payload ?? {});
    }

    if (msg.type === 'job_finished') {
      addLog('[UI] Job finished.');
    }
  };

  ws.onclose = () => {
    addLog('[UI] WS disconnected, reconnecting in 2s...');
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = setTimeout(() => connectWs(jobId), 2000);
  };
}

async function startJob() {
  const payload = {
    accounts: state.accounts,
    proxies: state.proxies,
    target_emails: state.emails,
    config: {
      threads: Number(elements.threads.value),
      timeout: Number(document.getElementById('timeout').value),
      headless: document.getElementById('headless').checked,
      mx_lookup: document.getElementById('mxLookup').checked,
      bot_token: document.getElementById('botToken').value.trim(),
      chat_id: document.getElementById('chatId').value.trim()
    }
  };

  const res = await fetch('/jobs/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    addLog(`[UI] Failed to start job: HTTP ${res.status}`);
    return;
  }

  const data = await res.json();
  state.jobId = data.job_id;
  elements.resultsBody.innerHTML = '';
  elements.liveLog.innerHTML = '';
  setProgress(0);
  connectWs(state.jobId);
}

async function sendJobCommand(action) {
  if (!state.jobId) return addLog('[UI] No active job id');
  const res = await fetch(`/jobs/${state.jobId}/${action}`, { method: 'POST' });
  addLog(`[UI] ${action.toUpperCase()} -> HTTP ${res.status}`);
}

function init() {
  bindDropzones();
  elements.threads.addEventListener('input', () => {
    elements.threadsValue.textContent = elements.threads.value;
  });
  elements.startBtn.addEventListener('click', startJob);
  elements.pauseBtn.addEventListener('click', () => sendJobCommand('pause'));
  elements.stopBtn.addEventListener('click', () => sendJobCommand('stop'));
  addLog('[UI] Ready. Upload files and click Initialize Threads.');
}

init();
