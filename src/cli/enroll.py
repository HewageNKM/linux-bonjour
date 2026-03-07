import numpy as np
import cv2
import sys
import os
from insightface.app import FaceAnalysis

# Add daemon path to import our Camera
sys.path.append(os.path.abspath("src"))
from daemon.camera import IRCamera

def enroll_owner():
    # Initialize the "Lite" app for 8GB RAM
    app = FaceAnalysis(name='buffalo_s', providers=['OpenVINOExecutionProvider', 'CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(320, 320))

    cam = IRCamera()
    print("Look at the IR camera...")
    frame = cam.get_frame()

    faces = app.get(frame)
    if faces:
        # Save the mathematical 'identity' of your face
        embedding = faces[0].normed_embedding
        np.save("config/owner.npy", embedding)
        print("Enrollment Complete! Your face is now a vector.")
    else:
        print("No face detected. Try adjusting the camera angle.")

if __name__ == "__main__":
    enroll_owner()