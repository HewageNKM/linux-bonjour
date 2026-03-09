import os
import sys
import time
from insightface.app import FaceAnalysis

def init_models(target_dir=None):
    if target_dir:
        models_dir = target_dir
    elif len(sys.argv) > 1:
        models_dir = sys.argv[1]
    else:
        models_dir = "/usr/share/linux-bonjour/models"
    
    if not os.path.exists(models_dir):
        os.makedirs(models_dir, exist_ok=True)
    
    print(f"Initializing AI models in {models_dir}...")
    
    # Default to small model for fastest installation
    # Package all confirmed working models for v0.7
    models = ["buffalo_sc", "buffalo_s", "buffalo_l", "antelopev2"]
    
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
                # Handle nested directory structure common in some models (e.g. antelopev2)
                import shutil
                model_base = os.path.join(models_dir, "models", model_name)
                nested_path = os.path.join(model_base, model_name)
                if os.path.exists(nested_path) and os.path.isdir(nested_path):
                    print(f"🔧 Fixing nested directory structure for {model_name}...")
                    for item in os.listdir(nested_path):
                        shutil.move(os.path.join(nested_path, item), os.path.join(model_base, item))
                    os.rmdir(nested_path)
                    # Retry immediately if we fixed it
                    try:
                        app = FaceAnalysis(name=model_name, root=models_dir, providers=['CPUExecutionProvider'])
                        app.prepare(ctx_id=0, det_size=(320, 320))
                        print(f"✅ {model_name} ready (after fix).")
                        break
                    except: pass

                import traceback
                print(f"⚠️  Try {attempt+1} failed for {model_name}: {e}")
                traceback.print_exc()
                if attempt < max_retries:
                    time.sleep(2) # Wait before retry
                else:
                    print(f"❌ Failed to initialize {model_name} after {max_retries+1} attempts.")

if __name__ == "__main__":
    init_models()
