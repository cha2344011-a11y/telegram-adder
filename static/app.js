// ── Socket.IO ──────────────────────────────────────────────────────────────
const socket = io();
const accounts = [];

// ── Connection ─────────────────────────────────────────────────────────────
socket.on("connect", () => {
  document.getElementById("conn-dot").className   = "dot green";
  document.getElementById("conn-label").textContent = "Connected";
  addLog("✅ Connected to server.", "success");
  socket.emit("get_accounts_status");
});
socket.on("disconnect", () => {
  document.getElementById("conn-dot").className   = "dot red";
  document.getElementById("conn-label").textContent = "Disconnected";
});

// ── Tab Switching ───────────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "accounts") loadAccountsLive();
  });
});

// ── Log helper ─────────────────────────────────────────────────────────────
function addLog(msg, type = "info") {
  const box   = document.getElementById("log-box");
  const entry = document.createElement("p");
  entry.className = `log-entry ${type}`;
  const now   = new Date().toLocaleTimeString();
  entry.textContent = `[${now}] ${msg}`;
  box.appendChild(entry);
  box.scrollTop = box.scrollHeight;
}
document.getElementById("clear-log-btn").addEventListener("click", () => {
  document.getElementById("log-box").innerHTML = "";
});
socket.on("log", d => addLog(d.msg, d.type || "info"));

// ── OTP ───────────────────────────────────────────────────────────────────
socket.on("otp_required", data => {
  const box = document.getElementById("otp-box");
  document.getElementById("otp-phone").textContent = data.phone;
  box.classList.remove("hidden");
  addLog(`📲 OTP required for ${data.phone}`, "warn");
});
document.getElementById("otp-submit-btn").addEventListener("click", () => {
  const phone = document.getElementById("s-phone").value.trim()
              || document.getElementById("otp-phone").textContent;
  const code  = document.getElementById("otp-code").value.trim();
  if (!code) { addLog("OTP enter karo!", "error"); return; }
  fetch("/api/otp", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, code })
  }).then(() => {
    document.getElementById("otp-box").classList.add("hidden");
    addLog("✅ OTP submitted.", "success");
  });
});

// ════════════════════════════════════════════════════════════════════════════
// ─── SCRAPE ──────────────────────────────────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════
document.getElementById("start-scrape-btn").addEventListener("click", () => {
  const api_id   = document.getElementById("s-api-id").value.trim();
  const api_hash = document.getElementById("s-api-hash").value.trim();
  const phone    = document.getElementById("s-phone").value.trim();
  const source   = document.getElementById("s-source").value.trim();
  if (!api_id || !api_hash || !phone || !source) {
    addLog("❌ All scrape fields fill karo.", "error"); return;
  }
  addLog(`🔍 Scraping from: ${source}`, "info");
  socket.emit("start_scrape", { api_id, api_hash, phone, source_group: source });
});
socket.on("scrape_progress", d => {
  document.getElementById("total-scraped").textContent = d.scraped;
});
socket.on("scrape_done", d => {
  document.getElementById("total-scraped").textContent = d.total;
  document.getElementById("download-scraped").classList.remove("hidden");
  addLog(`✅ Scraping complete! ${d.total} members saved.`, "success");
});

// ════════════════════════════════════════════════════════════════════════════
// ─── AUTO SCHEDULER ──────────────────────────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════
document.getElementById("start-auto-btn").addEventListener("click", () => {
  const target    = document.getElementById("auto-target").value.trim();
  const delay_min = document.getElementById("setting-delay-min").value;
  const delay_max = document.getElementById("setting-delay-max").value;

  if (!target) { addLog("❌ Target group enter karo!", "error"); return; }

  // ── Turant progress load karo before scheduler fires ──
  fetch("/api/progress").then(r => r.json()).then(data => {
    document.getElementById("total-invited").textContent   = data.invited   || 0;
    document.getElementById("total-today").textContent     = data.daily?.total_today || 0;
    document.getElementById("total-remaining").textContent = data.remaining || "—";
    if (data.total > 0) {
      const pct = Math.min(100, Math.round((data.invited / data.total) * 100));
      document.getElementById("progress-bar").style.width = `${pct}%`;
      document.getElementById("progress-pct").textContent  = `${pct}%`;
    }
    if (data.accounts) renderAccountsLive(data.accounts, data.daily);
    addLog(`📊 Stats loaded: ${data.invited || 0} invited, ${data.remaining || 0} remaining.`, "info");
  }).catch(() => {});

  socket.emit("start_auto_scheduler", {
    target_group: target,
    delay_min: parseFloat(delay_min),
    delay_max: parseFloat(delay_max)
  });
  addLog(`🤖 Auto-scheduler starting for: ${target}`, "info");
});

