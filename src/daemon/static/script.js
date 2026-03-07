async function init() {
    await refreshData();
}

async function refreshData() {
    // 1. Fetch Config
    const config = await (await fetch('/api/config')).json();
    document.getElementById('threshold-slider').value = config.threshold * 100;
    document.getElementById('threshold-val').textContent = config.threshold;
    document.getElementById('cooldown-val').value = config.cooldown_time;
    document.getElementById('failures-val').value = config.max_failures;
    document.getElementById('current-model-name').textContent = config.model_name.toUpperCase();

    // 2. Fetch System Info
    const sysInfo = await (await fetch('/api/sys_info')).json();
    const specs = sysInfo.specs;
    document.getElementById('specs-content').innerHTML = `
        <p>RAM: ${specs.ram_gb} GB</p>
        <p>CPU: ${specs.cpu}</p>
        <p>GPU: ${specs.gpu.split(' ').slice(0, 3).join(' ')}...</p>
    `;
    document.getElementById('specs-content').classList.remove('loading');
    document.getElementById('model-suggestion').textContent = `Suggested: ${sysInfo.suggested_model} (${sysInfo.reason})`;

    // 3. Fetch Users
    const users = await (await fetch('/api/users')).json();
    const userList = document.getElementById('user-list');
    userList.innerHTML = users.map(u => `<div class="user-tag">${u}</div>`).join('');
}

async function saveSettings() {
    const threshold = document.getElementById('threshold-slider').value / 100;
    const cooldown = parseInt(document.getElementById('cooldown-val').value);
    const failures = parseInt(document.getElementById('failures-val').value);

    const response = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            threshold: threshold,
            cooldown_time: cooldown,
            max_failures: failures
        })
    });

    if (response.ok) showNotification("Settings Saved Successfully!");
}

async function switchModel(modelName) {
    showNotification(`Downloading and switching to ${modelName}...`, 5000);
    const response = await fetch(`/api/model/switch?model_name=${modelName}`, {
        method: 'POST'
    });
    
    const result = await response.json();
    if (result.status === "success") {
        showNotification(`Switched to ${modelName}!`);
        refreshData();
    } else {
        showNotification(`Error: ${result.message}`, 5000);
    }
}

function showNotification(msg, duration = 3000) {
    const el = document.getElementById('notification');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), duration);
}

// Slider live update
document.getElementById('threshold-slider').oninput = function() {
    document.getElementById('threshold-val').textContent = (this.value / 100).toFixed(2);
};

init();
