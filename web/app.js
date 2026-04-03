/* =========================================================
   RoboCup Local Gamemaster — app.js
   ========================================================= */

'use strict';

// ---------------------------------------------------------------------------
// Constants (filled from /api/config)
// ---------------------------------------------------------------------------
let C = null;          // config object
let POLL_ID = null;    // setInterval handle

// ---------------------------------------------------------------------------
// Tab system
// ---------------------------------------------------------------------------
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = document.getElementById('tab-' + btn.dataset.tab);
    if (panel) panel.classList.add('active');
    if (btn.dataset.tab === 'leaderboard') refreshLeaderboard();
  });
});

// ---------------------------------------------------------------------------
// Canvas
// ---------------------------------------------------------------------------
const canvas = document.getElementById('field');
const ctx    = canvas.getContext('2d');
// Native resolution matches simulation world
canvas.width  = 1200;
canvas.height = 760;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
  try {
    C = await fetch('/api/config').then(r => r.json());
  } catch {
    C = {
      window_width: 1200, window_height: 760,
      field_margin: 60,
      field_width: 1080, field_height: 640,
      goal_height: 220, goal_depth: 34,
      goal_top: 270, goal_bottom: 490,
      field_center_x: 600, field_center_y: 380,
    };
  }
  drawIdleField();
  await refreshModels();

  // Check if a match is already running (e.g. after page reload)
  const data = await fetch('/api/match/state').then(r => r.json());
  if (data.running) {
    setRunningUI(true);
    startPolling();
  } else if (data.state) {
    renderState(data.state);
    updateScoreBar(data.state, data.team1, data.team2);
  }
}

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------
async function refreshModels() {
  let models = [];
  try {
    models = await fetch('/api/models').then(r => r.json());
  } catch { /* server offline? */ }

  ['sel-t1', 'sel-t2'].forEach(id => {
    const sel = document.getElementById(id);
    const prev = sel.value;
    sel.innerHTML = models.length
      ? models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('')
      : '<option value="">— нет моделей —</option>';
    if (models.includes(prev)) sel.value = prev;
  });

  renderModelChips(models);
}

function renderModelChips(models) {
  const list = document.getElementById('model-list');
  if (models.length === 0) {
    list.innerHTML = '<span style="color:var(--muted);font-size:12px">Нет загруженных моделей. Нажмите «Загрузить модель».</span>';
    return;
  }
  list.innerHTML = models.map(m => `
    <div class="model-chip">
      <span>${esc(m)}</span>
      <button class="chip-del" title="Удалить" onclick="deleteModel('${esc(m).replace(/'/g, "\\'")}')">×</button>
    </div>
  `).join('');
}