document.getElementById("stop-auto-btn").addEventListener("click", () => {
  socket.emit("stop_auto_scheduler");
});

// Scheduler status updates
socket.on("scheduler_status", data => {
  const bar   = document.getElementById("scheduler-status-bar");
  const dot   = document.getElementById("scheduler-dot");
  const label = document.getElementById("scheduler-label");

  if (data.running) {
    bar.className  = "scheduler-bar running";
    dot.className  = "dot green";
    label.textContent = `🤖 Auto-Scheduler: ACTIVE — ${data.accounts || ''} accounts, ${data.total_daily || ''} invites/day`;
  } else {
    bar.className  = "scheduler-bar stopped";
    dot.className  = "dot red";
    label.textContent = "Auto-Scheduler: Stopped";
  }
});

// ── Next Batch Live Panel ────────────────────────────────────────────────────
socket.on("next_batches", data => {
  let panel = document.getElementById("next-batch-panel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "next-batch-panel";
    panel.style.cssText = `
      margin: 10px 0 6px 0;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 13px;
    `;
    const bar = document.getElementById("scheduler-status-bar");
    if (bar) bar.parentNode.insertBefore(panel, bar.nextSibling);
  }

  const accs = data.accounts || [];
  panel.innerHTML = `
    <div style="font-weight:700; margin-bottom:7px; color:#a78bfa;">⏰ Agle Batches & Aaj ka Score</div>
    ${accs.map(a => {
      const pct = Math.min(100, Math.round((a.done_today / (a.limit || 1)) * 100));
      const barColor = pct >= 100 ? "#22c55e" : "#a78bfa";
      const isFiring = a.mins_left === 0;
      const timeLabel = a.mins_left < 0
        ? `<span style="color:#6b7280">Kal ke liye reset</span>`
        : isFiring
          ? `<span style="color:#f59e0b; font-weight:700; animation:pulse 1s infinite;">🔥 FIRING NOW!</span>`
          : `<span style="color:#38bdf8">⏳ ${a.next_at} <small>(${a.mins_left} min baad)</small></span>`;
      return `
        <div style="display:flex; flex-direction:column; gap:3px; margin-bottom:8px; padding-bottom:8px; border-bottom:1px solid rgba(255,255,255,0.07); ${isFiring ? 'border:1.5px solid #f59e0b; border-radius:8px; padding:6px; box-shadow:0 0 12px rgba(245,158,11,0.4);' : ''}">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-weight:600; color:#e2e8f0">👤 ${a.name}</span>
            <span style="color:#94a3b8">${a.done_today}/${a.limit} aaj &nbsp; | &nbsp; ${a.batches_left} batches baaki</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <div style="flex:1; background:rgba(255,255,255,0.08); border-radius:99px; height:6px; overflow:hidden;">
              <div style="width:${pct}%; height:100%; background:${barColor}; border-radius:99px; transition:width 0.5s;"></div>
            </div>
            ${timeLabel}
          </div>
        </div>`;
    }).join("")}
  `;
});

// Daily summary update
socket.on("daily_update", data => {
  document.getElementById("total-today").textContent = data.total_today || 0;
  document.getElementById("total-invited").textContent = data.total_all_time || 0;
});

// ── Toast Notification ───────────────────────────────────────────────────────
function showToast(msg, color = "#22c55e") {
  let toast = document.getElementById("invite-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "invite-toast";
    toast.style.cssText = `
      position:fixed; bottom:28px; right:28px; z-index:9999;
      padding:12px 22px; border-radius:14px;
      font-weight:700; font-size:15px; color:#fff;
      box-shadow:0 4px 24px rgba(0,0,0,0.4);
      transition:opacity 0.4s, transform 0.4s;
      pointer-events:none;
    `;
    document.body.appendChild(toast);
  }
  toast.style.background = color;
  toast.textContent = msg;
  toast.style.opacity = "1";
  toast.style.transform = "translateY(0)";
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(16px)";
  }, 2200);
}

// Invite progress (overall)
socket.on("invite_progress", data => {
  document.getElementById("total-invited").textContent   = data.invited;
  document.getElementById("total-remaining").textContent = data.remaining;
  const total = data.total || 1;
  const pct   = Math.min(100, Math.round(((data.invited) / total) * 100));
  document.getElementById("progress-bar").style.width  = `${pct}%`;
  document.getElementById("progress-pct").textContent   = `${pct}%`;
  showToast(`✅ +1 Member Added! Total: ${data.invited}`);
});

