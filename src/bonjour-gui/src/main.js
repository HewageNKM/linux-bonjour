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
const livenessThresholdSlider = getEl('liveness-threshold-slider');
const livenessThresholdValue = getEl('liveness-threshold-value');
const settingSmile = getEl('setting-smile');
const settingAutocapture = getEl('setting-autocapture');
const settingLiveness = getEl('setting-liveness');
const settingSystemEnabled = getEl('setting-system-enabled');
const settingAskPermission = getEl('setting-ask-permission');
const settingRetryLimit = getEl('setting-retry-limit');
const settingModel = getEl('setting-model');
const settingCamera = getEl('setting-camera');
const settingEnableLogin = getEl('setting-enable-login');
const settingEnableSudo = getEl('setting-enable-sudo');
const settingEnablePolkit = getEl('setting-enable-polkit');
const toastContainer = getEl('toast-container');
const usernameInput = getEl('username');
const enrollBtn = getEl('enroll-btn');

// Hardware Elements
const statTpm = getEl('stat-tpm');
const statAcceleration = getEl('stat-acceleration');
const statCamera = getEl('stat-camera');

// Security Elements
const statSecurity = getEl('stat-security');
const statLiveness = getEl('stat-liveness');
const statRetries = getEl('stat-retries');

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

// --- CUSTOM MODAL SYSTEM ---
function customConfirm(title, message, isDanger = false) {
    return new Promise((resolve) => {
        const modal = getEl('confirm-modal');
        const titleEl = getEl('confirm-title');
        const msgEl = getEl('confirm-message');
        const okBtn = getEl('confirm-ok-btn');
        const cancelBtn = getEl('confirm-cancel-btn');

        titleEl.innerText = title;
        msgEl.innerText = message;
        
        // Reset styles and listeners
        okBtn.className = isDanger ? 'primary-btn danger' : 'primary-btn';
        
        const cleanup = () => {
            modal.classList.add('hidden');
            okBtn.removeEventListener('click', onOk);
            cancelBtn.removeEventListener('click', onCancel);
        };

        const onOk = () => { cleanup(); resolve(true); };
        const onCancel = () => { cleanup(); resolve(false); };

        okBtn.addEventListener('click', onOk);
        cancelBtn.addEventListener('click', onCancel);

        modal.classList.remove('hidden');
    });
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
        if (viewName === 'settings') syncSettings();
    });
});

// --- SETTINGS LOGIC ---
async function syncSettings() {
    try {
        const cfg = await invoke("get_config");
        if (cfg.status === "CONFIG") {
            thresholdSlider.value = cfg.threshold * 100;
            thresholdValue.innerText = cfg.threshold.toFixed(2);
            settingSmile.checked = cfg.smile_required;
            settingAutocapture.checked = cfg.autocapture;
            settingLiveness.checked = cfg.liveness_enabled;
            livenessThresholdSlider.value = cfg.liveness_threshold * 100;
            livenessThresholdValue.innerText = cfg.liveness_threshold.toFixed(2);
            settingAskPermission.checked = cfg.ask_permission;
            settingRetryLimit.value = cfg.retry_limit;
            
            settingSystemEnabled.checked = cfg.enabled;
            settingEnableLogin.checked = cfg.enable_login;
            settingEnableSudo.checked = cfg.enable_sudo;
            settingEnablePolkit.checked = cfg.enable_polkit;

            // Populate Camera List
            const cameras = await invoke("get_camera_list");
            if (cameras.status === "CAMERA_LIST") {
                const current = cfg.camera_path || 'auto';
                settingCamera.innerHTML = '<option value="auto">Auto-Detect (Recommended)</option>';
                cameras.devices.forEach(cam => {
                    const opt = document.createElement('option');
                    opt.value = cam.path;
                    opt.innerText = `${cam.name} [${cam.path}]`;
                    settingCamera.appendChild(opt);
                });
                settingCamera.value = current;
            }

        }
    } catch (err) {
        console.error("Failed to sync settings:", err);
    }
}

thresholdSlider.addEventListener('input', (e) => {
    const val = (e.target.value / 100).toFixed(2);
    thresholdValue.innerText = val;
});

livenessThresholdSlider.addEventListener('input', (e) => {
    const val = (e.target.value / 100).toFixed(2);
    livenessThresholdValue.innerText = val;
});