async function deleteModel(name) {
  if (!confirm(`Удалить модель «${name}»?`)) return;
  const r = await fetch(`/api/models/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (r.ok) await refreshModels();
  else showError(`Не удалось удалить: ${(await r.json()).detail}`);
}

// Upload
document.getElementById('btn-upload').addEventListener('click', () => {
  document.getElementById('upload-input').click();
});
document.getElementById('btn-refresh').addEventListener('click', () => refreshModels());

document.getElementById('upload-input').addEventListener('change', async e => {
  const file = e.target.files[0];
  if (!file) return;
  const status = document.getElementById('upload-status');
  status.textContent = 'Загрузка…';
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/api/models/upload', { method: 'POST', body: fd });
    if (r.ok) {
      status.textContent = `✓ ${file.name} загружен`;
      await refreshModels();
    } else {
      const err = await r.json();
      status.style.color = 'var(--danger)';
      status.textContent = `✗ ${err.detail}`;
    }
  } catch {
    status.style.color = 'var(--danger)';
    status.textContent = '✗ Сервер недоступен';
  }
  e.target.value = '';
  setTimeout(() => { status.textContent = ''; status.style.color = ''; }, 4000);
});

// ---------------------------------------------------------------------------
// Duration range display
// ---------------------------------------------------------------------------
const periodRange = document.getElementById('period-range');
const periodDisplay = document.getElementById('period-display');
periodRange.addEventListener('input', () => {
  const v = parseInt(periodRange.value);
  periodDisplay.textContent = v >= 60
    ? `${Math.floor(v/60)}:${String(v%60).padStart(2,'0')} мин`
    : `${v} с`;
});

// ---------------------------------------------------------------------------
// Match controls
// ---------------------------------------------------------------------------
document.getElementById('btn-start').addEventListener('click', startMatch);
document.getElementById('btn-stop').addEventListener('click', stopMatch);
document.getElementById('ov-close').addEventListener('click', () => {
  document.getElementById('match-overlay').classList.add('hidden');
});

async function startMatch() {
  hideError();
  const team1 = document.getElementById('sel-t1').value;
  const team2 = document.getElementById('sel-t2').value;
  if (!team1 || !team2) { showError('Выберите модели для обеих команд.'); return; }

  const period = parseFloat(periodRange.value);
  const speed  = parseFloat(document.getElementById('speed-select').value);

  const r = await fetch('/api/match/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ team1, team2, period, speed }),
  });

  if (!r.ok) {
    const err = await r.json();
    showError(`Ошибка старта: ${err.detail}`);
    return;
  }

  document.getElementById('match-overlay').classList.add('hidden');
  setRunningUI(true);
  startPolling();
}

async function stopMatch() {
  await fetch('/api/match/stop', { method: 'POST' });
  setRunningUI(false);
}

function setRunningUI(running) {
  document.getElementById('btn-start').disabled = running;
  document.getElementById('btn-stop').disabled  = !running;
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------
function startPolling() {
  if (POLL_ID) clearInterval(POLL_ID);
  POLL_ID = setInterval(poll, 100);
}

async function poll() {
  let data;
  try {
    data = await fetch('/api/match/state').then(r => r.json());
  } catch { return; }

  if (data.state) {
    renderState(data.state);
    updateScoreBar(data.state, data.team1, data.team2);
  }

  if (!data.running) {
    clearInterval(POLL_ID);
    POLL_ID = null;
    setRunningUI(false);

    if (data.error) {
      showError(`Ошибка матча: ${data.error}`);
    } else if (data.state && data.state.truncated) {
      showResult(data.state, data.team1, data.team2);
      refreshLeaderboard();
    }
  }
}

// ---------------------------------------------------------------------------
// Canvas renderer
// ---------------------------------------------------------------------------
function drawIdleField() {
  drawField();
  // "Waiting" text
  ctx.save();
  ctx.fillStyle = 'rgba(22,31,25,0.6)';
  ctx.fillRect(0, 0, 1200, 760);
  ctx.fillStyle = 'rgba(238,245,239,0.25)';
  ctx.font = 'bold 28px Segoe UI, system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('Выберите модели и нажмите «Старт»', 600, 380);
  ctx.restore();
}

function renderState(st) {
  ctx.clearRect(0, 0, 1200, 760);
  drawField();

  // Robots
  (st.team1_robots || []).forEach(r => drawRobot(r, '#f2b134', '#262626'));
  (st.team2_robots || []).forEach(r => drawRobot(r, '#449ce8', '#12306e'));

  // Ball
  if (st.ball) drawBall(st.ball);

  // Goal flash
  if (st.match_phase === 'goal_pause') {
    ctx.fillStyle = 'rgba(255,220,60,0.07)';
    ctx.fillRect(0, 0, 1200, 760);
  }
}

function drawField() {
  const m  = C ? C.field_margin : 60;
  const fw = C ? C.field_width  : 1080;
  const fh = C ? C.field_height : 640;
  const gh = C ? C.goal_height  : 220;
  const gd = C ? C.goal_depth   : 34;
  const cy = C ? C.field_center_y : 380;
  const gTop = cy - gh / 2;

  // Background
  ctx.fillStyle = '#161f19';
  ctx.fillRect(0, 0, 1200, 760);

  // Field fill
  roundRect(m, m, fw, fh, 18);
  ctx.fillStyle = '#348a4e';
  ctx.fill();

  // Field border
  roundRect(m, m, fw, fh, 18);
  ctx.strokeStyle = '#eef5ef';
  ctx.lineWidth = 4;
  ctx.stroke();

  // Center line
  ctx.beginPath();
  ctx.moveTo(m + fw / 2, m);
  ctx.lineTo(m + fw / 2, m + fh);
  ctx.strokeStyle = '#eef5ef';
  ctx.lineWidth = 3;
  ctx.stroke();

  // Center circle
  ctx.beginPath();
  ctx.arc(m + fw / 2, m + fh / 2, 90, 0, Math.PI * 2);
  ctx.strokeStyle = '#eef5ef';
  ctx.lineWidth = 3;
  ctx.stroke();

  // Goal boxes
  ctx.strokeStyle = '#eef5ef';
  ctx.lineWidth = 3;
  ctx.strokeRect(m, m + fh / 2 - 110, 120, 220);
  ctx.strokeRect(m + fw - 120, m + fh / 2 - 110, 120, 220);

  // Goals (left and right)
  ctx.strokeStyle = '#e1e9e4';
  ctx.lineWidth = 3;
  ctx.strokeRect(m - gd, gTop, gd, gh);
  ctx.strokeRect(m + fw, gTop, gd, gh);
}

function drawRobot(robot, bodyColor, headColor) {
  const x = robot.x, y = robot.y, r = robot.radius || 28;

  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = bodyColor;
  ctx.fill();
  ctx.strokeStyle = '#eef5ef';
  ctx.lineWidth = 2;
  ctx.stroke();

  // Direction head
  const rad = (robot.angle || 0) * Math.PI / 180;
  const hx = x + Math.cos(rad) * r * 0.65;
  const hy = y + Math.sin(rad) * r * 0.65;
  ctx.beginPath();
  ctx.arc(hx, hy, 8, 0, Math.PI * 2);
  ctx.fillStyle = headColor;
  ctx.fill();
}

function drawBall(ball) {
  ctx.beginPath();
  ctx.arc(ball.x, ball.y, ball.radius || 14, 0, Math.PI * 2);
  ctx.fillStyle = 'rgb(220,50,50)';
  ctx.fill();
  ctx.strokeStyle = '#464646';
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

// ---------------------------------------------------------------------------
// Score bar
// ---------------------------------------------------------------------------
function updateScoreBar(st, team1, team2) {
  document.getElementById('sc-t1-name').textContent  = team1 || '—';
  document.getElementById('sc-t2-name').textContent  = team2 || '—';
  document.getElementById('sc-goals-t1').textContent = st.team1_score ?? 0;
  document.getElementById('sc-goals-t2').textContent = st.team2_score ?? 0;

  const elapsed = Math.floor(st.elapsed_time || 0);
  const total   = Math.floor(st.period_seconds || 60);
  const fmt = s => `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;
  document.getElementById('sc-time').textContent = `${fmt(elapsed)} / ${fmt(total)}`;

  const phase = st.match_phase || '';
  document.getElementById('sc-phase').textContent =
    phase === 'full_time' ? 'ФИНАЛ' :
    phase === 'goal_pause' ? '⚽ ГОЛ!' :
    phase === 'kickoff'   ? 'НАЧАЛО' : '';
}

// ---------------------------------------------------------------------------
// Result overlay
// ---------------------------------------------------------------------------
function showResult(st, team1, team2) {
  const s1 = st.team1_score, s2 = st.team2_score;
  let winner;
  if (s1 > s2) winner = `🏆 Победитель: ${team1}`;
  else if (s2 > s1) winner = `🏆 Победитель: ${team2}`;
  else winner = '🤝 Ничья!';

  document.getElementById('ov-score').textContent  = `${s1} : ${s2}`;
  document.getElementById('ov-winner').textContent = winner;

  // Color winner name
  if (s1 > s2) document.getElementById('ov-winner').style.color = '#f2b134';
  else if (s2 > s1) document.getElementById('ov-winner').style.color = '#449ce8';
  else document.getElementById('ov-winner').style.color = 'var(--muted)';

  document.getElementById('match-overlay').classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// Leaderboard
// ---------------------------------------------------------------------------
async function refreshLeaderboard() {
  let stats = [], history = [];
  try {
    [stats, history] = await Promise.all([
      fetch('/api/leaderboard/stats').then(r => r.json()),
      fetch('/api/leaderboard').then(r => r.json()),
    ]);
  } catch { return; }

  renderStatsTable(stats);
  renderHistoryTable(history);
}

function renderStatsTable(stats) {
  const tbody = document.getElementById('stats-body');
  if (!stats.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-msg">Нет данных — сыграйте хотя бы один матч</td></tr>';
    return;
  }
  tbody.innerHTML = stats.map((s, i) => `
    <tr class="${i === 0 ? 'rank-1' : i === 1 ? 'rank-2' : i === 2 ? 'rank-3' : ''}">
      <td>${i + 1}</td>
      <td><strong>${esc(s.name)}</strong></td>
      <td>${s.m}</td>
      <td class="good">${s.w}</td>
      <td>${s.d}</td>
      <td class="bad">${s.l}</td>
      <td>${s.gf}:${s.ga}</td>
      <td><strong>${s.pts}</strong></td>
    </tr>
  `).join('');
}

function renderHistoryTable(history) {
  const tbody = document.getElementById('history-body');
  if (!history.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">История пуста</td></tr>';
    return;
  }
  tbody.innerHTML = history.slice(0, 100).map(r => {
    const s1 = r.score1, s2 = r.score2;
    const result = s1 > s2
      ? `<span class="good">${esc(r.team1)} победили</span>`
      : s2 > s1
      ? `<span class="good">${esc(r.team2)} победили</span>`
      : '<span style="color:var(--muted)">Ничья</span>';
    const dur = r.duration ? `${Math.round(r.duration)}с` : '—';
    const dt  = r.created_at ? r.created_at.replace('T', ' ').slice(0, 16) : '';
    return `
      <tr>
        <td>${esc(r.team1)}</td>
        <td class="score-cell">${s1} : ${s2}</td>
        <td>${esc(r.team2)}</td>
        <td>${result}</td>
        <td>${dur}</td>
        <td style="color:var(--muted);font-size:11px">${dt}</td>
      </tr>`;
  }).join('');
}

document.getElementById('btn-reset-lb').addEventListener('click', async () => {
  if (!confirm('Сбросить всю историю матчей? Это действие нельзя отменить.')) return;
  await fetch('/api/leaderboard', { method: 'DELETE' });
  await refreshLeaderboard();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function showError(msg) {
  const bar = document.getElementById('error-bar');
  bar.textContent = msg;
  bar.classList.remove('hidden');
}
function hideError() {
  document.getElementById('error-bar').classList.add('hidden');
}
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
init();
