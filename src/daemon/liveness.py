import cv2
import numpy as np
import time

class LBPLiveness:
    """
    Passive Liveness Detection using Local Binary Patterns (LBP).
    Optimized for high-speed (<100ms) execution on CPUs.
    Detects spoofing by analyzing skin texture consistency.
    """
    def __init__(self, threshold=0.7):
        self.threshold = threshold

    def _get_lbp_image(self, gray_img):
        """Calculates LBP image using 8 neighbors and radius 1."""
        rows, cols = gray_img.shape
        lbp = np.zeros((rows-2, cols-2), dtype=np.uint8)
        
        # Directions: 
        # (r-1, c-1), (r-1, c), (r-1, c+1)
        # (r, c-1),             (r, c+1)
        # (r+1, c-1), (r+1, c), (r+1, c+1)
        
        # We can optimize this with vectorization (shifts)
        for r in range(1, rows-1):
            for c in range(1, cols-1):
                center = gray_img[r, c]
                val = 0
                if gray_img[r-1, c-1] >= center: val |= 1
                if gray_img[r-1, c]   >= center: val |= 2
                if gray_img[r-1, c+1] >= center: val |= 4
                if gray_img[r, c+1]   >= center: val |= 8
                if gray_img[r+1, c+1] >= center: val |= 16
                if gray_img[r+1, c]   >= center: val |= 32
                if gray_img[r+1, c-1] >= center: val |= 64
                if gray_img[r, c-1]   >= center: val |= 128
                lbp[r-1, c-1] = val
        return lbp

    def _get_lbp_hist(self, lbp_img):
        """Calculates normalized histogram of LBP image."""
        hist, _ = np.histogram(lbp_img, bins=256, range=(0, 256))
        hist = hist.astype("float")
        hist /= (hist.sum() + 1e-7)
        return hist

    def analyze(self, frame, face_bbox):
        """
        Analyzes a face for liveness.
        - face_bbox: [x1, y1, x2, y2]
        Returns: Score (0.0 to 1.0), True if Likely Live
        """
        start_time = time.time()
        try:
            x1, y1, x2, y2 = map(int, face_bbox)
            # Crop face with a slight margin
            margin = int((x2 - x1) * 0.1)
            face_crop = frame[max(0, y1-margin):min(frame.shape[0], y2+margin), 
                             max(0, x1-margin):min(frame.shape[1], x2+margin)]
            
            if face_crop.size == 0:
                return 0.0, False

            # Convert to gray and resize for consistency
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (100, 100))

            # Calculate LBP histogram
            # Note: For extreme speed, we use a vectorized shift approach rather than nested loops
            img = gray.astype(np.int32)
            lbp = np.zeros((98, 98), dtype=np.uint8)
            
            # Vectorized LBP (Thresholding center vs 8 neighbors)
            center = img[1:-1, 1:-1]
            lbp |= (img[0:-2, 0:-2] >= center).astype(np.uint8) << 0
            lbp |= (img[0:-2, 1:-1] >= center).astype(np.uint8) << 1
            lbp |= (img[0:-2, 2:]   >= center).astype(np.uint8) << 2
            lbp |= (img[1:-1, 2:]   >= center).astype(np.uint8) << 3
            lbp |= (img[2:, 2:]     >= center).astype(np.uint8) << 4
            lbp |= (img[2:, 1:-1]   >= center).astype(np.uint8) << 5
            lbp |= (img[2:, 0:-2]   >= center).astype(np.uint8) << 6
            lbp |= (img[1:-1, 0:-2] >= center).astype(np.uint8) << 7

            hist, _ = np.histogram(lbp, bins=256, range=(0, 256))
            hist = hist.astype("float")
            hist /= (hist.sum() + 1e-7)

            # Heuristic: Real skin has lower "high-frequency" LBP patterns 
            # compared to printed dots or screen pixels.
            # Usually, uniform patterns (bins with few transitions) dominate real faces.
            # For this simplified model, we check for 'texture uniformity'.
            # A real face has a specific LBP energy profile.
            
            # Simple energy check: sum of squared bin values
            energy = np.sum(hist**2)
            
            # Normalize score (Live faces tend to have higher texture energy due to natural skin detail)
            # Spoofs (screens) often look 'too smooth' or 'too noisy' (aliasing)
            score = min(1.0, energy * 10.0) # Tune multiplier based on testing
            
            elapsed = (time.time() - start_time) * 1000
            # print(f"LBP Analysis: {elapsed:.2f}ms, Score: {score:.4f}")
            
            return score, score > self.threshold

        except Exception as e:
            print(f"Liveness Error: {e}")
            return 0.0, False
