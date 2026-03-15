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

// Daily summary update
socket.on("daily_update", data => {
  document.getElementById("total-today").textContent = data.total_today || 0;
  document.getElementById("total-invited").textContent = data.total_all_time || 0;
});

// Invite progress (overall)
socket.on("invite_progress", data => {
  document.getElementById("total-invited").textContent   = data.invited;
  document.getElementById("total-remaining").textContent = data.remaining;
  const total = data.total || 1;
  const pct   = Math.min(100, Math.round(((data.invited) / total) * 100));
  document.getElementById("progress-bar").style.width  = `${pct}%`;
  document.getElementById("progress-pct").textContent   = `${pct}%`;
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
