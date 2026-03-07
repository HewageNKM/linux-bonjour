import os
from insightface.app import FaceAnalysis

def download_models():
    print("Initializing InsightFace model downloader...")
    
    # This call automatically checks if models exist. 
    # If not, it downloads them from the official InsightFace mirror.
    # 'buffalo_s' is the lightweight model set optimized for 8GB RAM.
    app = FaceAnalysis(name='buffalo_s', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0)
    
    print("\nSuccess! Models have been downloaded to ~/.insightface/models/buffalo_s/")
    print("Your project is ready to go.")

if __name__ == "__main__":
    download_models()