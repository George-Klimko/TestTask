const state = {
  jobId: null,
  ws: null,
  reconnectTimer: null,
};

const elements = {
  threads: document.getElementById('threads'),
  threadsValue: document.getElementById('threadsValue'),
  progressBar: document.getElementById('progressBar'),
  progressLabel: document.getElementById('progressLabel'),
  successCount: document.getElementById('successCount'),
  smsCount: document.getElementById('smsCount'),
  errorCount: document.getElementById('errorCount'),
  liveLog: document.getElementById('liveLog'),
  validResultsBody: document.getElementById('validResultsBody'),
  errorResultsBody: document.getElementById('errorResultsBody'),
  accountsCount: document.getElementById('accountsCount'),
  proxiesCount: document.getElementById('proxiesCount'),
  emailsCount: document.getElementById('emailsCount'),
  startBtn: document.getElementById('startBtn'),
  pauseBtn: document.getElementById('pauseBtn'),
  stopBtn: document.getElementById('stopBtn'),
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
  if (row.status === 'ok') {
    // ✅ SUCCESS → validResultsBody
    const combo = `${row.account ?? ''}:${row.email_password ?? ''}:${row.new_password ?? ''}`;

    const tr = document.createElement('tr');
    tr.className = 'border-b border-slate-900 hover:bg-slate-900/30 transition-colors';
    tr.innerHTML = `
      <td class="py-2 pr-2 font-mono text-xs text-emerald-400 break-all">${combo}</td>
      <td class="py-2 text-right">
        <button class="copy-btn text-[11px] font-medium rounded bg-emerald-950 border border-emerald-800 text-emerald-300 px-2 py-0.5 hover:bg-emerald-900 transition-colors">
          Copy
        </button>
      </td>
    `;
    tr.querySelector('.copy-btn').addEventListener('click', async () => {
      await navigator.clipboard.writeText(combo);
    });
    elements.validResultsBody.prepend(tr);

  } else {
    // ❌ ERROR → errorResultsBody
    const tr = document.createElement('tr');
    tr.className = 'border-b border-slate-900 hover:bg-slate-900/30 transition-colors text-xs';
    tr.innerHTML = `
      <td class="py-2 pr-4 space-y-0.5 max-w-[180px]">
        <div class="font-medium text-slate-200 break-all">${row.account ?? '-'}</div>
        <div class="text-[10px] text-slate-500 break-all">${row.proxy ?? 'No proxy'}</div>
      </td>
      <td class="py-2 space-y-1">
        <div class="flex flex-wrap items-center gap-1">
          <span class="px-1 py-0.5 text-[9px] font-bold rounded bg-rose-950 border border-rose-900 text-rose-400">
            ${row.error ?? 'FAIL'}
          </span>
          <span class="text-[10px] text-slate-400">${row.stage ?? 'unknown'}</span>
        </div>
        <div class="text-slate-400 text-[11px] break-words leading-tight">${row.message ?? '-'}</div>
      </td>
    `;
    elements.errorResultsBody.prepend(tr);
  }
}

async function handleFile(inputId, kind) {
  const input = document.getElementById(inputId);
  const file = input.files?.[0];
  if (!file) return;

  const form = new FormData();
  form.append('file', file);

  const res = await fetch(`/upload/${kind}`, { method: 'POST', body: form });

  if (!res.ok) {
    addLog(`[UI] Upload ${kind} failed: HTTP ${res.status}`);
    return;
  }

  const data = await res.json();

  if (kind === 'accounts') elements.accountsCount.textContent = `${data.valid}/${data.total}`;
  if (kind === 'proxies') elements.proxiesCount.textContent = `${data.valid}/${data.total}`;
  if (kind === 'emails') elements.emailsCount.textContent = `${data.valid}/${data.total}`;

  addLog(`[UI] Uploaded ${kind}: valid=${data.valid}, invalid=${data.invalid}`);
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

  let finished = false;

  ws.onopen = () => addLog(`[UI] WS connected for job ${jobId}`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === 'ping') return;

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
      finished = true;
      addLog('[UI] Job finished.');
    }
  };

  ws.onerror = (e) => {
    console.error('WS ERROR:', e);
    addLog('[UI] WS error');
  };

  ws.onclose = (e) => {
    addLog(`[UI] WS disconnected code=${e.code}`);
    clearTimeout(state.reconnectTimer);
    if (!finished) {
      state.reconnectTimer = setTimeout(() => connectWs(jobId), 2000);
    }
  };
}

async function startJob() {
  const payload = {
    config: {
      threads: Number(elements.threads.value),
      timeout: Number(document.getElementById('timeout').value),
      headless: document.getElementById('headless').checked,
      mx_lookup: document.getElementById('mxLookup').checked,
      bot_token: document.getElementById('botToken').value.trim(),
      chat_id: document.getElementById('chatId').value.trim(),
    },
  };

  addLog('[UI] Starting job...');

  const res = await fetch('/jobs/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    addLog(`[UI] Failed to start job: HTTP ${res.status}`);
    return;
  }

  const data = await res.json();
  state.jobId = data.job_id;

  elements.validResultsBody.innerHTML = '';
  elements.errorResultsBody.innerHTML = '';
  elements.liveLog.innerHTML = '';
  setProgress(0);

  connectWs(state.jobId);
}

async function sendJobCommand(action) {
  if (!state.jobId) {
    addLog('[UI] No active job id');
    return;
  }
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