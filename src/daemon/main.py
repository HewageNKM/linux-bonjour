import os
import socket
import numpy as np
import cv2
import time
import json
from insightface.app import FaceAnalysis
from camera import IRCamera

# --- Configuration Loader ---
CONFIG_PATH = "config/config.json"
def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

class FaceDaemon:
    def __init__(self):
        self.config = load_config()
        print(f"Initializing Face Recognition Engine with model: {self.config['model_name']}...")
        
        # Load model with specified provider
        self.app = FaceAnalysis(name=self.config['model_name'], providers=['CPUExecutionProvider'])
        self.app.prepare(ctx_id=0, det_size=(320, 320))
        
        # Initialize camera with optional config overrides
        self.cam = IRCamera()
        if self.config.get('camera_index') is not None:
             self.cam.index = self.config['camera_index']
             
        print(f"FaceDaemon initialized with {self.cam.camera_type} camera at index {self.cam.index}")
        
        if not os.path.exists(self.config['users_dir']):
            os.makedirs(self.config['users_dir'])

        self.failed_attempts = {}

    def verify(self, username):
        # 1. Check for Throttling
        now = time.time()
        if username in self.failed_attempts:
            count, last_time = self.failed_attempts[username]
            if count >= self.config['max_failures'] and (now - last_time) < self.config['cooldown_time']:
                print(f"User {username} is throttled. Wait {int(self.config['cooldown_time'] - (now - last_time))}s.")
                return False

        # 2. Load Embedding
        user_file = os.path.join(self.config['users_dir'], f"{username}.npy")
        if os.path.exists(user_file):
            target_embedding = np.load(user_file)
        elif os.path.exists("config/owner.npy"):
            target_embedding = np.load("config/owner.npy")
        else:
            print(f"No embedding found for user {username}")
            return False

        # 3. Capture and Verify
        frame = self.cam.get_frame()
        if frame is None: return False

        faces = self.app.get(frame)
        if not faces: return False

        live_embedding = faces[0].normed_embedding
        score = np.dot(live_embedding, target_embedding)
        
        print(f"User: {username}, Match Score: {score:.4f}")
        
        if score > self.config['threshold']:
            self.failed_attempts[username] = (0, 0) # Reset on success
            return True
        else:
            # Increment failure count
            count, _ = self.failed_attempts.get(username, (0, 0))
            self.failed_attempts[username] = (count + 1, now)
            return False

    def run(self):
        socket_path = self.config['socket_path']
        if os.path.exists(socket_path):
            os.remove(socket_path)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(socket_path)
        os.chmod(socket_path, 0o666)
        server.listen(1)

        print(f"Daemon listening on {socket_path}...")

        while True:
            conn, _ = server.accept()
            try:
                request = conn.recv(1024).decode().strip()
                if request.startswith("AUTH "):
                    username = request.split(" ", 1)[1]
                    
                    # Reload config on each auth attempt for live changes
                    new_config = load_config()
                    
                    # Hot-reload model if it changed in config
                    if new_config.get('model_name') != self.config.get('model_name'):
                        print(f"Model change detected: {new_config['model_name']}. Hot-reloading...")
                        self.app = FaceAnalysis(name=new_config['model_name'], providers=['CPUExecutionProvider'])
                        self.app.prepare(ctx_id=0, det_size=(320, 320))
                    
                    self.config = new_config
                    result = "SUCCESS" if self.verify(username) else "FAILURE"
                    conn.sendall(result.encode())
            except Exception as e:
                print(f"Error handling request: {e}")
            finally:
                conn.close()

if __name__ == "__main__":
    daemon = FaceDaemon()
    daemon.run()