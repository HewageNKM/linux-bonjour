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

// --- CUSTOM MODALS ---
const promptModal = getEl('prompt-modal');
const promptTitle = getEl('prompt-title');
const promptMessage = getEl('prompt-message');
const promptInput = getEl('prompt-input');
const promptCancelBtn = getEl('prompt-cancel-btn');
const promptOkBtn = getEl('prompt-ok-btn');
const statHealthScore = getEl('stat-health-score');
const statHealthDesc = getEl('stat-health-desc');
const healthBar = getEl('health-bar');

function customPrompt(title, message, defaultValue = "") {
    return new Promise((resolve) => {
        promptTitle.innerText = title;
        promptMessage.innerText = message;
        promptInput.value = defaultValue;
        promptModal.classList.remove('hidden');
        promptInput.focus();
        promptInput.select();

        const cleanup = () => {
            promptModal.classList.add('hidden');
            // Use once: true or remove listeners to avoid accumulation
            promptOkBtn.onclick = null;
            promptCancelBtn.onclick = null;
            promptInput.onkeydown = null;
        };

        promptOkBtn.onclick = () => {
            const val = promptInput.value;
            cleanup();
            resolve(val);
        };

        promptCancelBtn.onclick = () => {
            cleanup();
            resolve(null);
        };

        promptInput.onkeydown = (e) => {
            if (e.key === 'Enter') promptOkBtn.onclick();
            if (e.key === 'Escape') promptCancelBtn.onclick();
        };
    });
}
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
const statActiveModel = getEl('stat-active-model');
const statLivenessMode = getEl('stat-liveness-mode');
const stat3dGuard = getEl('stat-3d-guard');
const stat3dDesc = getEl('stat-3d-desc');
const statGroups = getEl('stat-groups');
const btnStartService = getEl('btn-start-service');
const btnStopService = getEl('btn-stop-service');
const btnRestartService = getEl('btn-restart-service');
const enrollmentModal = getEl('enrollment-modal');
const enrollmentVideo = getEl('enrollment-video');
const enrollmentInstruction = getEl('enrollment-instruction');
const cancelEnrollmentBtn = getEl('cancel-enrollment');
const progressCircle = document.querySelector('.progress-ring__circle');
if (progressCircle) {
    const radius = progressCircle.r.baseVal.value;
    const circumference = radius * 2 * Math.PI;
    progressCircle.style.strokeDasharray = `${circumference} ${circumference}`;
    progressCircle.style.strokeDashoffset = circumference;
}

function setEnrollmentProgress(percent) {
    if (!progressCircle) return;
    const radius = progressCircle.r.baseVal.value;
    const circumference = radius * 2 * Math.PI;
    const offset = circumference - (percent / 100) * circumference;
    progressCircle.style.strokeDashoffset = offset;
}

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
// --- SERVICE MANAGEMENT ---
async function handleServiceAction(action) {
    try {
        showToast(`${action.charAt(0).toUpperCase() + action.slice(1)}ing service...`, 'info');
        await invoke("manage_service", { action });
        showToast(`Service ${action}ed successfully!`);
        setTimeout(updateSystemStatus, 1000);
    } catch (err) {
        showToast(`Service action failed: ${err}`, 'error');
    }
}

