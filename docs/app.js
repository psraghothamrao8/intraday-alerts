// Dashboard Application Logic (plain vanilla JS)
let lastETag = null;
let cachedEnvelope = null;
let decryptedState = null;
let pollTimer = null;

const STORAGE_KEY_PASS = 'ia_pass';

function getPassphrase() {
  return localStorage.getItem(STORAGE_KEY_PASS) || '';
}

function setPassphrase(pass) {
  if (pass) {
    localStorage.setItem(STORAGE_KEY_PASS, pass);
  } else {
    localStorage.removeItem(STORAGE_KEY_PASS);
  }
}

async function fetchStateEnvelope() {
  const cfg = window.APP_CONFIG || {};
  const apiUrl = `https://api.github.com/repos/${cfg.owner}/${cfg.repo}/contents/${cfg.dataPath || 'state.enc.json'}?ref=${cfg.dataBranch || 'data'}`;
  const rawUrl = `https://raw.githubusercontent.com/${cfg.owner}/${cfg.repo}/${cfg.dataBranch || 'data'}/${cfg.dataPath || 'state.enc.json'}`;

  const headers = { 'Accept': 'application/vnd.github.raw+json' };
  if (lastETag) headers['If-None-Match'] = lastETag;

  try {
    const res = await fetch(apiUrl, { headers });
    if (res.status === 304) {
      return { envelope: cachedEnvelope, notModified: true };
    }
    if (res.ok) {
      lastETag = res.headers.get('ETag');
      const data = await res.json();
      cachedEnvelope = data;
      return { envelope: data, notModified: false };
    }
    if (res.status === 403 || res.status === 429) {
      // Fallback to raw.githubusercontent.com
      const rawRes = await fetch(rawUrl);
      if (rawRes.ok) {
        const rawData = await rawRes.json();
        cachedEnvelope = rawData;
        return { envelope: rawData, notModified: false, delayed: true };
      }
    }
  } catch (err) {
    console.warn('Primary fetch failed, trying fallback raw:', err);
    try {
      const rawRes = await fetch(rawUrl);
      if (rawRes.ok) {
        const rawData = await rawRes.json();
        cachedEnvelope = rawData;
        return { envelope: rawData, notModified: false, delayed: true };
      }
    } catch (e) {
      console.error('All state fetches failed:', e);
    }
  }
  return { envelope: cachedEnvelope, notModified: true };
}

function updateStatusBar(envelope, isDelayed = false) {
  const statusEl = document.getElementById('status-text');
  const timeEl = document.getElementById('status-time');
  if (!envelope) {
    statusEl.textContent = '🔴 Offline';
    return;
  }

  const engineStatus = envelope.engine_status || 'running';
  const heartbeatStr = envelope.heartbeat_at || envelope.updated_at;
  const heartbeatTime = heartbeatStr ? new Date(heartbeatStr) : null;
  const now = new Date();
  const diffMinutes = heartbeatTime ? (now - heartbeatTime) / 60000 : 999;

  let timeFormatted = heartbeatTime ? heartbeatTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  timeEl.textContent = heartbeatStr ? `Updated ${timeFormatted}` : '';

  if (engineStatus === 'stopped_eod') {
    statusEl.textContent = `⚪ Market closed (next: ${envelope.next_trading_day || 'tomorrow'})`;
  } else if (diffMinutes > 30) {
    statusEl.textContent = '🔴 Engine offline';
  } else if (diffMinutes > 10 || isDelayed) {
    statusEl.textContent = `🟡 Delayed (>10 min) · updated ${timeFormatted}`;
  } else {
    statusEl.textContent = `🟢 Live · updated ${timeFormatted}`;
  }
}

