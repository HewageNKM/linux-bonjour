import psutil
import platform
import subprocess

def get_system_specs():
    specs = {
        "ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "cpu": platform.processor(),
        "gpu": "Unknown"
    }
    
    # Try to find GPU info
    try:
        gpu_info = subprocess.check_output(["lspci"], stderr=subprocess.STDOUT).decode()
        if "VGA compatible controller" in gpu_info:
            for line in gpu_info.split("\n"):
                if "VGA" in line or "3D controller" in line:
                    specs["gpu"] = line.split(": ")[-1]
                    break
    except:
        pass
        
    return specs

def suggest_model(specs):
    if specs["ram_gb"] < 8:
        return "buffalo_s", "Lightweight model (Recommended for < 8GB RAM)"
    else:
        return "buffalo_l", "High-accuracy model (Recommended for 8GB+ RAM)"

if __name__ == "__main__":
    specs = get_system_specs()
    model, reason = suggest_model(specs)
    print(f"System Specs: {specs}")
    print(f"Suggested Model: {model} ({reason})")