getEl('save-settings-btn').addEventListener('click', async () => {
    const confirmed = await customConfirm(
        "Save Configuration", 
        "Are you sure you want to apply these system-wide biometric settings?", 
        false
    );
    
    if (!confirmed) return;

    try {
        const threshold = parseFloat(thresholdSlider.value) / 100;
        const liveness_threshold = parseFloat(livenessThresholdSlider.value) / 100;
        const smile_required = settingSmile.checked;
        const autocapture = settingAutocapture.checked;
        const liveness_enabled = settingLiveness.checked;
        const ask_permission = settingAskPermission.checked;
        const retry_limit = parseInt(settingRetryLimit.value) || 3;
        const camera_path = settingCamera.value === 'auto' ? null : settingCamera.value;
        const model = settingModel.value;


        // Sync Global State
        await invoke("toggle_system", { enabled: settingSystemEnabled.checked });

        await invoke("update_config", { 
            threshold, 
            smileRequired: smile_required,
            autocapture: autocapture,
            livenessEnabled: liveness_enabled,
            livenessThreshold: liveness_threshold,
            askPermission: ask_permission,
            retryLimit: retry_limit,
            cameraPath: camera_path,
            enableLogin: settingEnableLogin.checked,
            enableSudo: settingEnableSudo.checked,
            enablePolkit: settingEnablePolkit.checked
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

        identityList.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const user = btn.dataset.user;
                const confirmed = await customConfirm(
                    "Delete Identity",
                    `Are you sure you want to permanently delete the biometric profile for '${user}'? This action cannot be undone.`,
                    true
                );
                
                if (confirmed) {
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
        const status = await invoke("get_system_status");
        statStatus.innerText = status.enabled ? "Active" : "Disabled";
        statStatus.className = `stat-value ${status.enabled ? 'success' : 'danger'}`;
        
        const hw = await invoke("get_hardware_status");
        if (hw.status === "HARDWARE_STATUS") {
            statTpm.innerText = hw.tpm;
            statAcceleration.innerText = hw.acceleration;
            statCamera.innerText = hw.camera;
            
            statTpm.className = `stat-value ${hw.tpm.includes('Active') ? 'success' : 'info'}`;
            statAcceleration.className = `stat-value ${hw.acceleration.includes('GPU') ? 'success' : 'info'}`;
            statCamera.className = `stat-value ${hw.camera.includes('IR') ? 'success' : 'info'}`;
        }
        
        const cfg = await invoke("get_config");
        if (cfg.status === "CONFIG" && statSecurity) {
            let secLevel = "Standard";
            if (cfg.threshold > 0.45) secLevel = "Strict";
            if (cfg.threshold < 0.40) secLevel = "Lenient";
            statSecurity.innerText = `${secLevel} (${cfg.threshold.toFixed(2)})`;
            statSecurity.className = `stat-value ${cfg.threshold >= 0.45 ? 'success' : 'info'}`;
            
            if (cfg.smile_required) {
                statLiveness.innerText = "Active (Smile)";
                statLiveness.className = 'stat-value success';
            } else if (cfg.liveness_enabled) {
                statLiveness.innerText = "Passive (LBP)";
                statLiveness.className = 'stat-value success';
            } else {
                statLiveness.innerText = "Disabled";
                statLiveness.className = 'stat-value danger';
            }
            
            statRetries.innerText = `${cfg.retry_limit} Attempts`;
            statRetries.className = 'stat-value info';
        }
        
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
    const user = usernameInput.value.trim() || "default";

    enrollBtn.disabled = true;
    showToast(`Starting capture for ${user}...`, "info");

    try {
        await invoke("run_biometric_command", { cmd: "ENROLL", user });
        showToast(user === "default" ? "Enrollment successful!" : `Enrollment successful for ${user}!`);
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
        // Scanning feedback (reduced noise)
    } else if (resp.status === "INFO") {
        showToast(resp.msg, "info");
    } else if (resp.status === "SUCCESS") {
        showToast(`Authenticated: ${resp.user}`, "success");
        updateSystemStatus();
    } else if (resp.status === "ACTION_SUCCESS") {
        showToast(resp.msg, "success");
        updateSystemStatus();
    } else if (resp.status === "FAILURE") {
        showToast(resp.reason, "error");
    }
});

// --- INITIALIZATION ---
(async () => {
    await syncSettings();
    await updateSystemStatus();
    await loadIdentities();
    
    // Background polling for status
    setInterval(updateSystemStatus, 15000);
})();
