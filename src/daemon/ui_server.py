import os
import json
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from sys_info import get_system_specs, suggest_model
import numpy as np
import cv2
from insightface.app import FaceAnalysis

# Add src to path for IRCamera
import sys
sys.path.append("src")
from daemon.camera import IRCamera
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("config/ui_error.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ui_server")

app = FastAPI(title="Linux Hello Management API")

# Global variables for model and camera to avoid reloading
_face_app = None

def get_face_app():
    global _face_app
    if _face_app is None:
        config = load_config()
        model_name = config.get("model_name", "buffalo_s")
        print(f"Loading FaceAnalysis model: {model_name}...")
        _face_app = FaceAnalysis(name=model_name, providers=['CPUExecutionProvider'])
        _face_app.prepare(ctx_id=0, det_size=(320, 320))
    return _face_app

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
@app.post("/api/users/enroll")
def enroll_user(username: str):
    logger.info(f"Enrollment request for user: {username}")
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    
    try:
        app_face = get_face_app()
        cam = IRCamera()
        
        # Try to get a valid frame
        frame = None
        for i in range(10):
            frame = cam.get_frame()
            if frame is not None:
                logger.info(f"Frame captured on attempt {i+1}")
                break
            import time
            time.sleep(0.2)
            
        if frame is None:
            logger.error("Camera access failed during enrollment")
            raise HTTPException(status_code=503, detail="Could not access camera (is another app using it?)")
        
        faces = app_face.get(frame)
        if not faces:
            logger.warning(f"No face detected for {username}")
            raise HTTPException(status_code=400, detail="No face detected. Please look directly at the camera.")
        
        embedding = faces[0].normed_embedding
        config = load_config()
        users_dir = config["users_dir"]
        
        if not os.path.exists(users_dir):
            os.makedirs(users_dir)
            
        save_path = os.path.join(users_dir, f"{username}.npy")
        np.save(save_path, embedding)
        logger.info(f"Successfully enrolled {username} to {save_path}")
        
        # Also maintain legacy owner.npy for the first user
        if not os.path.exists("config/owner.npy"):
            np.save("config/owner.npy", embedding)
            
        return {"status": "success", "message": f"User {username} enrolled successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during enrollment for {username}")
        raise HTTPException(status_code=500, detail=str(e))
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
