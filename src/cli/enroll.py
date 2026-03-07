import numpy as np
import cv2
import sys
import os
from insightface.app import FaceAnalysis

# Add daemon path to import our Camera
sys.path.append(os.path.abspath("src"))
from daemon.camera import IRCamera

def enroll_user(username=None):
    if not username:
        username = input("Enter username to enroll: ").strip()
    
    if not username:
        print("Username cannot be empty.")
        return

    # Initialize the "Lite" app for 8GB RAM
    app = FaceAnalysis(name='buffalo_s', providers=['CPUExecutionProvider'])
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
        
        users_dir = "config/users"
        if not os.path.exists(users_dir):
            os.makedirs(users_dir)
            
        np.save(os.path.join(users_dir, f"{username}.npy"), embedding)
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