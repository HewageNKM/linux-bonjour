import os
import sys
import time
from insightface.app import FaceAnalysis

def init_models():
    models_dir = "/usr/share/linux-bonjour/models"
    if not os.path.exists(models_dir):
        os.makedirs(models_dir, exist_ok=True)
    
    print(f"Initializing AI models in {models_dir}...")
    
    # Default to small model for fastest installation
    models = ["buffalo_s"]
    
    for model_name in models:
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                print(f"Checking/Downloading {model_name} (Attempt {attempt+1}/{max_retries+1})...")
                # We use a short timeout for the download if possible, but InsightFace handles it
                app = FaceAnalysis(name=model_name, root=models_dir, providers=['CPUExecutionProvider'])
                app.prepare(ctx_id=0, det_size=(320, 320))
                print(f"✅ {model_name} ready.")
                break # Success
            except Exception as e:
                import traceback
                print(f"⚠️  Try {attempt+1} failed for {model_name}: {e}")
                traceback.print_exc()
                if attempt < max_retries:
                    time.sleep(2) # Wait before retry
                else:
                    print(f"❌ Failed to initialize {model_name} after {max_retries+1} attempts.")

if __name__ == "__main__":
    init_models()
