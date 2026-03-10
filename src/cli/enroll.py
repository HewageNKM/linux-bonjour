import numpy as np
import cv2
import sys
import os
from insightface.app import FaceAnalysis

import json

# Add daemon path to import our Camera
sys.path.append(os.path.abspath("src"))
import io
from daemon.camera import IRCamera
from daemon.crypto_utils import encrypt_data

CONFIG_PATH = "config/config.json"

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {"model_name": "buffalo_s", "users_dir": "config/users"}

def enroll_user(username=None):
    if not username:
        username = input("Enter username to enroll: ").strip()
    
    if not username:
        print("Username cannot be empty.")
        return

    config = load_config()
    model_name = config.get("model_name", "buffalo_s")
    
    print(f"Initializing enrollment with model: {model_name}...")
    app = FaceAnalysis(name=model_name, providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(320, 320))

    cam = IRCamera()
    print(f"Look at the IR camera to enroll '{username}'...")
    
    # Wait for a valid frame
    frame = None
    for _ in range(5): # retry a few times
        frame = cam.get_frame()
        if frame is not None: break
        import time
        time.sleep(0.5)

    if frame is None:
        print("Could not access camera.")
        return

    faces = app.get(frame)
    if faces:
        embedding = faces[0].normed_embedding
        
        model_name = config.get("model_name", "buffalo_s")
        model_base = model_name.replace("_int8", "")
        users_dir = os.path.join(config.get("users_dir", "config/users"), model_base)
        
        if not os.path.exists(users_dir):
            os.makedirs(users_dir)
            
        save_path = os.path.join(users_dir, f"{username}.enc")
        
        # Encrypt the embedding
        buffer = io.BytesIO()
        np.save(buffer, embedding)
        encrypted_data = encrypt_data(buffer.getvalue())
        
        with open(save_path, 'wb') as f:
            f.write(encrypted_data)
        
        # Also maintain legacy owner.npy for the first user
        if not os.path.exists("config/owner.npy"):
            np.save("config/owner.npy", embedding)
            
        print(f"Enrollment Complete for {username}! Face vector saved.")
    else:
        print("No face detected. Try adjusting the camera angle.")

if __name__ == "__main__":
    import time
    u = sys.argv[1] if len(sys.argv) > 1 else None
    enroll_user(u)