socket.on("invite_done", data => {
  addLog(`🎉 Session done! Invited: ${data.invited}`, "success");
});

// ════════════════════════════════════════════════════════════════════════════
// ─── ACCOUNTS LIVE STATS ─────────────────────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════
function loadAccountsLive() {
  fetch("/api/accounts").then(r => r.json()).then(data => {
    renderAccountsLive(data.accounts, data.daily);
  });
}

function renderAccountsLive(accounts_data, daily) {
  const list = document.getElementById("accounts-live-list");
  if (!accounts_data || accounts_data.length === 0) {
    list.innerHTML = '<p class="empty-msg">sessions_config.json nahi mila. bulk_session_generator.py run karo.</p>';
    return;
  }

  const totalDaily    = accounts_data.reduce((s, a) => s + a.limit, 0);
  const totalDoneToday= accounts_data.reduce((s, a) => s + a.done_today, 0);

  list.innerHTML = `
    <div class="accounts-summary">
      <strong>📊 Aaj:</strong> ${totalDoneToday} / ${totalDaily} invites
      &nbsp;|&nbsp; All time: ${daily?.total_all_time || 0}
    </div>
    ${accounts_data.map(acc => `
      <div class="acc-card-detailed">
        <div class="acc-card-header">
          <span class="acc-name">${acc.name}</span>
          <span class="acc-phone">${acc.phone}</span>
          <span class="acc-status ${acc.active ? 'active' : 'done'}">${acc.active ? '🟢 Active' : '✅ Done'}</span>
        </div>
        <div class="acc-progress-row">
          <div class="acc-track">
            <div class="acc-bar" style="width:${acc.pct}%"></div>
          </div>
          <span class="acc-nums">${acc.done_today}/${acc.limit}</span>
        </div>
      </div>
    `).join("")}
  `;
}

socket.on("accounts_status", data => {
  renderAccountsLive(data.accounts, data.daily);
  // Also update today counter in auto tab
  if (data.daily) {
    document.getElementById("total-today").textContent  = data.daily.total_today || 0;
    document.getElementById("total-invited").textContent = data.daily.total_all_time || 0;
  }
});

socket.on("account_update", data => {
  // Refresh accounts list whenever an account completes a batch
  loadAccountsLive();
});

document.getElementById("refresh-accounts-btn")?.addEventListener("click", () => {
  loadAccountsLive();
  socket.emit("get_accounts_status");
});

// ════════════════════════════════════════════════════════════════════════════
// ─── MANUAL ACCOUNTS (for manual mode) ───────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════
function renderManualAccounts() {
  const list = document.getElementById("accounts-list");
  if (!accounts.length) { list.innerHTML = ""; return; }
  list.innerHTML = accounts.map((acc, i) => `
    <div class="acc-card">
      <div><span>${acc.phone}</span> <small style="color:var(--muted); margin-left:8px">API: ${acc.api_id}</small></div>
      <button onclick="removeAccount(${i})">✕</button>
    </div>
  `).join("");
}
window.removeAccount = i => { accounts.splice(i, 1); renderManualAccounts(); };

document.getElementById("add-acc-btn").addEventListener("click", () => {
  const api_id   = document.getElementById("acc-api-id").value.trim();
  const api_hash = document.getElementById("acc-api-hash").value.trim();
  const phone    = document.getElementById("acc-phone").value.trim();
  if (!api_id || !api_hash || !phone) { addLog("❌ All account fields fill karo.", "error"); return; }
  accounts.push({ api_id, api_hash, phone });
  renderManualAccounts();
  addLog(`✅ Manual account added: ${phone}`, "success");
  document.getElementById("acc-api-id").value   = "";
  document.getElementById("acc-api-hash").value = "";
  document.getElementById("acc-phone").value    = "";
});

// ── Download ──────────────────────────────────────────────────────────────
window.download = type => { window.location.href = `/api/download/${type}`; };

// ── Load progress on start ────────────────────────────────────────────────
window.addEventListener("load", () => {
  fetch("/api/progress").then(r => r.json()).then(data => {
    if (data.invited > 0) {
      document.getElementById("total-invited").textContent   = data.invited;
      document.getElementById("total-remaining").textContent = data.remaining || "—";
      if (data.daily) {
        document.getElementById("total-today").textContent = data.daily.total_today || 0;
      }
      addLog(`🔄 Last session resumed: ${data.invited} invited, ${data.remaining} remaining.`, "warn");
    }
    if (data.accounts) renderAccountsLive(data.accounts, data.daily);
  });
});
