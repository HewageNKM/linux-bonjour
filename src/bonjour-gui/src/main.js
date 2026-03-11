const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

// UI Elements
const statusLog = document.getElementById("status-log");
const usernameInput = document.getElementById("username");
const enrollBtn = document.getElementById("enroll-btn");
const enabledToggle = document.getElementById("system-enabled");
const navItems = document.querySelectorAll(".nav-item");
const views = document.querySelectorAll(".view");
const identityList = document.getElementById("identity-list");
const saveSettingsBtn = document.getElementById("save-settings-btn");
const refreshLogsBtn = document.getElementById("refresh-logs");

// Tab Switching Logic
navItems.forEach(item => {
  item.addEventListener("click", () => {
    const targetView = item.getAttribute("data-view");
    
    // Update Nav
    navItems.forEach(ni => ni.classList.remove("active"));
    item.classList.add("active");

    // Update View
    views.forEach(v => v.classList.remove("active"));
    document.getElementById(`view-${targetView}`).classList.add("active");
    
    if (targetView === "logs") fetchJournalLogs();
    if (targetView === "enrollment") fetchIdentities();
    if (targetView === "dashboard") updateDashboardStats();
  });
});

function addLog(msg, type = "info") {
  const entry = document.createElement("div");
  entry.className = `log-entry ${type}`;
  entry.innerText = `[${new Date().toLocaleTimeString()}] ${msg}`;
  statusLog.appendChild(entry);
  statusLog.scrollTop = statusLog.scrollHeight;
}

// Enrollment Logic
async function startEnrollment() {
  const user = usernameInput.value.trim();
  if (!user) {
    addLog("Please enter a username", "error");
    return;
  }

  enrollBtn.disabled = true;
  addLog(`Starting ENROLL for user: ${user}...`, "info");

  try {
    await invoke("run_biometric_command", { cmd: "ENROLL", user });
    fetchIdentities(); // Refresh list after enrollment
  } catch (err) {
    addLog(`Error: ${err}`, "error");
  } finally {
    enrollBtn.disabled = false;
  }
}

// Identity Management
async function fetchIdentities() {
  try {
    const resp = await invoke("list_identities");
    if (resp.status === "IDENTITY_LIST") {
      renderIdentityList(resp.users);
      document.getElementById("stat-identities").innerText = resp.users.length;
    }
  } catch (err) {
    addLog(`Failed to fetch identities: ${err}`, "error");
  }
}

function renderIdentityList(users) {
  identityList.innerHTML = "";
  if (users.length === 0) {
    identityList.innerHTML = '<div class="empty-state">No identities enrolled.</div>';
    return;
  }

  users.forEach(user => {
    const item = document.createElement("div");
    item.className = "identity-item";
    item.innerHTML = `
      <div class="identity-info">
        <div class="identity-avatar">${user[0].toUpperCase()}</div>
        <span>${user}</span>
      </div>
      <button class="delete-btn" onclick="deleteUser('${user}')">DELETE</button>
    `;
    identityList.appendChild(item);
  });
}

window.deleteUser = async (user) => {
  if (!confirm(`Are you sure you want to delete profile for '${user}'?`)) return;
  try {
    const resp = await invoke("delete_identity", { user });
    if (resp.status === "ACTION_SUCCESS") {
      addLog(`Profile for ${user} deleted`, "info");
      fetchIdentities();
      updateDashboardStats();
    }
  } catch (err) {
    addLog(`Delete failed: ${err}`, "error");
  }
};

// Settings Logic
const thresholdSlider = document.getElementById("threshold-slider");
const thresholdValue = document.getElementById("threshold-value");
const smileCheckbox = document.getElementById("setting-smile");

thresholdSlider.addEventListener("input", () => {
  const val = (thresholdSlider.value / 100).toFixed(2);
  thresholdValue.innerText = val;
});

saveSettingsBtn.addEventListener("click", async () => {
  const threshold = parseFloat(thresholdValue.innerText);
  const smile_required = smileCheckbox.checked;
  
  try {
    await invoke("update_config", { threshold, smileRequired: smile_required });
    addLog("Configuration saved successfully", "success");
  } catch (err) {
    addLog(`Save failed: ${err}`, "error");
  }
});

// Logs Logic
async function fetchJournalLogs() {
  const output = document.getElementById("journal-output");
  output.innerText = "Fetching latest logs...";
  try {
    const logs = await invoke("get_journal_logs");
    output.innerText = logs || "--- No logs found ---";
    output.scrollTop = output.scrollHeight;
  } catch (err) {
    output.innerText = `Error: ${err}`;
  }
}

refreshLogsBtn.addEventListener("click", fetchJournalLogs);

// Dashboard Logic
async function updateDashboardStats() {
  try {
    const status = await invoke("get_system_status");
    const identities = await invoke("list_identities");
    
    document.getElementById("stat-status").innerText = status.enabled ? "Active" : "Disabled";
    document.getElementById("stat-status").className = `stat-value ${status.enabled ? "success" : ""}`;
    
    if (identities.status === "IDENTITY_LIST") {
      document.getElementById("stat-identities").innerText = identities.users.length;
    }
  } catch (err) {
    console.error("Dashboard sync failed:", err);
  }
}

// Event Listeners
enrollBtn.addEventListener("click", startEnrollment);

enabledToggle.addEventListener("change", async () => {
  const enabled = enabledToggle.checked;
  try {
    await invoke("toggle_system", { enabled });
    addLog(`System ${enabled ? "Enabled" : "Disabled"}`, enabled ? "success" : "info");
    updateDashboardStats();
  } catch (err) {
    addLog(`Failed to toggle system: ${err}`, "error");
    enabledToggle.checked = !enabled;
  }
});

// Listen for status updates from Rust
listen("biometric-status", (event) => {
  const resp = event.payload;
  if (resp.status === "SCANNING") {
    addLog(`📸 ${resp.msg}`, "info");
  } else if (resp.status === "SUCCESS") {
    addLog(`✅ SUCCESS: ${resp.user} matched!`, "success");
    updateDashboardStats(); // Refresh stats on success
  } else if (resp.status === "FAILURE") {
    addLog(`❌ FAILURE: ${resp.reason}`, "error");
  } else if (resp.status === "INFO") {
    addLog(`💡 ${resp.msg}`, "info");
  }
});

// Initial Setup
(async () => {
    updateDashboardStats();
    fetchIdentities();
})();
