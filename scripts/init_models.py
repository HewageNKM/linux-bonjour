import os
import sys
import time
from insightface.app import FaceAnalysis

def init_models(target_dir=None):
    if target_dir:
        models_dir = target_dir
        requested_models = []
    else:
        # Check if first arg is a directory, otherwise default models_dir
        if len(sys.argv) > 1 and (os.path.sep in sys.argv[1] or sys.argv[1].startswith('.')):
            models_dir = sys.argv[1]
            requested_models = sys.argv[2:]
        else:
            models_dir = "/usr/share/linux-bonjour/models"
            requested_models = sys.argv[1:]
    
    if not os.path.exists(models_dir):
        os.makedirs(models_dir, exist_ok=True)
    
    print(f"Initializing AI models in {models_dir}...")
    
    # Models to initialize
    if requested_models:
        models = requested_models
    else:
        # Default models (essential for first run)
        models = ["buffalo_s"]
    
    for model_name in models:
        # Optimization: Quick check if model is already present
        model_ready_marker = os.path.join(models_dir, "models", model_name, "det_500m.onnx")
        if os.path.exists(model_ready_marker):
            print(f"✨ {model_name} already exists. Skipping.")
            continue

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                print(f"Checking/Downloading {model_name} (Attempt {attempt+1}/{max_retries+1})...")
                app = FaceAnalysis(name=model_name, root=models_dir, providers=['CPUExecutionProvider'])
                app.prepare(ctx_id=0, det_size=(320, 320))
                print(f"✅ {model_name} ready.")
                break
            except Exception as e:
                import traceback
                print(f"⚠️  Try {attempt+1} failed for {model_name}: {e}")
                if attempt < max_retries:
                    time.sleep(2)
                else:
                    print(f"❌ Failed to initialize {model_name}.")

if __name__ == "__main__":
    init_models()