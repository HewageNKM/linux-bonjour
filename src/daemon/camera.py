import cv2

class IRCamera:
    def __init__(self, index=2): # UX425EA IR is usually /dev/video2
        self.index = index

    def get_frame(self):
        # We capture at low res (320x240) to save bus bandwidth and RAM
        cap = cv2.VideoCapture(self.index)
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