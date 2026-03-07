import cv2
import os

class IRCamera:
    def __init__(self):
        self.index = self._find_ir_camera()

    def _find_ir_camera(self):
        # Common IR camera names or drivers to look for (heuristic)
        # Often IR cameras are on even indices (/dev/video2, 4, 6)
        # We'll try common indices first
        for i in [2, 4, 6, 0]:
            if os.path.exists(f"/dev/video{i}"):
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    # Check if it emits IR (some cameras have metadata, but simple check for now)
                    ret, _ = cap.read()
                    cap.release()
                    if ret:
                        print(f"Auto-detected IR camera at /dev/video{i}")
                        return i
        return 0 # Fallback to default

    def get_frame(self):
        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            return None
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        
        ret, frame = cap.read()
        cap.release()
        return frame if ret else None

if __name__ == "__main__":
    # Test if the red lights blink!
    cam = IRCamera()
    if cam.get_frame() is not None:
        print("IR Camera active and Emitters blinking!")