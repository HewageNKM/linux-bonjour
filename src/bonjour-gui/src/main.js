const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

// UI Selection
const getEl = (id) => document.getElementById(id);

// Elements
const navItems = document.querySelectorAll('.nav-item');
const views = document.querySelectorAll('.view');
const statStatus = getEl('stat-status');
const statIdentities = getEl('stat-identities');
const identityList = getEl('identity-list');
const journalOutput = getEl('journal-output');
const thresholdSlider = getEl('threshold-slider');
const thresholdValue = getEl('threshold-value');
const settingSmile = getEl('setting-smile');
const settingAutocapture = getEl('setting-autocapture');
const settingLiveness = getEl('setting-liveness');
const settingSystemEnabled = getEl('setting-system-enabled');
const settingAskPermission = getEl('setting-ask-permission');
const settingRetryLimit = getEl('setting-retry-limit');
const settingModel = getEl('setting-model');
const toastContainer = getEl('toast-container');
const usernameInput = getEl('username');
const enrollBtn = getEl('enroll-btn');

// Hardware Elements
const statTpm = getEl('stat-tpm');
const statAcceleration = getEl('stat-acceleration');
const statCamera = getEl('stat-camera');

// --- NOTIFICATION SYSTEM ---
function showToast(message, type = 'success') {
    if (!toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = '✓';
    if (type === 'error') icon = '✕';
    if (type === 'info') icon = 'ℹ';
    
    toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-message">${message}</div>
    `;
    
    toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'fadeOut 0.5s forwards';
        setTimeout(() => toast.remove(), 500);
    }, 4000);
}

// --- NAVIGATION ---
navItems.forEach(item => {
    item.addEventListener('click', () => {
        navItems.forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        
        const viewName = item.dataset.view;
        views.forEach(v => {
            v.classList.toggle('active', v.id === `view-${viewName}`);
        });
        
        if (viewName === 'enrollment') loadIdentities();
        if (viewName === 'logs') loadLogs();
        if (viewName === 'dashboard') updateSystemStatus();
    });
});

// --- SETTINGS LOGIC ---
thresholdSlider.addEventListener('input', (e) => {
    const val = (e.target.value / 100).toFixed(2);
    thresholdValue.innerText = val;
});

getEl('save-settings-btn').addEventListener('click', async () => {
    try {
        const threshold = parseFloat(thresholdSlider.value) / 100;
        const smile_required = settingSmile.checked;
        const autocapture = settingAutocapture.checked;
        const liveness_enabled = settingLiveness.checked;
        const ask_permission = settingAskPermission.checked;
        const retry_limit = parseInt(settingRetryLimit.value) || 3;
        const model = settingModel.value;

        // Sync Global State if Changed
        await invoke("set_enabled", { enabled: settingSystemEnabled.checked });

        await invoke("update_config", { 
            threshold, 
            smileRequired: smile_required,
            autocapture: autocapture,
            livenessEnabled: liveness_enabled,
            askPermission: ask_permission,
            retryLimit: retry_limit
        });
        
        showToast("Configuration saved successfully!");
        
        if (model !== "buffalo_l") {
            showToast(`Model ${model} requested (Download on-demand)`, 'info');
            await invoke("download_model", { name: model });
        }
    } catch (error) {
        showToast(`Failed to save: ${error}`, 'error');
    }
});

// --- IDENTITY MANAGEMENT ---
async function loadIdentities() {
    try {
        const resp = await invoke("list_identities");
        const users = resp.users || [];
        statIdentities.innerText = users.length;
        
        identityList.innerHTML = users.length ? "" : '<div class="empty-state">No identities enrolled.</div>';
        
        users.forEach(user => {
            const el = document.createElement('div');
            el.className = 'identity-item';
            el.innerHTML = `
                <div class="identity-info">
                    <div class="identity-avatar">${user[0].toUpperCase()}</div>
                    <span>${user}</span>
                </div>
                <button class="delete-btn" data-user="${user}">DELETE</button>
            `;
            identityList.appendChild(el);
        });

        // Add delete listeners
        identityList.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const user = btn.dataset.user;
                if (confirm(`Are you sure you want to delete profile for '${user}'?`)) {
                    try {
                        await invoke("delete_identity", { user });
                        showToast(`Profile for ${user} deleted`, 'info');
                        loadIdentities();
                    } catch (err) {
                        showToast(`Delete failed: ${err}`, 'error');
                    }
                }
            });
        });
    } catch (e) {
        console.error("Failed to list identities:", e);
    }
}

// --- SYSTEM & HARDWARE STATUS ---
async function updateSystemStatus() {
    try {
        // Core Status
        const status = await invoke("get_system_status");
        statStatus.innerText = status.enabled ? "Active" : "Disabled";
        statStatus.className = `stat-value ${status.enabled ? 'success' : 'danger'}`;
        
        // Hardware Status
        const hw = await invoke("get_hardware_status");
        if (hw.status === "HARDWARE_STATUS") {
            statTpm.innerText = hw.tpm;
            statAcceleration.innerText = hw.acceleration;
            statCamera.innerText = hw.camera;
            
            // Set colors based on status
            statTpm.className = `stat-value ${hw.tpm.includes('Active') ? 'success' : 'info'}`;
            statAcceleration.className = `stat-value ${hw.acceleration.includes('GPU') ? 'success' : 'info'}`;
            statCamera.className = `stat-value ${hw.camera.includes('IR') ? 'success' : 'info'}`;
        }
        
        // Identity Count (Sync with dashboard)
        const idents = await invoke("list_identities");
        if (idents.status === "IDENTITY_LIST") {
            statIdentities.innerText = idents.users.length;
        }
    } catch (error) {
        console.warn("Status update cycle failed:", error);
    }
}

// --- ENROLLMENT ---
enrollBtn.addEventListener('click', async () => {
    const user = usernameInput.value.trim();
    if (!user) {
        showToast("Please enter a username", "error");
        return;
    }

    enrollBtn.disabled = true;
    showToast(`Starting capture for ${user}...`, "info");

    try {
        await invoke("run_biometric_command", { cmd: "ENROLL", user });
        showToast(`Enrollment successful for ${user}!`);
        loadIdentities();
    } catch (err) {
        showToast(`Biometric Error: ${err}`, "error");
    } finally {
        enrollBtn.disabled = false;
    }
});

// --- LOGS ---
async function loadLogs() {
    try {
        const logs = await invoke("get_journal_logs");
        journalOutput.innerText = logs || "No logs found.";
        journalOutput.scrollTop = journalOutput.scrollHeight;
    } catch (e) {
        journalOutput.innerText = "Error reading system logs.";
    }
}

getEl('refresh-logs').addEventListener('click', loadLogs);

// --- LISTEN FOR REAL-TIME EVENTS ---
listen("biometric-status", (event) => {
    const resp = event.payload;
    if (resp.status === "SCANNING") {
        showToast(resp.msg, "info");
    } else if (resp.status === "SUCCESS") {
        showToast(`Authenticated: ${resp.user}`, "success");
        updateSystemStatus();
    } else if (resp.status === "FAILURE") {
        showToast(resp.reason, "error");
    }
});

// --- INITIALIZATION ---
(async () => {
    await updateSystemStatus();
    await loadIdentities();
    
    // Background polling for status
    setInterval(updateSystemStatus, 10000);
})();
