import cv2
import threading
import time
import os
import queue

class Camera:
    _cached_index = None
    _cached_type = "AUTO"

    def __init__(self, config=None):
        self.config = config or {}
        self.cap = None
        if Camera._cached_index is not None:
            self.index = Camera._cached_index
            self.camera_type = Camera._cached_type
        else:
            self.index, self.camera_type, self.cap = self._find_camera()
            Camera._cached_index = self.index
            Camera._cached_type = self.camera_type
            
        self.stopped = False
        self.thread = None
        # Use a Queue with maxsize=1 to ensure we always have the freshest frame
        # and minimize latency (old frames are dropped if new ones arrive).
        self.frame_queue = queue.Queue(maxsize=1)

    def _find_camera(self):
        """Discovers the best camera, prioritizing IR sensors."""
        manual_index = self.config.get("camera_index")
        if manual_index is not None and manual_index != -1:
            return manual_index, self.config.get("camera_type", "AUTO"), None

        # Step 1: Probe for hardware-labeled IR cameras in /sys
        ir_candidates = []
        rgb_candidates = []
        
        try:
            v4l_dir = "/sys/class/video4linux"
            if os.path.exists(v4l_dir):
                for dev in sorted(os.listdir(v4l_dir)):
                    index = int(dev.replace("video", ""))
                    name_path = os.path.join(v4l_dir, dev, "name")
                    if os.path.exists(name_path):
                        with open(name_path, "r") as f:
                            name = f.read().lower()
                            if "ir" in name or "infrared" in name or "depth" in name:
                                ir_candidates.append(index)
                            else:
                                rgb_candidates.append(index)
        except Exception as e:
            print(f"Camera Probe Error: {e}")

        # Step 2: Try candidates and keep the first successful handle
        for index in ir_candidates + rgb_candidates + [0, 1, 2, 4, 6]:
            cap = self._open_device(index)
            if cap:
                ctype = "IR" if index in ir_candidates else "RGB"
                print(f"✅ Camera Found: /dev/video{index} ({ctype})")
                return index, ctype, cap

        return 0, "UNKNOWN", None

    def _open_device(self, index):
        """Attempt to open a camera device and verify it works."""
        try:
            if not os.path.exists(f"/dev/video{index}"):
                return None
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    return cap
                cap.release()
        except:
            pass
        return None

    def start(self):
        """Starts the background thread for continuous frame polling."""
        if self.thread is not None and self.thread.is_alive():
            return
            
        self.stopped = False
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        """Internal thread loop (Producer) to keep the latest frame in the queue."""
        while not self.stopped:
            if self.cap is None or not self.cap.isOpened():
                # Redundant check because we might have closed it in release()
                self.cap = cv2.VideoCapture(self.index)
                
            if self.cap.isOpened():
                # Apply settings only once or when re-opened
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            else:
                time.sleep(1.0)
                continue

            ret, frame = self.cap.read()
            if ret:
                # Clear queue if full to ensure freshness (LIFO behavior)
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                self.frame_queue.put(frame)
            else:
                time.sleep(0.1)

    def get_frame(self):
        """Returns the latest frame (Consumer). Returns None if queue is empty."""
        # Ensure thread is running
        if self.thread is None or not self.thread.is_alive():
            self.start()
            
        try:
            # Non-blocking get to avoid stalling the caller
            return self.frame_queue.get_nowait()
        except queue.Empty:
            return None

    def release(self):
        """Stops the thread and releases hardware."""
        self.stopped = True
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None
        # Clear the queue
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

# Maintain alias for compatibility
IRCamera = Camera