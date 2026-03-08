import os
import socket
import numpy as np
import cv2
import time
import json
from insightface.app import FaceAnalysis
import io
from camera import IRCamera
from crypto_utils import encrypt_data, decrypt_data

# --- Configuration Loader ---
# Ensure we use absolute paths when running as a service
BASE_DIR = "/usr/share/linux-bonjour"
CONFIG_PATH = os.path.join(BASE_DIR, "config/config.json")

def load_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            conf = json.load(f)
            # Ensure users_dir is absolute
            if not conf['users_dir'].startswith('/'):
                conf['users_dir'] = os.path.join(BASE_DIR, conf['users_dir'])
            return conf
    except Exception as e:
        print(f"CRITICAL: Failed to load config from {CONFIG_PATH}: {e}")
        # Return sensible defaults if file missing
        return {
            "threshold": 0.45,
            "model_name": "buffalo_s",
            "users_dir": os.path.join(BASE_DIR, "config/users"),
            "socket_path": "/run/linux-bonjour.sock"
        }

# --- Logging Helper ---
LOG_FILE = "/usr/share/linux-bonjour/daemon.log"
def log_event(message):
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f"[{time.ctime()}] {message}\n")
    except: pass

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
            if count >= self.config.get('max_failures', 5) and (now - last_time) < self.config.get('cooldown_time', 60):
                log_event(f"AUTH FAILED: User {username} is throttled.")
                return False

        # 2. Collect Target Embeddings
        targets = [] # List of (label, embedding)
        
        if self.config.get("global_unlock", False):
            # Try ALL enrolled faces
            users_dir = self.config['users_dir']
            if os.path.exists(users_dir):
                for f in os.listdir(users_dir):
                    # Try encrypted first (.enc)
                    enc_file = os.path.join(users_dir, f)
                    if f.endswith(".enc"):
                        try:
                            with open(enc_file, 'rb') as ef:
                                decrypted = decrypt_data(ef.read())
                                emb = np.load(io.BytesIO(decrypted))
                                targets.append((f.replace(".enc", ""), emb))
                        except Exception as e:
                            log_event(f"ERROR: Failed to decrypt user data for '{f}': {e}")
                    elif f.endswith(".npy"):
                        # Automatic Migration: npy -> enc
                        try:
                            emb = np.load(os.path.join(users_dir, f))
                            # Save as encrypted
                            buffer = io.BytesIO()
                            np.save(buffer, emb)
                            encrypted = encrypt_data(buffer.getvalue())
                            with open(enc_file.replace(".npy", ".enc"), 'wb') as ef:
                                ef.write(encrypted)
                            # Add to targets
                            targets.append((f.replace(".npy", ""), emb))
                            log_event(f"MIGRATION: User '{f}' data encrypted and saved.")
                        except Exception as e:
                            log_event(f"ERROR: Failed to migrate user data for '{f}': {e}")
        else:
            # Traditional strict username matching
            user_file_enc = os.path.join(self.config['users_dir'], f"{username}.enc")
            user_file_npy = os.path.join(self.config['users_dir'], f"{username}.npy")
            
            if os.path.exists(user_file_enc):
                try:
                    with open(user_file_enc, 'rb') as ef:
                        decrypted = decrypt_data(ef.read())
                        emb = np.load(io.BytesIO(decrypted))
                        targets.append((username, emb))
                except Exception as e:
                    log_event(f"ERROR: Failed to decrypt user '{username}': {e}")
            elif os.path.exists(user_file_npy):
                try:
                    emb = np.load(user_file_npy)
                    targets.append((username, emb))
                    # Migration
                    buffer = io.BytesIO()
                    np.save(buffer, emb)
                    with open(user_file_enc, 'wb') as ef:
                        ef.write(encrypt_data(buffer.getvalue()))
                except: pass
        
        # Fallback to owner if no targets found yet
        if not targets and os.path.exists("config/owner.npy"):
            try:
                targets.append(("Owner", np.load("config/owner.npy")))
            except: pass

        if not targets:
            log_event(f"AUTH FAILED: No face data found for '{username}'.")
            print(f"No embedding found for user {username}")
            return False

        # 3. Capture Frame
        frame = self.cam.get_frame()
        if frame is None: return False

        faces = self.app.get(frame)
        if not faces:
            log_event(f"AUTH FAILED: No face detected for '{username}'")
            return False

        live_embedding = faces[0].normed_embedding
        
        # 4. Match against all candidates
        best_score = -1
        best_match = None
        
        for name, target_embedding in targets:
            score = np.dot(live_embedding, target_embedding)
            if score > best_score:
                best_score = score
                best_match = name
        
        print(f"Auth Request: {username}, Best Match: {best_match}, Score: {best_score:.4f}")
        
        if best_score > self.config['threshold']:
            log_event(f"AUTH SUCCESS: User '{username}' recognized as '{best_match}' (Score: {best_score:.4f})")
            self.failed_attempts[username] = (0, 0) # Reset on success
            return True
        else:
            log_event(f"AUTH FAILED: User '{username}' best match was '{best_match}' with score {best_score:.4f}")
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
                raw_request = conn.recv(1024).decode().strip()
                log_event(f"DEBUG: Received request: '{raw_request}'")
                if raw_request.startswith("AUTH "):
                    username = raw_request.split(" ", 1)[1]
                    
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