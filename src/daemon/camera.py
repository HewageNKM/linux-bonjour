import cv2
import os

class Camera:
    def __init__(self):
        self.index, self.camera_type = self._find_camera()
        self.cap = None

    def _find_camera(self):
        # 1. Try to find an IR camera (priority)
        for i in [2, 4, 6, 0, 1, 3]: # Expanded list
            if os.path.exists(f"/dev/video{i}"):
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    ret, _ = cap.read()
                    cap.release()
                    if ret:
                        print(f"Detected camera at /dev/video{i}")
                        return i, "AUTO"
        return 0, "UNKNOWN"

    def get_frame(self):
        if self.cap is None or not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.index)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
            # Use MJPG if possible for speed
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

        ret, frame = self.cap.read()
        return frame if ret else None

    def release(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None

# Maintain alias for compatibility
IRCamera = Camera

if __name__ == "__main__":
    # Test if the red lights blink!
    cam = IRCamera()
    if cam.get_frame() is not None:
        print("IR Camera active and Emitters blinking!")