if (btnStartService) btnStartService.addEventListener('click', () => handleServiceAction('start'));
if (btnStopService) btnStopService.addEventListener('click', () => handleServiceAction('stop'));
if (btnRestartService) btnRestartService.addEventListener('click', () => handleServiceAction('restart'));

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
            activeModel: model,
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
                <div class="identity-actions">
                    <button class="rename-btn" data-user="${user}">RENAME</button>
                    <button class="delete-btn" data-user="${user}">DELETE</button>
                </div>
            `;
            identityList.appendChild(el);
        });

        identityList.querySelectorAll('.rename-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const oldName = btn.dataset.user;
                const newName = await customPrompt(
                    "Rename Identity",
                    `Enter a new name for '${oldName}':`,
                    oldName
                );
                if (newName && newName !== oldName) {
                    try {
                        await invoke("rename_identity", { oldName, newName });
                        showToast(`Renamed ${oldName} to ${newName}`);
                        loadIdentities();
                    } catch (err) {
                        showToast(`Rename failed: ${err}`, 'error');
                    }
                }
            });
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
            if (statActiveModel) {
                statActiveModel.innerText = hw.active_model || "None";
            }
            
            statTpm.className = `stat-value ${hw.tpm.includes('Active') ? 'success' : 'info'}`;
            statAcceleration.className = `stat-value ${hw.acceleration.includes('GPU') ? 'success' : 'info'}`;
            statCamera.className = `stat-value ${hw.camera.includes('IR') ? 'success' : 'info'}`;
            if (statActiveModel) statActiveModel.className = 'stat-value success';
        }
        
        const cfg = await invoke("get_config");
        if (cfg.status === "CONFIG" && statSecurity) {
            let secLevel = "Standard";
            if (cfg.threshold > 0.45) secLevel = "Strict";
            if (cfg.threshold < 0.40) secLevel = "Lenient";
            statSecurity.innerText = `${secLevel} (${cfg.threshold.toFixed(2)})`;
            statSecurity.className = `stat-value ${cfg.threshold >= 0.45 ? 'success' : 'info'}`;
            
            if (cfg.smile_required) {
                statLiveness.innerText = "Enabled";
                statLiveness.className = 'stat-value success';
                if (statLivenessMode) statLivenessMode.innerText = "Active (Smile)";
            } else if (cfg.liveness_enabled) {
                statLiveness.innerText = "Enabled";
                statLiveness.className = 'stat-value success';
                if (statLivenessMode) statLivenessMode.innerText = "Passive (LBP)";
            } else {
                statLiveness.innerText = "Disabled";
                statLiveness.className = 'stat-value danger';
                if (statLivenessMode) statLivenessMode.innerText = "N/A";
            }
            if (statLivenessMode) statLivenessMode.className = cfg.liveness_enabled || cfg.smile_required ? 'stat-value success' : 'stat-value danger';
            
            statRetries.innerText = `${cfg.retry_limit} Attempts`;
            statRetries.className = 'stat-value info';

            if (stat3dGuard) {
                if (cfg.depth_active) {
                    stat3dGuard.innerText = "ACTIVE";
                    stat3dGuard.className = 'stat-value success';
                    stat3dDesc.innerText = "Hardware 3D Shield enabled";
                } else if (cfg.liveness_enabled) {
                    stat3dGuard.innerText = "STANDBY";
                    stat3dGuard.className = 'stat-value info';
                    stat3dDesc.innerText = "Software 2D Liveness active";
                } else {
                    stat3dGuard.innerText = "OFF";
                    stat3dGuard.className = 'stat-value danger';
                    stat3dDesc.innerText = "Anti-spoofing disabled";
                }
            }
        }

        // Security Groups check
        try {
            const groups = await invoke("check_groups");
            const hasTpm = groups.includes('tss') || groups.includes('vtpm');
            const hasVideo = groups.includes('video');
            
            let groupText = "";
            if (hasTpm && hasVideo) groupText = "Ready (tss, video)";
            else if (hasTpm) groupText = "Missing video group";
            else if (hasVideo) groupText = "Missing tss group";
            else groupText = "No access groups!";
            
            if (statGroups) {
                statGroups.innerText = groupText;
                statGroups.className = `stat-value ${hasTpm && hasVideo ? 'success' : 'danger'}`;
            }
        } catch (e) { console.error("Group check failed", e); }
        
        const idents = await invoke("list_identities");
        if (idents.status === "IDENTITY_LIST") {
            statIdentities.innerText = idents.users.length;
        }

        // --- HEALTH SCORE CALCULATION ---
        let score = 0;
        let reasons = [];

        // 1. TPM (40%)
        if (hw.tpm && hw.tpm.includes('Active')) {
            score += 40;
        } else {
            reasons.push("TPM not active");
        }

        // 2. Camera (30%)
        if (hw.camera && hw.camera.includes('Detected')) {
            score += 30;
            if (hw.camera.includes('IR')) {
                // Bonus for IR (aesthetic only for now)
            }
        } else {
            reasons.push("Camera not detected");
        }

        // 3. Model (20%)
        if (hw.active_model && hw.active_model !== "None") {
            score += 20;
        } else {
            reasons.push("AI model missing");
        }

        // 4. Permission Groups (10%)
        const groups = await invoke("check_groups");
        const hasTpmGroup = groups.includes('tss') || groups.includes('vtpm');
        const hasVideoGroup = groups.includes('video');
        if (hasTpmGroup && hasVideoGroup) {
            score += 10;
        } else {
            reasons.push("Groups missing");
        }

        if (statHealthScore) {
            statHealthScore.innerText = `${score}%`;
            healthBar.style.width = `${score}%`;
            
            let color = 'info';
            let desc = "System is fully optimized and secured.";
            if (score >= 90) color = 'success';
            else if (score >= 60) color = 'info';
            else {
                color = 'danger';
                desc = `Optimization required: ${reasons.join(', ')}`;
            }
            
            if (score === 100) desc = "Enterprise-grade hardware security active.";
            
            statHealthScore.className = `stat-value ${color}`;
            healthBar.style.background = score >= 90 ? 'var(--success)' : (score >= 60 ? 'var(--info)' : 'var(--danger)');
            if (statHealthDesc) statHealthDesc.innerText = desc;
        }
    } catch (error) {
        console.warn("Status update cycle failed:", error);
    }
}

// --- ENROLLMENT ---
enrollBtn.addEventListener('click', async () => {
    const user = usernameInput.value.trim() || "default";

    enrollBtn.disabled = true;
    enrollmentModal.classList.remove('hidden');
    setEnrollmentProgress(0);
    enrollmentInstruction.innerText = "Initializing camera...";
    enrollmentVideo.src = "";

    try {
        await invoke("run_biometric_command", { cmd: "ENROLL", user, bypass_consent: false });
    } catch (err) {
        showToast(`Enrollment failed: ${err}`, "error");
        enrollmentModal.classList.add('hidden');
        enrollBtn.disabled = false;
    }
});

if (cancelEnrollmentBtn) {
    cancelEnrollmentBtn.addEventListener('click', async () => {
        enrollmentModal.classList.add('hidden');
        enrollBtn.disabled = false;
        try {
            await invoke("stop_biometric_command");
        } catch (e) {
            console.warn("Could not stop biometric command:", e);
        }
    });
}

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
    
    if (resp.status === "ENROLLMENT_FRAME") {
        if (enrollmentVideo) {
            enrollmentVideo.src = `data:image/jpeg;base64,${resp.base64_image}`;
        }
        if (enrollmentInstruction) {
            enrollmentInstruction.innerText = resp.message;
        }
        setEnrollmentProgress(resp.progress * 100);
    } else if (resp.status === "SCANNING") {
        // Scanning feedback (reduced noise)
    } else if (resp.status === "INFO") {
        if (resp.msg === "CONSENT_REQUIRED") {
            const user = usernameInput.value.trim() || "default";
            enrollmentInstruction.innerText = "Authorization Required...";
            
            // Trigger PKEXEC system validation
            invoke("validate_user").then(validated => {
                if (validated) {
                    invoke("run_biometric_command", { cmd: "ENROLL", user, bypass_consent: true });
                } else {
                    showToast("Authorization cancelled", "info");
                    enrollmentModal.classList.add('hidden');
                    enrollBtn.disabled = false;
                }
            }).catch(e => {
                showToast(`Authorization failed: ${e}`, "error");
                enrollmentModal.classList.add('hidden');
                enrollBtn.disabled = false;
            });
        } else {
            showToast(resp.msg, "info");
        }
    } else if (resp.status === "SUCCESS") {
        if (enrollBtn.disabled) {
            // This was likely an enrollment success
            showToast(`Enrollment successful!`);
            enrollmentModal.classList.add('hidden');
            enrollBtn.disabled = false;
            loadIdentities();
        } else {
            showToast(`Authenticated: ${resp.user}`, "success");
            updateSystemStatus();
        }
    } else if (resp.status === "ACTION_SUCCESS") {
        showToast(resp.msg, "success");
        updateSystemStatus();
    } else if (resp.status === "FAILURE") {
        showToast(`Error: ${resp.reason}`, "error");
        if (enrollBtn.disabled) {
            enrollmentModal.classList.add('hidden');
            enrollBtn.disabled = false;
        }
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