function renderDashboard(state) {
  if (!state) return;

  // Mode badge
  const modeBadge = document.getElementById('mode-badge');
  const mode = (state.mode || 'paper').toUpperCase();
  modeBadge.textContent = mode;
  modeBadge.className = `badge ${mode === 'LIVE' ? 'badge-live' : 'badge-paper'}`;

  // Open Trades
  const todayTrades = (state.today && state.today.trades) || [];
  const openTrades = todayTrades.filter(t => t.status === 'OPEN');
  document.getElementById('open-count').textContent = openTrades.length;

  const openGrid = document.getElementById('open-trades-grid');
  if (openTrades.length === 0) {
    openGrid.innerHTML = '<div class="empty-state">No open positions.</div>';
  } else {
    openGrid.innerHTML = openTrades.map(renderTradeCard).join('');
  }

  // Today Summary Table
  const todayPnl = state.today ? state.today.paper_pnl_pct : 0;
  const todayPnlEl = document.getElementById('today-pnl');
  todayPnlEl.textContent = (todayPnl >= 0 ? '+' : '') + todayPnl.toFixed(2) + '%';
  todayPnlEl.style.color = todayPnl >= 0 ? 'var(--green)' : 'var(--red)';

  const todayTbody = document.getElementById('today-tbody');
  if (todayTrades.length === 0) {
    todayTbody.innerHTML = '<tr><td colspan="7" class="empty-state">No trades today yet.</td></tr>';
  } else {
    todayTbody.innerHTML = todayTrades.map(renderTodayRow).join('');
  }

  // Scoreboard
  const scoreboard = state.scoreboard || [];
  const sbTbody = document.getElementById('scoreboard-tbody');
  sbTbody.innerHTML = scoreboard.map(s => `
    <tr>
      <td><strong>${s.strategy}</strong> <span style="font-size:0.75rem; color:var(--text-muted);">(${s.name})</span></td>
      <td>${s.n_30d}</td>
      <td>${Math.round((s.win_rate_30d || 0) * 100)}%</td>
      <td style="color:${s.avg_net_pct_30d >= 0 ? 'var(--green)' : 'var(--red)'}">${s.avg_net_pct_30d >= 0 ? '+' : ''}${s.avg_net_pct_30d}%</td>
      <td style="color:${s.sum_net_pct_30d >= 0 ? 'var(--green)' : 'var(--red)'}">${s.sum_net_pct_30d >= 0 ? '+' : ''}${s.sum_net_pct_30d}%</td>
      <td style="letter-spacing:2px;">${(s.last10 || '').replace(/W/g, '●').replace(/L/g, '○')}</td>
    </tr>
  `).join('');

  // Research S4
  if (state.research && state.research.S4) {
    document.getElementById('s4-sessions').textContent = state.research.S4.sessions || 0;
    document.getElementById('s4-promoted').textContent = state.research.S4.promoted ? 'Promoted (Live)' : 'Research Mode';
  }

  // Health
  if (state.health) {
    document.getElementById('health-feed').textContent = state.health.feed || 'ok';
    document.getElementById('health-polls').textContent = `${state.health.bse_last_poll || '-'} / ${state.health.nse_last_poll || '-'}`;
    document.getElementById('health-llm').textContent = state.health.llm_errors_today || 0;
    document.getElementById('health-version').textContent = state.engine_version || '0.3.0';
  }

  highlightDeepLink();
}

function renderTradeCard(t) {
  const sideClass = t.side === 'LONG' ? 'side-long' : 'side-short';
  const thesisLvl = (t.thesis && t.thesis.level) ? `₹${t.thesis.level.toFixed(2)}` : '-';
  const safetyLvl = t.safety_stop ? `₹${t.safety_stop.toFixed(2)}` : '-';
  const entryLvl = t.paper_entry ? `₹${t.paper_entry.toFixed(2)}` : (t.ref_price ? `₹${t.ref_price.toFixed(2)}` : '-');
  const sourceLink = t.source_url ? `<a href="${t.source_url}" target="_blank" rel="noopener">Filing PDF</a>` : '';

  return `
    <div class="trade-card" id="card-${t.id}">
      <div class="card-header">
        <span class="symbol-side ${sideClass}">${t.side} ${t.symbol}</span>
        <span class="score-tag">${t.strategy} · ${t.strength}/10</span>
      </div>
      <div class="card-body">
        <div class="card-field"><span>Entry Price</span><strong>${entryLvl}</strong></div>
        <div class="card-field"><span>Thesis Stop</span><span>${thesisLvl}</span></div>
        <div class="card-field"><span>Safety SL</span><span>${safetyLvl}</span></div>
        <div class="card-field"><span>Exit By</span><span>${t.exit_by || '-'}</span></div>
        <div class="card-field"><span>Qty / Risk</span><span>${t.qty || '-'} (₹${t.risk_inr || '-'})</span></div>
      </div>
      <div class="card-footer">
        <span style="font-size:0.75rem; color:var(--text-muted);">${t.why || ''}</span>
        ${sourceLink}
      </div>
    </div>
  `;
}

