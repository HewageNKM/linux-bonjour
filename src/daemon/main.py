import os
import socket
import numpy as np
import cv2
import time
from insightface.app import FaceAnalysis
from camera import IRCamera

# --- Configuration ---
SOCKET_PATH = "/run/linux-hello.sock"
MODEL_NAME = "buffalo_s"
THRESHOLD = 0.45
USERS_DIR = "config/users"
FAILED_ATTEMPTS = {}
COOLDOWN_TIME = 60 # Seconds
MAX_FAILURES = 5

class FaceDaemon:
    def __init__(self):
        print("Initializing Face Recognition Engine...")
        self.app = FaceAnalysis(name=MODEL_NAME, providers=['CPUExecutionProvider'])
        self.app.prepare(ctx_id=0, det_size=(320, 320))
        self.cam = IRCamera()
        
        if not os.path.exists(USERS_DIR):
            os.makedirs(USERS_DIR)

    def verify(self, username):
        # 1. Check for Throttling
        now = time.time()
        if username in FAILED_ATTEMPTS:
            count, last_time = FAILED_ATTEMPTS[username]
            if count >= MAX_FAILURES and (now - last_time) < COOLDOWN_TIME:
                print(f"User {username} is throttled. Wait {int(COOLDOWN_TIME - (now - last_time))}s.")
                return False

        # 2. Load Embedding
        user_file = os.path.join(USERS_DIR, f"{username}.npy")
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
        
        if score > THRESHOLD:
            FAILED_ATTEMPTS[username] = (0, 0) # Reset on success
            return True
        else:
            # Increment failure count
            count, _ = FAILED_ATTEMPTS.get(username, (0, 0))
            FAILED_ATTEMPTS[username] = (count + 1, now)
            return False

    def run(self):
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o666)
        server.listen(1)

        print(f"Daemon listening on {SOCKET_PATH}...")

        while True:
            conn, _ = server.accept()
            try:
                request = conn.recv(1024).decode().strip()
                if request.startswith("AUTH "):
                    username = request.split(" ", 1)[1]
                    result = "SUCCESS" if self.verify(username) else "FAILURE"
                    conn.sendall(result.encode())
            except Exception as e:
                print(f"Error handling request: {e}")
            finally:
                conn.close()

if __name__ == "__main__":
    daemon = FaceDaemon()
    daemon.run()