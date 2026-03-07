import cv2
import os

class Camera:
    def __init__(self):
        self.index, self.camera_type = self._find_camera()

    def _find_camera(self):
        # 1. Try to find an IR camera (priority)
        # Often IR cameras are on even indices (/dev/video2, 4, 6)
        for i in [2, 4, 6]:
            if os.path.exists(f"/dev/video{i}"):
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    ret, _ = cap.read()
                    cap.release()
                    if ret:
                        print(f"Detected IR camera at /dev/video{i}")
                        return i, "IR"

        # 2. Fallback to any available camera (RGB)
        for i in [0, 1, 3, 5]:
            if os.path.exists(f"/dev/video{i}"):
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    ret, _ = cap.read()
                    cap.release()
                    if ret:
                        print(f"Falling back to RGB camera at /dev/video{i}")
                        return i, "RGB"

        return 0, "UNKNOWN"

    def get_frame(self):
        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            return None
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        
        ret, frame = cap.read()
        cap.release()
        return frame if ret else None

# Maintain alias for compatibility
IRCamera = Camera

if __name__ == "__main__":
    # Test if the red lights blink!
    cam = IRCamera()
    if cam.get_frame() is not None:
        print("IR Camera active and Emitters blinking!")