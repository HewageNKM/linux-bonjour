import os
import sys
from insightface.app import FaceAnalysis

def download_model(model_name="buffalo_s"):
    print(f"Checking for model: {model_name}...")
    try:
        # FaceAnalysis will automatically download the model if it doesn't exist
        app = FaceAnalysis(name=model_name, providers=['CPUExecutionProvider'])
        app.prepare(ctx_id=0, det_size=(320, 320))
        print(f"Model {model_name} is ready.")
    except Exception as e:
        print(f"Error downloading model {model_name}: {e}")

if __name__ == "__main__":
    model = "buffalo_s"
    if len(sys.argv) > 1:
        model = sys.argv[1]
    download_model(model)