function renderTodayRow(t) {
  const pnl = t.paper_net_pct;
  const pnlStr = pnl !== null && pnl !== undefined ? (pnl >= 0 ? '+' : '') + pnl.toFixed(1) + '%' : '-';
  const pnlColor = pnl > 0 ? 'var(--green)' : (pnl < 0 ? 'var(--red)' : 'inherit');
  const entryStr = t.paper_entry ? `₹${t.paper_entry.toFixed(2)}` : (t.ref_price ? `₹${t.ref_price.toFixed(2)}` : '-');
  const exitStr = t.exit_price ? `₹${t.exit_price.toFixed(2)}` : '-';

  return `
    <tr id="row-${t.id}">
      <td><strong>${t.symbol}</strong></td>
      <td class="${t.side === 'LONG' ? 'side-long' : 'side-short'}">${t.side}</td>
      <td>${t.strategy}</td>
      <td><span class="badge" style="background:var(--bg); border:1px solid var(--border);">${t.status}</span></td>
      <td>${entryStr}</td>
      <td>${exitStr}</td>
      <td style="font-weight:600; color:${pnlColor}">${pnlStr}</td>
    </tr>
  `;
}

function highlightDeepLink() {
  const hash = window.location.hash;
  if (!hash.startsWith('#t=')) return;
  const tradeId = hash.substring(3);
  const card = document.getElementById(`card-${tradeId}`);
  if (card) {
    document.querySelectorAll('.trade-card.highlight').forEach(el => el.classList.remove('highlight'));
    card.classList.add('highlight');
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

async function unlockAndRefresh() {
  const pass = getPassphrase();
  if (!pass) {
    document.getElementById('lock-screen').style.display = 'block';
    document.getElementById('dashboard-view').style.display = 'none';
    return;
  }

  document.getElementById('lock-screen').style.display = 'none';
  document.getElementById('dashboard-view').style.display = 'block';
  document.getElementById('settings-passphrase').value = pass;

  const { envelope, delayed } = await fetchStateEnvelope();
  if (!envelope) {
    updateStatusBar(null);
    return;
  }
  updateStatusBar(envelope, delayed);

  try {
    decryptedState = await decryptState(envelope, pass);
    document.getElementById('unlock-error').style.display = 'none';
    renderDashboard(decryptedState);
  } catch (err) {
    console.error('Decryption failed:', err);
    document.getElementById('lock-screen').style.display = 'block';
    document.getElementById('dashboard-view').style.display = 'none';
    const errEl = document.getElementById('unlock-error');
    errEl.textContent = 'Decryption failed: incorrect passphrase.';
    errEl.style.display = 'block';
  }
}

// Push notification registration
async function enablePush() {
  const subOutput = document.getElementById('sub-output');
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    alert('Web Push is not supported on this browser.');
    return;
  }

  try {
    const reg = await navigator.serviceWorker.register('sw.js', { scope: './' });
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') {
      alert('Notification permissions were denied.');
      return;
    }
    const cfg = window.APP_CONFIG || {};
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: b64urlToUint8(cfg.vapidPublicKey),
    });
    subOutput.value = JSON.stringify(sub, null, 2);
    alert('Notifications enabled! Subscription JSON generated in Settings box. Copy it and paste into: python -m engine add-device');
  } catch (err) {
    console.error('Push registration error:', err);
    alert('Failed to register push: ' + err.message);
  }
}

// Setup event listeners
window.addEventListener('DOMContentLoaded', () => {
  // Service worker registration
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js', { scope: './' }).catch(console.error);
  }

  document.getElementById('unlock-btn').addEventListener('click', () => {
    const pass = document.getElementById('passphrase-input').value.trim();
    if (pass) {
      setPassphrase(pass);
      unlockAndRefresh();
    }
  });

  document.getElementById('save-passphrase-btn').addEventListener('click', () => {
    const pass = document.getElementById('settings-passphrase').value.trim();
    setPassphrase(pass);
    alert('Passphrase updated in localStorage.');
    unlockAndRefresh();
  });

  document.getElementById('enable-push-btn').addEventListener('click', enablePush);

  document.getElementById('copy-sub-btn').addEventListener('click', () => {
    const txt = document.getElementById('sub-output').value;
    if (txt) {
      navigator.clipboard.writeText(txt).then(() => alert('Copied subscription JSON to clipboard!'));
    }
  });

  document.getElementById('test-push-btn').addEventListener('click', () => {
    if (Notification.permission === 'granted') {
      new Notification('🟢 Test Alert', {
        body: 'Local notification test successful.',
        icon: 'icons/icon-192.png',
      });
    } else {
      alert('Please enable notifications first.');
    }
  });

  window.addEventListener('hashchange', highlightDeepLink);

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      unlockAndRefresh();
    }
  });

  // Auto poll every 60s
  const pollSec = (window.APP_CONFIG && window.APP_CONFIG.pollSec) || 60;
  pollTimer = setInterval(unlockAndRefresh, pollSec * 1000);

  unlockAndRefresh();
});
