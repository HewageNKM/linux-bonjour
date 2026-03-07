import os
import json
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from sys_info import get_system_specs, suggest_model

app = FastAPI(title="Linux Hello Management API")

CONFIG_PATH = "config/config.json"
VENV_PYTHON = "venv/bin/python3"

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)

class ConfigUpdate(BaseModel):
    threshold: Optional[float] = None
    cooldown_time: Optional[int] = None
    max_failures: Optional[int] = None
    camera_index: Optional[int] = None

@app.get("/api/config")
def get_config():
    return load_config()

@app.post("/api/config")
def update_config(update: ConfigUpdate):
    config = load_config()
    if update.threshold is not None: config["threshold"] = update.threshold
    if update.cooldown_time is not None: config["cooldown_time"] = update.cooldown_time
    if update.max_failures is not None: config["max_failures"] = update.max_failures
    if update.camera_index is not None: config["camera_index"] = update.camera_index
    save_config(config)
    return config

@app.get("/api/sys_info")
def get_sys_info():
    specs = get_system_specs()
    model, reason = suggest_model(specs)
    return {
        "specs": specs,
        "suggested_model": model,
        "reason": reason
    }

@app.get("/api/users")
def get_users():
    users_dir = load_config()["users_dir"]
    if not os.path.exists(users_dir):
        return []
    return [f.replace(".npy", "") for f in os.listdir(users_dir) if f.endswith(".npy")]

@app.post("/api/model/switch")
def switch_model(model_name: str):
    config = load_config()
    if model_name not in ["buffalo_s", "buffalo_l"]:
        raise HTTPException(status_code=400, detail="Invalid model name")
    
    # 1. Download model if needed
    print(f"Switching to model: {model_name}...")
    subprocess.run([VENV_PYTHON, "scripts/init_models.py", model_name])
    
    # 2. Update config
    config["model_name"] = model_name
    save_config(config)
    
    # 3. Restart daemon
    try:
        subprocess.run(["sudo", "systemctl", "restart", "linux-hello"])
        return {"status": "success", "message": f"Switched to {model_name} and restarted daemon"}
    except Exception as e:
        return {"status": "partial_success", "message": f"Switched to {model_name} but failed to restart daemon: {e}"}

# Serve static files last to allow API routes to take precedence
app.mount("/", StaticFiles(directory="src/daemon/static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
