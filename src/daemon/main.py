import os
import socket
import numpy as np
import cv2
from insightface.app import FaceAnalysis
from camera import IRCamera  # Our utility from Phase 1

# --- Configuration ---
SOCKET_PATH = "/run/linux-hello.sock"
MODEL_NAME = "buffalo_s"  # 8GB RAM friendly
THRESHOLD = 0.45          # Cosine similarity score (0.4 - 0.5 is ideal for IR)

class FaceDaemon:
    def __init__(self):
        print("Initializing Face Recognition Engine...")
        # Load the AI once and keep it in RAM
        self.app = FaceAnalysis(name=MODEL_NAME, providers=['CPUExecutionProvider'])
        self.app.prepare(ctx_id=0, det_size=(320, 320))
        
        # Load your 'Database' (the npy file)
        self.owner_embedding = np.load("config/owner.npy")
        self.cam = IRCamera()

    def verify(self):
        frame = self.cam.get_frame()
        if frame is None:
            return False

        faces = self.app.get(frame)
        if not faces:
            return False

        # Math: Compare live face vector to stored owner.npy vector
        live_embedding = faces[0].normed_embedding
        score = np.dot(live_embedding, self.owner_embedding)
        
        print(f"Match Score: {score:.4f}")
        return score > THRESHOLD

    def run(self):
        # Clean up old socket if it exists
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

        # Create a Unix Socket (The 'API' for our PAM module)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o666) # Allow PAM (running as root) to talk to us
        server.listen(1)

        print(f"Daemon listening on {SOCKET_PATH}...")

        while True:
            conn, _ = server.accept()
            try:
                # When someone tries to sudo or login, PAM sends a 'ping'
                request = conn.recv(1024).decode()
                if request == "AUTH":
                    result = "SUCCESS" if self.verify() else "FAILURE"
                    conn.sendall(result.encode())
            finally:
                conn.close()

if __name__ == "__main__":
    daemon = FaceDaemon()
    daemon.run()