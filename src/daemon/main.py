import os
import socket
import numpy as np
import cv2
import time
import json
import subprocess
import pwd
import glob
from insightface.app import FaceAnalysis
import io
from camera import IRCamera
from crypto_utils import encrypt_data, decrypt_data
import logging
from datetime import datetime
import threading
from threading import Lock, Event
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
# Robust import for DBusManager (handles standalone vs module execution)
try:
    from dbus_service import DBusManager
    from liveness import LBPLiveness
except ImportError:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from dbus_service import DBusManager
    from liveness import LBPLiveness

# --- Global Config ---
LOGIN_SERVICES = ["gdm-password", "lightdm", "sddm", "login", "polkit-1"]

# --- Configuration Loader ---
# Ensure we use absolute paths when running as a service
BASE_DIR = "/usr/share/linux-bonjour"
CONFIG_PATH = os.path.join(BASE_DIR, "config/config.json")

def load_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            conf = json.load(f)
            # Ensure users_dir is absolute and points to the model-wise subdirectory
            model_name = str(conf.get('model_name', 'buffalo_l'))
            # Strip _int8 for directory naming consistency (Phase 26)
            model_base = model_name.replace("_int8", "")
            
            if not conf['users_dir'].startswith('/'):
                conf['users_dir'] = os.path.join(BASE_DIR, conf['users_dir'], model_base)
            else:
                conf['users_dir'] = os.path.join(conf['users_dir'], model_base)
            return conf
    except Exception as e:
        print(f"CRITICAL: Failed to load config from {CONFIG_PATH}: {e}")
        # Return sensible defaults if file missing
        return {
            "threshold": 0.45,
            "model_name": "buffalo_l",
            "users_dir": os.path.join(BASE_DIR, "config/users/buffalo_l"),
            "socket_path": "/run/linux-bonjour.sock",
            "liveness_required": False,
            "ear_threshold": 0.20
        }

# --- Secure Logging (Phase 6) ---
LOG_FILE = "/usr/share/linux-bonjour/daemon.log"
SIGNING_KEY = "/usr/share/linux-bonjour/logging.key"

class SecureLogger:
    def __init__(self, log_path, key_path):
        self.log_path = log_path
        self.key_path = key_path
        self._ensure_keys()

    def _ensure_keys(self):
        try:
            if not os.path.exists(os.path.dirname(self.key_path)):
                os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
            if not os.path.exists(self.key_path):
                private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                with open(self.key_path, "wb") as f:
                    f.write(private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption()
                    ))
                os.chmod(self.key_path, 0o600)
        except Exception as e:
            print(f"logger initialization failed: {e}")

    def log(self, message, enabled=True):
        if not enabled: return
        timestamp = time.ctime()
        entry = f"[{timestamp}] {message}"
        try:
            with open(self.key_path, "rb") as f:
                private_key = serialization.load_pem_private_key(f.read(), password=None)
            
            signature = private_key.sign(
                entry.encode(),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256()
            )
            
            with open(self.log_path, 'a') as f:
                f.write(entry + "\n")
                f.write(f"SIG:{signature.hex()}\n")
        except:
            try:
                with open(self.log_path, 'a') as f:
                    f.write(entry + " (UNSIGNED)\n")
            except: pass

logger = SecureLogger(LOG_FILE, SIGNING_KEY)

def log_event(message, enabled=True):
    logger.log(message, enabled)

def get_current_ssid():
    """Returns the current Wi-Fi SSID using nmcli."""
    try:
        res = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], capture_output=True, text=True)
        for line in res.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
    except:
        pass
    return None

class PresenceDetector(threading.Thread):
    """Background thread that monitors user presence and locks the screen."""
    def __init__(self, daemon):
        super().__init__(daemon=True)
        self.daemon_ref = daemon
        self.last_presence = time.time()
        self.running = True

    def run(self):
        while self.running:
            config = self.daemon_ref.config
            if not config.get("auto_lock_enabled", False):
                time.sleep(10)
                continue

            # Adaptive presence scan rate (Nitro Power Optimization)
            on_bat = False
            perc = 100
            try:
                on_bat, perc = self.daemon_ref.get_battery_status()
            except:
                pass
                
            if on_bat:
                sleep_time = 10 if perc < 20 else 7
            else:
                sleep_time = 5
            
            time.sleep(sleep_time)
            
            # Don't scan if an active AUTH is happening (prevents race/flicker)
            if self.daemon_ref.auth_in_progress:
                self.last_presence = time.time() # Reset presence if user is currently authenticating
                continue

            with self.daemon_ref.cam_lock:
                frame = self.daemon_ref.cam.get_frame()
                if frame is not None:
                    faces = self.daemon_ref.app.get(frame)
                    self.daemon_ref.cam.release()
                    
                    if faces:
                        self.last_presence = time.time()
                        # log_event("DEBUG: Presence detected")
                    else:
                        elapsed = time.time() - self.last_presence
                        timeout = float(config.get("auto_lock_timeout", 30))
                        if elapsed > timeout:
                            log_event(f"SECURITY: No presence detected for {int(elapsed)}s. Locking session.")
                            try:
                                subprocess.run(["loginctl", "lock-sessions"], check=False)
                                self.last_presence = time.time() # Reset after locking
                            except Exception as e:
                                log_event(f"ERROR: Failed to lock session: {e}")
                        
                        # Phase 6: Face-to-Lock (Immediate)
                        elif config.get("face_to_lock_immediate", False) and elapsed > 2.0:
                            log_event("SECURITY: Face disappeared. Immediate lock triggered.")
                            subprocess.run(["loginctl", "lock-sessions"], check=False)
                            self.last_presence = time.time()

