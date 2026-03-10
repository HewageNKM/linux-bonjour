import cv2
import threading
import time
import os

class Camera:
    _cached_index = None
    _cached_type = "AUTO"

    def __init__(self, config=None):
        self.config = config or {}
        if Camera._cached_index is not None:
            self.index = Camera._cached_index
            self.camera_type = Camera._cached_type
        else:
            self.index, self.camera_type = self._find_camera()
            Camera._cached_index = self.index
            Camera._cached_type = self.camera_type
            
        self.cap = None
        self.frame = None
        self.stopped = False
        self.lock = threading.Lock()
        self.thread = None

    def _find_camera(self):
        manual_index = self.config.get("camera_index")
        if manual_index is not None and manual_index != -1:
            return manual_index, self.config.get("camera_type", "AUTO")

        for i in [2, 4, 6, 0, 1, 3]:
            if os.path.exists(f"/dev/video{i}"):
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    ret, _ = cap.read()
                    cap.release()
                    if ret:
                        return i, "AUTO"
        return 0, "UNKNOWN"

    def start(self):
        """Starts the background thread for continuous frame polling."""
        if self.thread is not None and self.thread.is_alive():
            return
            
        self.stopped = False
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        """Internal thread loop to keep the latest frame in the buffer."""
        while not self.stopped:
            if self.cap is None or not self.cap.isOpened():
                self.cap = cv2.VideoCapture(self.index)
                if self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                else:
                    time.sleep(1.0)
                    continue

            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.1)

    def get_frame(self):
        """Returns the latest frame instantly from the buffer."""
        # Ensure thread is running
        if self.thread is None or not self.thread.is_alive():
            self.start()
            
        with self.lock:
            return self.frame

    def release(self):
        """Stops the thread and releases hardware."""
        self.stopped = True
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None

# Maintain alias for compatibility
IRCamera = Camera