class FaceDaemon:
    def __init__(self):
        # Load Config
        self.config = load_config()
        self.app = None # Explicitly initialize for static analysis
        
        # Initialize state
        self.failed_attempts = {} # username -> (count, timestamp)
        self.last_success = {}   # username -> timestamp
        self.last_denial = {}    # username -> (timestamp, service)
        self.match_cache = {}    # username -> (embedding, label)
        self.blink_state = {}    # username -> (blink_count, is_closed)
        self.auth_in_progress = False
        self.is_scanning = False
        self.cam_lock = Lock()
        self._last_pam_info = 0.0
        
        # Phase 9: Global Signaling
        self.dbus = DBusManager()
        self.dbus.start()
        
        # Approval Tracking
        self.auth_event = Event()
        self.auth_approved = False
        
        # Load Engine (Nitro Threaded Initialization)
        self.app_ready = Event()
        self.init_thread = threading.Thread(target=self._load_ai_engine, daemon=True)
        self.init_thread.start()

        # Initialize camera
        self.cam = IRCamera(config=self.config)
        self.cam_lock = Lock()
        self.liveness = LBPLiveness()
        self.users_dir = "" # Will be set in reload_config
        self.reload_config()
        # Startup Directory Verification
        users_dir = self.config.get('users_dir', 'config/users')
        if not os.path.exists(str(users_dir)):
            os.makedirs(str(users_dir), mode=0o777, exist_ok=True)
            os.chmod(str(users_dir), 0o777)

        # Start Presence Detector
        self.presence_detector = PresenceDetector(self)
        self.presence_detector.start()

    def _load_ai_engine(self):
        """Initializes AI Engine with OpenVINO priority and intelligent hardware fallback."""
        model_name = str(self.config.get('model_name', 'buffalo_l'))
        models_dir = os.path.join(BASE_DIR, "models")
        cache_dir = "/var/cache/linux-bonjour"
        
        # Phase 28: Model Caching (OpenVINO)
        # We use environment variables because insightface 
        # doesn't directly expose provider_options in FaceAnalysis constructor
        os.environ["OV_CACHE_DIR"] = cache_dir
        os.environ["OV_CONFIG"] = '{"CACHE_DIR":"'+cache_dir+'"}'
        
        # Priority: OpenVINO (Intel) -> MIGraphX (AMD) -> ROCM (AMD) -> TensorRT (NVIDIA) -> CUDA (NVIDIA)
        accelerated_providers = [
            'OpenVINOExecutionProvider',
            'MIGraphXExecutionProvider',
            'ROCMExecutionProvider',
            'TensorrtExecutionProvider', 
            'CUDAExecutionProvider',
        ]
        print(f"Initializing Optimized AI Engine: {model_name}...")
        
        # Step 1: Attempt to find optimized INT8 models (Phase 14)
        # We prefer _int8 models if they exist in the models directory
        int8_model_path = os.path.join(models_dir, "models", f"{model_name}_int8")
        if os.path.exists(int8_model_path):
            print(f"🚀 Quantized INT8 model detected for {model_name}. Prioritizing OpenVINO.")
            model_name = f"{model_name}_int8"
        # Try accelerated providers
        for provider in accelerated_providers:
            try:
                print(f"Trying hardware acceleration: {provider}...")
                self.app = FaceAnalysis(name=model_name, root=models_dir, providers=[provider])
                self.app.prepare(ctx_id=0, det_size=(320, 320))
                
                # Verify that the provider was actually assigned
                if self.app is not None and hasattr(self.app, 'models') and 'detection' in self.app.models:
                    model = self.app.models['detection']
                    if hasattr(model, 'session'):
                        assigned_providers = model.session.get_providers()
                        if provider in assigned_providers:
                            print(f"✅ Success! Accelerated by {provider}")
                            self.app_ready.set()
                            return
            except Exception as e:
                print(f"Provider {provider} failed: {e}")

        # Fallback to CPU
        print("Falling back to CPUExecutionProvider...")
        self.app = FaceAnalysis(name=model_name, root=models_dir, providers=['CPUExecutionProvider'])
        self.app.prepare(ctx_id=0, det_size=(320, 320))
        self.app_ready.set()

    def _ensure_ai_ready(self, timeout=15):
        """Blocks until AI engine is loaded (used for on-demand auth)."""
        if not self.app_ready.is_set():
            print("⏳ Waiting for AI Engine to initialize...")
            self.app_ready.wait(timeout=timeout)
        return self.app is not None

    def reload_config(self):
        """Reloads configuration and triggers engine swat if model changed."""
        old_model = self.config.get('model_name')
        self.config = load_config()
        if self.config.get('model_name') != old_model:
            log_event(f"CONFIG: Model changed to {self.config.get('model_name')}. Swapping engine...")
            with self.cam_lock: # Ensure no concurrent inference
                self._load_ai_engine()
                self.match_cache.clear() # Cache is invalid for new model

    def get_targets(self, username):
        # 1. Check for Throttling
        now = time.time()
        if username in self.failed_attempts:
            count, last_time = self.failed_attempts[username]
            max_fail = int(self.config.get('max_failures', 5))
            cooldown = float(self.config.get('cooldown_time', 60))
            if count >= max_fail and (now - last_time) < cooldown:
                log_event(f"AUTH FAILED: User '{username}' is throttled.", enabled=self.config.get('logging_enabled', True))
                # Return empty list instead of False to avoid "No face data found" misleading log
                return [] 

        # 2. Collect Target Embeddings
        targets = [] # List of (label, embedding)
        
        # New: Search Locations
        search_dirs = [self.config['users_dir']]
        # Strip _int8 for local user dir as well
        model_name = str(self.config.get('model_name', 'buffalo_l'))
        model_base = model_name.replace("_int8", "")
        # Safe string conversion for path functions
        u_dir = str(self.config.get("users_dir", "config/users"))
        # In service mode, we use BASE_DIR as the root
        self.users_dir = os.path.join(BASE_DIR, u_dir, model_base)
        try:
            pw = pwd.getpwnam(username)
            user_local_dir = os.path.join(pw.pw_dir, ".linux-bonjour", "users", model_base)
            search_dirs.insert(0, user_local_dir)
        except Exception: pass

        if self.config.get("global_unlock", False):
            # Try ALL enrolled faces in ALL search locations
            for users_dir in search_dirs:
                if not os.path.exists(users_dir): continue
                for f in os.listdir(users_dir):
                    # Try encrypted first (.enc)
                    enc_file = os.path.join(users_dir, f)
                    if f.endswith(".enc"):
                        try:
                            with open(enc_file, 'rb') as ef:
                                decrypted = decrypt_data(ef.read())
                                emb = np.load(io.BytesIO(decrypted))
                                targets.append((f.replace(".enc", ""), emb))
                        except Exception as e:
                            log_event(f"ERROR: Failed to decrypt user data for '{f}': {e}")
                    elif f.endswith(".npy"):
                        # Automatic Migration: npy -> enc
                        try:
                            emb = np.load(os.path.join(users_dir, f))
                            # Save as encrypted (if we have permission, usually true for user homes)
                            buffer = io.BytesIO()
                            np.save(buffer, emb)
                            encrypted = encrypt_data(buffer.getvalue())
                            with open(enc_file.replace(".npy", ".enc"), 'wb') as ef:
                                ef.write(encrypted)
                            # Add to targets
                            targets.append((f.replace(".npy", ""), emb))
                            log_event(f"MIGRATION: User '{f}' data encrypted and saved.")
                        except Exception as e:
                            log_event(f"ERROR: Failed to migrate user data for '{f}': {e}")
        else:
            # Traditional strict username matching
            for users_dir in search_dirs:
                user_file_enc = os.path.join(users_dir, f"{username}.enc")
                user_file_npy = os.path.join(users_dir, f"{username}.npy")
                
                if os.path.exists(user_file_enc):
                    try:
                        with open(user_file_enc, 'rb') as ef:
                            decrypted = decrypt_data(ef.read())
                            emb = np.load(io.BytesIO(decrypted))
                            targets.append((username, emb))
                            break # Found it
                    except Exception as e:
                        log_event(f"ERROR: Failed to decrypt user '{username}': {e}")
                elif os.path.exists(user_file_npy):
                    try:
                        emb = np.load(user_file_npy)
                        targets.append((username, emb))
                        # Migration to encrypted format
                        buffer = io.BytesIO()
                        np.save(buffer, emb)
                        with open(user_file_enc, 'wb') as ef:
                            ef.write(encrypt_data(buffer.getvalue()))
                        break # Found it
                    except: pass
        return targets

    def calculate_ear(self, landmarks):
        """Calculates Eye Aspect Ratio (EAR) using 3D-68 facial landmarks."""
        try:
            def eye_ear(eye_pts):
                v1 = np.linalg.norm(eye_pts[1] - eye_pts[5])
                v2 = np.linalg.norm(eye_pts[2] - eye_pts[4])
                h = np.linalg.norm(eye_pts[0] - eye_pts[3])
                return (v1 + v2) / (2.0 * h)

            left_ear = eye_ear(landmarks[36:42])
            right_ear = eye_ear(landmarks[42:48])
            return left_ear, right_ear
        except:
            return 1.0, 1.0

    def calculate_head_tilt(self, landmarks):
        """Calculates head tilt (roll) using eye centers."""
        try:
            left_eye_center = np.mean(landmarks[36:42], axis=0)
            right_eye_center = np.mean(landmarks[42:48], axis=0)
            dy = right_eye_center[1] - left_eye_center[1]
            dx = right_eye_center[0] - left_eye_center[0]
            angle = np.degrees(np.arctan2(dy, dx))
            return angle # Negative = tilt left, Positive = tilt right
        except:
            return 0.0

    def calculate_mar(self, landmarks):
        """Calculates Mouth Aspect Ratio (MAR) for smile/speech detection."""
        try:
            # Using landmark indices for inner/outer lip
            # 60-67 are inner lip points in 68-point model
            d_v = np.linalg.norm(landmarks[62] - landmarks[66])
            d_h = np.linalg.norm(landmarks[60] - landmarks[64])
            return d_v / d_h
        except:
            return 0.0

    def calculate_smile_score(self, landmarks):
        """Calculates smile score based on mouth corner elevation."""
        try:
            # 48, 54 are mouth corners
            # 51 is top of lip, 57 is bottom
            # 33 is nose tip (stable reference)
            corner_avg_y = (landmarks[48][1] + landmarks[54][1]) / 2.0
            nose_y = landmarks[33][1]
            relative_elevation = (nose_y - corner_avg_y)
            return relative_elevation
        except:
            return 0.0

    def get_battery_status(self):
        """Checks if the system is on battery and its percentage."""
        try:
            # Quick check for primary battery
            res = subprocess.run(["upower", "-i", "/org/freedesktop/UPower/devices/battery_BAT0"], 
                                 capture_output=True, text=True, timeout=1)
            on_battery = "state:               discharging" in res.stdout
            percentage = 100
            for line in res.stdout.splitlines():
                if "percentage:" in line:
                    percentage = int(line.split(":")[1].strip().replace("%", ""))
                    break
            return on_battery, percentage
        except:
            return False, 100
    
    def get_desktop_env(self, username):
        """Discovers necessary environment variables for the user's desktop."""
        env = os.environ.copy()
        try:
            user_info = pwd.getpwnam(username)
            uid = user_info.pw_uid
            user_home = user_info.pw_dir
            
            env["USER"] = username
            env["HOME"] = user_home
            env["UID"] = str(uid)
            env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
            
            # 1. Find XAUTHORITY (especially for Wayland/Mutter/XWayland)
            mutter_auths = glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth.*")
            if mutter_auths:
                env["XAUTHORITY"] = mutter_auths[0]
            else:
                xauth = os.path.join(user_home, ".Xauthority")
                if os.path.exists(xauth):
                    env["XAUTHORITY"] = xauth

            # 2. Find WAYLAND_DISPLAY
            wayland_displays = glob.glob(f"/run/user/{uid}/wayland-*")
            if wayland_displays:
                env["WAYLAND_DISPLAY"] = os.path.basename(wayland_displays[0])
            elif not env.get("WAYLAND_DISPLAY"):
                env["WAYLAND_DISPLAY"] = "wayland-0"

            if not env.get("DISPLAY"): env["DISPLAY"] = ":0"
            if not env.get("DBUS_SESSION_BUS_ADDRESS"): env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
            
            log_event(f"DEBUG: Found desktop env for {username}: DISPLAY={env.get('DISPLAY')}, XAUTH={env.get('XAUTHORITY')}, WAYLAND={env.get('WAYLAND_DISPLAY')}")
            return env, uid
        except Exception as e:
            log_event(f"ERROR: Failed to discover desktop env for {username}: {e}")
            return env, os.getuid()

    def _run_zenity_approval(self, username, service):
        """Launches a Zenity question dialog for the user to approve the scan."""
        env_vars, uid = self.get_desktop_env(username)
        
        # Build the command precisely to run in the user's session using sudo
        cmd = [
            "sudo", "-u", username,
            "env",
            f"DISPLAY={env_vars.get('DISPLAY', ':0')}",
            f"XAUTHORITY={env_vars.get('XAUTHORITY', '')}",
            f"WAYLAND_DISPLAY={env_vars.get('WAYLAND_DISPLAY', 'wayland-0')}",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            "zenity", "--question",
            "--title=Linux Bonjour Authorization",
            f"--text=Authorize Face ID scan for service: {service}?\n\n(Required for security to prevent ghost scans)",
            "--ok-label=Verify",
            "--cancel-label=Cancel",
            "--timeout=15",
            "--icon-name=camera-web-symbolic"
        ]
        
        try:
            log_event(f"ZENITY EXEC: {' '.join(cmd)}")
            res = subprocess.run(cmd, capture_output=True, text=True, env=env_vars, timeout=20)
            if res.returncode == 0:
                log_event(f"ZENITY SUCCESS: User approved Face ID for {service}")
                return True
            else:
                log_event(f"ZENITY FAILURE: RC={res.returncode}, STDOUT={res.stdout.strip()}, STDERR={res.stderr.strip()}")
                return False
        except Exception as e:
            log_event(f"ZENITY EXCEPTION: {e}")
            return False

    def _on_auth_response(self, username, approved):
        log_event(f"DBUS: User interaction response for {username}: {approved}")
        self.auth_approved = approved
        self.auth_event.set()

    def verify(self, username, conn, service="unknown"):
        self.is_scanning = True
        try:
            return self._verify_impl(username, conn, service)
        finally:
            self.is_scanning = False

    def _verify_impl(self, username, conn, service="unknown"):
        self.config = load_config()  # Ensure settings from GUI take immediate effect
        
        current_ssid = str(get_current_ssid() or "")
        temp_ssids = self.config.get("safe_ssids", [])
        if not isinstance(temp_ssids, list):
            temp_ssids = []
        safe_ssids = [str(s) for s in temp_ssids]
        is_safe_zone = (current_ssid in safe_ssids) if current_ssid else False
        
        base_threshold = float(self.config.get("threshold", 0.55))
        if is_safe_zone:
            # Drop threshold by 10% in safe zones for convenience
            active_threshold = max(0.40, base_threshold - 0.10)
            log_event(f"CONTEXT: Safe Zone detected ({current_ssid}). Lowering threshold to {active_threshold:.2f}")
        else:
            active_threshold = base_threshold
        
        # 0. Check Grace Period
        now = time.time()
        grace_period = float(load_config().get("grace_period", 0)) # Fresh reload
        if grace_period > 0 and username in self.last_success:
            if (now - self.last_success[username]) < grace_period:
                log_event(f"AUTH BYPASS: User '{username}' authenticated via grace period.")
                if self.config.get("pam_logging", True):
                    try: conn.sendall(b"INFO: Recently verified! Bypassing scan... \n")
                    except: pass
                self.dbus.emit_verified(username)
                return "SUCCESS"

        # 0.1 Manual User Approval (Zenity Fallback + D-Bus)
        # Skip popup for services that already have a GUI (GDM, Polkit, etc.)
        gui_services = [
            "polkit-1", "gnome-screensaver", "lightdm", "sddm", "xscreensaver", 
            "mate-screensaver", "kcheckpass", "gnome-shell", "system-auth", 
            "kscreensaver", "gnome-initial-setup", "unity-greeter"
        ]
        skip_popup = service in gui_services or service.startswith("gdm-")
        if self.config.get("auth_approval", True) and not skip_popup:
            log_event(f"AUTH: Requesting user approval for {username} on {service}")
            
            # Send info to terminal
            if self.config.get("pam_logging", True):
                try: conn.sendall(f"INFO: 🛡️ Please Approve Face ID in the authorization popup...\n".encode())
                except: pass

            # 1. Emit D-Bus signal (for extension if it works)
            self.auth_event.clear()
            self.auth_approved = False
            if self.config.get("notifications_enabled", True):
                self.dbus.emit_auth_requested(username, service)
            
            # 2. Run Zenity (Legacy reliable way)
            # This is blocking, but that's what we want for authorization
            zenity_approved = self._run_zenity_approval(username, service)
            
            if not zenity_approved:
                # Check if D-Bus responded in the meantime (just in case)
                if self.auth_event.is_set() and self.auth_approved:
                    log_event("AUTH: Zenity failed/timeout but D-Bus approved.")
                else:
                    log_event(f"AUTH DENIED: User rejected or Zenity failed for {username}")
                    return "DENIED"
            else:
                self.auth_approved = True
                self.auth_event.set()

        # 0.2 Start Feedback
        if self.config.get("notifications_enabled", True):
            self.dbus.emit_scanning(username)

        # 0.1 Check Denial Grace Period (Prevent prompt looping on Deny)
        if username in self.last_denial:
            deny_time, deny_svc = self.last_denial[username]
            if (now - deny_time) < 10 and deny_svc == service:
                log_event(f"AUTH DENIED: Reusing recent denial for {username} on {service}")
                return "DENIED"

        targets = self.get_targets(username)
        if not targets:
            print("No Face Data!")
            # Only log if NOT throttled (throttling already logs its own message)
            if username not in self.failed_attempts or \
               (time.time() - self.failed_attempts[username][1]) >= self.config.get('cooldown_time', 60) or \
               self.failed_attempts[username][0] < self.config.get('max_failures', 5):
                log_event(f"AUTH FAILED: No face data found for '{username}'.", 
                          enabled=self.config.get('logging_enabled', True))
            return "FAILURE"

        # 1. Capture & Verify Loop (Retry for search_duration seconds)
        start_verify = time.time()
        max_duration = float(self.config.get("search_duration", 3.5))
        attempt = 0
        consecutive_cam_fails = 0
        
        # Non-blocking check for connection status
        conn.setblocking(False)
        
        # Ensure AI is ready (Nitro deferment)
        if not self._ensure_ai_ready():
            log_event("AUTH ERROR: AI Engine failed to initialize in time.")
            return "FAILURE"

        match_found = False # Flag to track if a match was found
        overall_best_score = -1 # For debugging on timeout

        while (time.time() - start_verify) < max_duration:
            now_loop = time.time()
            # Throttled instruction signaling (Every 1.5s)
            if not hasattr(self, '_last_pam_info'): self._last_pam_info = 0
            if (now_loop - self._last_pam_info) > 1.5:
                required_gesture = self.config.get("secret_gesture", "none")
                if self.config.get("secret_gesture_enabled", False) and required_gesture != "none":
                    if self.config.get("pam_logging", True):
                        msg = f"INFO: 😉 Please {required_gesture.replace('_', ' ').upper()} to authenticate...\n"
                        try: conn.sendall(msg.encode())
                        except: pass
                elif self.config.get("liveness_required", False) and self.config.get("pam_logging", True):
                    try: conn.sendall("INFO: 👁️ Please BLINK to verify liveness...\n".encode())
                    except: pass
                self._last_pam_info = now_loop

            # Check if client disconnected (User might have started typing password)
            try:
                data = conn.recv(1, socket.MSG_PEEK)
                if not data: # Connection closed
                    conn.setblocking(True)
                    return "FAILURE"
            except (BlockingIOError, InterruptedError):
                pass # Still connected, no data
            except:
                conn.setblocking(True)
                return "FAILURE"

            attempt += 1
            with self.cam_lock:
                frame = self.cam.get_frame()
                if frame is None:
                    consecutive_cam_fails += 1
                    if consecutive_cam_fails > 50: # Give camera 5s to warm up
                        log_event(f"AUTH FAILED: Camera hardware failure (50 consecutive null frames).", 
                                  enabled=self.config.get('logging_enabled', True))
                        conn.setblocking(True)
                        self.cam.release()
                        return "FAILURE"
                    time.sleep(0.1)
                    continue
                consecutive_cam_fails = 0 # Reset on success

                if self.app is not None and hasattr(self.app, 'get'):
                    faces = self.app.get(frame)
                else:
                    faces = []
                
                # Filter for liveness (Passive LBP) - Phase 30
                if self.config.get("passive_liveness_enabled", True):
                    alive_faces = []
                    for face in faces:
                        score, is_live = self.liveness.analyze(frame, face.bbox)
                        if is_live:
                            alive_faces.append(face)
                        else:
                            if attempt % 10 == 0:
                                log_event(f"SECURITY: Potential spoofing detected (LBP Score: {score:.2f})")
                    faces = alive_faces
            
            if not faces:
                # Optimized Phase 2 & 5: Adaptive sleep
                idle_sleep = 0.2
                if self.config.get("power_throttling_enabled", True):
                    on_bat, perc = self.get_battery_status()
                    if on_bat and perc < 30:
                        idle_sleep = 0.5 # Double sleep on low battery
                
                time.sleep(idle_sleep)
                continue

            # Face detected, process at full speed (or minimal sleep)
            match_found_in_frame = False
            for face in faces:
                live_embedding = face.normed_embedding
                
                # --- Liveness Phase 1: Blink Detection ---
                liveness_detected = False
                if hasattr(face, 'landmark_3d_68'):
                    left_ear, right_ear = self.calculate_ear(face.landmark_3d_68)
                    ear = (left_ear + right_ear) / 2.0
                    blink_count, is_closed = self.blink_state.get(username, (0, False))
                    
                    # Log EAR occasionally for tuning
                    if attempt % 10 == 0:
                        log_event(f"DEBUG: L-EAR={left_ear:.4f}, R-EAR={right_ear:.4f} for {username}")

                    if ear < float(self.config.get("ear_threshold", 0.20)):
                        is_closed = True
                    elif is_closed:
                        blink_count += 1
                        is_closed = False
                        log_event(f"SECURITY: Blink detected for {username} (Total: {blink_count})")
                    
                    self.blink_state[username] = (blink_count, is_closed)
                    if blink_count >= 1:
                        liveness_detected = True

                    # --- Liveness Phase 2: Gesture (Smile/Mouth Open) ---
                    gesture_detected = False
                    mar = self.calculate_mar(face.landmark_3d_68)
                    smile_score = self.calculate_smile_score(face.landmark_3d_68)
                    
                    # NEW: Smile to Unlock
                    if self.config.get("smile_required", False):
                        if smile_score > 5.0: # Threshold for detectable smile
                            gesture_detected = True
                            if attempt % 5 == 0:
                                log_event(f"SECURITY: Smile detected for {username} (Score: {smile_score:.2f})")
                    else:
                        if mar > 0.35: # Threshold for mouth open/speech
                            gesture_detected = True
                            if attempt % 5 == 0:
                                log_event(f"SECURITY: Mouth activity detected for {username} (MAR: {mar:.2f})")

                    # --- Phase 8: Secret Gestures ---
                    secret_gesture_ok = True
                    required_gesture = self.config.get("secret_gesture", "none") # "none", "wink_left", "wink_right", "tilt_left", "tilt_right"
                    
                    if required_gesture == "wink_left":
                        # Left eye closed, right eye open
                        if left_ear < 0.20 and right_ear > 0.25:
                            log_event(f"SECURITY: Secret Gesture 'Wink Left' detected for {username}")
                        else: secret_gesture_ok = False
                    elif required_gesture == "wink_right":
                        if right_ear < 0.20 and left_ear > 0.25:
                            log_event(f"SECURITY: Secret Gesture 'Wink Right' detected for {username}")
                        else: secret_gesture_ok = False
                    elif required_gesture == "tilt_left":
                        tilt = self.calculate_head_tilt(face.landmark_3d_68)
                        if tilt < -15:
                            log_event(f"SECURITY: Secret Gesture 'Tilt Left' detected for {username} ({tilt:.1f}deg)")
                        else: secret_gesture_ok = False
                    elif required_gesture == "tilt_right":
                        tilt = self.calculate_head_tilt(face.landmark_3d_68)
                        if tilt > 15:
                            log_event(f"SECURITY: Secret Gesture 'Tilt Right' detected for {username} ({tilt:.1f}deg)")
                        else: secret_gesture_ok = False

                # Step 1: Try matched cache first (Buttery Smooth retries)
                cached = self.match_cache.get(username)
                if cached:
                    cached_emb, cached_name = cached
                    score = float(np.dot(live_embedding, cached_emb))
                    if score >= active_threshold:
                        # Check requirements
                        liveness_ok = not self.config.get("liveness_required", False) or liveness_detected
                        gesture_ok = not self.config.get("gesture_required", False) or gesture_detected
                        secret_ok = not self.config.get("secret_gesture_enabled", False) or secret_gesture_ok
                        
                        if not (liveness_ok and gesture_ok and secret_ok):
                            continue # Keep looking

                        log_event(f"AUTH SUCCESS (CACHE): User '{username}' recognized as '{cached_name}' (Score: {score:.4f}, Threshold: {active_threshold:.2f})",
                                   enabled=self.config.get('logging_enabled', True))
                    if self.config.get("notifications_enabled", True):
                        self.dbus.emit_verified(username)
                        self._finish_success(username, cached_name, conn, service)
                        return "SUCCESS"

                # Step 2: Full search
                best_score = -1.0
                best_match = None
                
                # Ensure targets is a list to avoid None errors
                search_targets = targets if targets is not None else []
                for name, target_embedding in search_targets:
                    score = float(np.dot(live_embedding, target_embedding))
                    if score > best_score:
                        best_score = score
                        best_match = name
                
                if best_score > overall_best_score:
                    overall_best_score = best_score

                if best_score >= active_threshold:
                    # Check requirements
                    liveness_ok = not self.config.get("liveness_required", False) or liveness_detected
                    gesture_ok = not self.config.get("gesture_required", False) or gesture_detected
                    secret_ok = not self.config.get("secret_gesture_enabled", False) or secret_gesture_ok
                    
                    if not (liveness_ok and gesture_ok and secret_ok):
                        continue # Keep looking

                    log_event(f"AUTH SUCCESS: User '{username}' recognized as '{best_match}' (Score: {best_score:.4f}, Threshold: {active_threshold:.2f})", 
                               enabled=self.config.get('logging_enabled', True))
                    
                    # Update cache for next time
                    if self.config.get("notifications_enabled", True):
                        self.dbus.emit_verified(username)
                    self.match_cache[username] = (live_embedding, best_match)
                    self._finish_success(username, best_match, conn, service)
                    return "SUCCESS"
            
            # Face was present but not matched, brief pause (50ms)
            time.sleep(0.05)

        log_event(f"AUTH FAILED: Recognition timeout for '{username}' after {attempt} attempts. Highest score: {overall_best_score:.4f} (Threshold: {active_threshold:.2f})", 
                  enabled=self.config.get('logging_enabled', True))
            
        # Increment failure count
        if self.config.get("notifications_enabled", True):
            self.dbus.emit_denied(username)
        stats = self.failed_attempts.get(username, (0, 0.0))
        count, _ = stats
        self.failed_attempts[username] = (count + 1, time.time())
        conn.setblocking(True)
        self.cam.release()
        return "FAILURE"

    def _finish_success(self, username, matched_name, conn, service):
        """Common cleanup on success."""
        self.failed_attempts[username] = (0, 0)
        self.last_success[username] = time.time()
        
        conn.setblocking(True)
        self.cam.release()

    def run(self):
        socket_path = self.config['socket_path']
        if os.path.exists(socket_path):
            os.remove(socket_path)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(socket_path)
        os.chmod(socket_path, 0o666)
        server.listen(1)

        print(f"Daemon listening on {socket_path}...")

        while True:
            conn, _ = server.accept()
            try:
                raw_request = conn.recv(1024).decode().strip()
                if raw_request.startswith("AUTH "):
                    parts = raw_request.split()
                    username = parts[1] if len(parts) > 1 else None
                    service = parts[2] if len(parts) > 2 else "unknown"
                    
                    if not username:
                        conn.sendall(b"FAILURE")
                        continue

                    # Reload config on each auth attempt for live changes
                    new_config = load_config()
                    log_event(f"DEBUG: Received request for {username} (Service: {service})", 
                               enabled=new_config.get('logging_enabled', True))
                    
                    # 1. Check System Master Switch
                    if not new_config.get("system_enabled", True):
                        log_event(f"AUTH REJECTED: System is globally disabled in config.", 
                                   enabled=new_config.get('logging_enabled', True))
                        conn.sendall(b"FAILURE")
                        continue
                    
                    # Hot-reload model if it changed in config
                    if new_config.get('model_name') != self.config.get('model_name'):
                        print(f"Model change detected: {new_config['model_name']}. Hot-reloading...")
                        models_dir = os.path.join(BASE_DIR, "models")
                        self.app = FaceAnalysis(name=new_config['model_name'], root=models_dir, providers=['CPUExecutionProvider'])
                        self.app.prepare(ctx_id=0, det_size=(320, 320))
                        
                        # Ensure new model directory exists and is writable
                        if not os.path.exists(new_config['users_dir']):
                            os.makedirs(new_config['users_dir'], mode=0o777, exist_ok=True)
                            os.chmod(new_config['users_dir'], 0o777)
                    
                    self.config = new_config
                    self.auth_in_progress = True
                    try:
                        result = self.verify(username, conn, service)
                        conn.sendall(result.encode())
                    finally:
                        self.auth_in_progress = False
                elif raw_request.startswith("GET_STATUS"):
                    if self.is_scanning:
                        conn.sendall(b"SCANNING")
                    else:
                        conn.sendall(b"IDLE")
                elif raw_request.startswith("GET_CONFIG "):
                    key = raw_request.split(" ", 1)[1]
                    # Reload config for latest value
                    conf = load_config()
                    val = str(conf.get(key, ""))
                    conn.sendall(val.encode())
            except Exception as e:
                print(f"Error handling request: {e}")
            finally:
                conn.close()

if __name__ == "__main__":
    daemon = FaceDaemon()
    daemon.run()