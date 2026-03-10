from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QScrollArea, QCheckBox, 
                             QGridLayout, QSlider, QMessageBox, QComboBox,
                             QLineEdit)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
import os
import json
import subprocess

ACCENT_BLUE = "#007bff"
CARD_BG = "#1A1C1E"
GRID_BORDER = "#252830"

# Resolve Project Root (up 3 levels from src/gui/ui_views/)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

class SettingsWidget(QWidget):
    def __init__(self, config=None):
        super().__init__()
        self.config = config or {}
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        
        # Header
        header = QLabel("SETTINGS")
        header.setFont(QFont("Segoe UI", 26, QFont.Bold))
        header.setStyleSheet(f"color: {ACCENT_BLUE};")
        layout.addWidget(header)
        
        # Scroll Area for settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(20)
        
        # Sections
        self.controls = {}
        
        # AUTH SECTION
        self.add_section("AUTHENTICATION", [
            ("Face Authentication", "face_auth", "checkbox"),
            ("Manual Approval Dialog", "manual_approval", "checkbox"),
            ("Desktop Notifications", "notifications", "checkbox"),
            ("Enable Overlay Popup", "auth_overlay", "checkbox")
        ], content_layout)
        
        # SYSTEM SECTION
        self.add_section("PAM INTEGRATION", [
            ("Enable Global Unlock", "global_unlock", "checkbox"),
            ("Enable Sudo Support", "pam_sudo", "checkbox"),
            ("Enable GDM Support", "pam_gdm", "checkbox")
        ], content_layout)

        # SECURITY SECTION
        self.add_section("RECOGNITION ENGINE", [
            ("AI Model Engine", "model_name", "model_selector", ["buffalo_l", "buffalo_sc", "buffalo_s"]),
            ("Similarity Threshold", "threshold", "slider", 10, 95, 0.01),
            ("Scan Duration (sec)", "search_duration", "slider", 1, 10, 0.5),
            ("Basic Liveness", "liveness_required", "checkbox"),
            ("Require Mouth/Smile", "gesture_required", "checkbox")
        ], content_layout)

        # 2FA / GESTURE SECTION
        self.add_section("SECRET GESTURES (MFA)", [
            ("Enable Secret Gesture", "secret_gesture_enabled", "checkbox"),
            ("Required Gesture Type", "secret_gesture", "dropdown", ["none", "wink_left", "wink_right", "tilt_left", "tilt_right"])
        ], content_layout)

        # CONTEXTUAL SECURITY
        self.add_section("SAFE ZONES", [
            ("Safe SSIDs (Comma Separated)", "safe_ssids", "text"),
            ("Safe Zone Threshold Drop (%)", "safe_zone_drop", "slider", 0, 30, 1)
        ], content_layout)

        # ADVANCED SECTION
        self.add_section("SECURITY POLICIES", [
            ("Retry Limit (Attempts)", "max_failures", "slider", 1, 10, 1),
            ("Grace Period (Seconds)", "grace_period", "slider", 0, 300, 5),
            ("Cooldown Time (Sec)", "cooldown_time", "slider", 30, 600, 10),
            ("Audit Logging", "logging_enabled", "checkbox")
        ], content_layout)
        
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        # System Actions
        action_layout = QHBoxLayout()
        fix_btn = QPushButton("FIX PERMISSIONS")
        fix_btn.setStyleSheet(f"background-color: transparent; color: {ACCENT_BLUE}; border: 1px solid {ACCENT_BLUE}; padding: 10px; border-radius: 5px; font-weight: bold;")
        fix_btn.clicked.connect(self.fix_permissions)
        action_layout.addWidget(fix_btn)
        
        content_layout.addLayout(action_layout)

        # Save Bar
        save_bar = QFrame()
        save_bar.setFixedHeight(80)
        save_bar.setStyleSheet(f"background-color: {CARD_BG}; border-top: 1px solid #20ffffff;")
        save_layout = QHBoxLayout(save_bar)
        save_layout.addStretch()
        
        save_btn = QPushButton("SAVE CHANGES")
        save_btn.setFixedSize(220, 45)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_BLUE}; 
                color: white; 
                border-radius: 10px; 
                font-weight: bold; 
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: #0056b3;
            }}
        """)
        save_btn.clicked.connect(self.save_settings)
        save_layout.addWidget(save_btn)
        
        layout.addWidget(save_bar)
        
    def add_section(self, title, items, parent_layout):
        section = QFrame()
        section.setStyleSheet(f"background-color: {CARD_BG}; border-radius: 12px; border: 1px solid #20ffffff;")
        sec_layout = QVBoxLayout(section)
        sec_layout.setContentsMargins(20, 20, 20, 20)
        
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {ACCENT_BLUE}; font-size: 11px; font-weight: bold; letter-spacing: 2px; margin-bottom: 10px;")
        sec_layout.addWidget(title_lbl)
        
        grid = QGridLayout()
        grid.setSpacing(20)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        
        for i, item in enumerate(items):
            label = item[0]
            key = item[1]
            type = item[2]
            
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #e0e0e0; font-size: 14px;")
            grid.addWidget(lbl, i, 0)
            
            if type == "checkbox":
                cb = QCheckBox()
                cb.setChecked(self.config.get(key, True))
                grid.addWidget(cb, i, 1, Qt.AlignRight)
                self.controls[key] = cb
            elif type == "slider":
                min_val, max_val, step = item[3], item[4], item[5]
                slider = QSlider(Qt.Horizontal)
                slider.setRange(int(min_val/step), int(max_val/step))
                
                # Default values handler
                current_val = self.config.get(key)
                if current_val is None:
                    if key == "threshold": current_val = 0.45
                    elif key == "search_duration": current_val = 3.5
                    elif key == "max_failures": current_val = 5
                    elif key == "grace_period": current_val = 0
                    elif key == "cooldown_time": current_val = 60
                    else: current_val = min_val
                
                slider.setValue(int(current_val/step))
                
                val_lbl = QLabel(f"{current_val}")
                val_lbl.setFixedWidth(40)
                val_lbl.setStyleSheet("color: #8a8fb5; font-weight: bold;")
                
                slider.valueChanged.connect(lambda v, l=val_lbl, s=step: l.setText(f"{round(v*s, 2)}"))
                
                slider_layout = QHBoxLayout()
                slider_layout.addWidget(slider)
                slider_layout.addWidget(val_lbl)
                grid.addLayout(slider_layout, i, 1)
                
                self.controls[key] = (slider, step)
            elif type == "dropdown":
                cb = QComboBox()
                cb.addItems(item[3])
                cb.setCurrentText(str(self.config.get(key, "none")))
                cb.setStyleSheet("background-color: #252830; color: white; border: 1px solid #40ffffff; padding: 5px;")
                grid.addWidget(cb, i, 1)
                self.controls[key] = cb
            elif type == "text":
                le = QLineEdit()
                val = self.config.get(key, [])
                if isinstance(val, list):
                    le.setText(", ".join(val))
                else:
                    le.setText(str(val))
                le.setStyleSheet("background-color: #252830; color: white; border: 1px solid #40ffffff; padding: 5px;")
                grid.addWidget(le, i, 1)
                self.controls[key] = le
            elif type == "model_selector":
                model_layout = QHBoxLayout()
                cb = QComboBox()
                cb.addItems(item[3])
                current_model = self.config.get(key, "buffalo_l")
                cb.setCurrentText(current_model)
                cb.setStyleSheet("background-color: #252830; color: white; border: 1px solid #40ffffff; padding: 5px;")
                model_layout.addWidget(cb)
                
                download_btn = QPushButton("DOWNLOAD")
                download_btn.setFixedWidth(100)
                download_btn.setStyleSheet("font-size: 10px; font-weight: bold; background: transparent; border: 1px solid #007bff; color: #007bff;")
                
                # Check if model exists
                if self.is_model_ready(current_model):
                    download_btn.setText("READY")
                    download_btn.setEnabled(False)
                    download_btn.setStyleSheet("font-size: 10px; font-weight: bold; background: transparent; border: 1px solid #00ff88; color: #00ff88;")
                
                download_btn.clicked.connect(lambda _, m=cb, b=download_btn: self.download_model(m.currentText(), b))
                cb.currentTextChanged.connect(lambda t, b=download_btn: self.update_download_btn(t, b))
                
                model_layout.addWidget(download_btn)
                grid.addLayout(model_layout, i, 1)
                self.controls[key] = cb
            
        sec_layout.addLayout(grid)
        parent_layout.addWidget(section)

    def check_identity_count(self):
        try:
            model_name = self.config.get("model_name", "buffalo_s")
            search_dirs = [
                os.path.expanduser(f"~/.linux-bonjour/users/{model_name}"),
                os.path.join(PROJECT_ROOT, "config", "users", model_name),
                f"/usr/share/linux-bonjour/config/users/{model_name}"
            ]
            unique_users = set()
            for users_dir in search_dirs:
                if os.path.exists(users_dir):
                    users = [f.rsplit(".", 1)[0] for f in os.listdir(users_dir) if f.endswith(".enc") or f.endswith(".npy")]
                    unique_users.update(users)
            return len(unique_users)
        except: return 0

    def save_settings(self):
        # Validation: Check if face_auth is being enabled without identities
        face_auth_ctrl = self.controls.get("face_auth")
        if face_auth_ctrl and isinstance(face_auth_ctrl, QCheckBox) and face_auth_ctrl.isChecked():
            if self.check_identity_count() == 0:
                QMessageBox.warning(self, "Validation Failed", 
                    "Cannot enable Face Authentication because no faces are enrolled!\n\nPlease go to ENROLLMENT tab first.")
                face_auth_ctrl.setChecked(False)
                return

        # Update config object
        for key, ctrl in self.controls.items():
            if isinstance(ctrl, QCheckBox):
                self.config[key] = ctrl.isChecked()
            elif isinstance(ctrl, tuple): # Slider with (slider, step)
                slider, step = ctrl
                self.config[key] = round(slider.value() * step, 2)
            elif isinstance(ctrl, QComboBox):
                self.config[key] = ctrl.currentText()
            elif isinstance(ctrl, QLineEdit):
                if key == "safe_ssids":
                    self.config[key] = [s.strip() for s in ctrl.text().split(",") if s.strip()]
                else:
                    self.config[key] = ctrl.text()

        try:
            import sys
            user_config = os.path.expanduser("~/.linux-bonjour/config.json")
            os.makedirs(os.path.dirname(user_config), exist_ok=True)
            
            with open(user_config, "w") as f:
                json.dump(self.config, f, indent=4)
            
            # Sync PAM if needed and verify success
            sync_ok = self.sync_pam()
            
            if sync_ok:
                QMessageBox.information(self, "Success", "Settings saved and applied! 🎉")
            else:
                QMessageBox.warning(self, "Partial Success", "Local settings saved, but system-wide PAM sync was cancelled or failed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")

    def sync_pam(self):
        setup_script = "/usr/share/linux-bonjour/scripts/setup_pam.sh"
        if not os.path.exists(setup_script):
            setup_script = os.path.join(PROJECT_ROOT, "scripts", "setup_pam.sh")
        
        if os.path.exists(setup_script):
            try:
                # Use check=True to raise exception on failure (like user cancel)
                if self.config.get("global_unlock"):
                    subprocess.run(["pkexec", "bash", setup_script, "--enable-all"], check=True)
                else:
                    subprocess.run(["pkexec", "bash", setup_script, "--disable-all"], check=True)
                return True
            except subprocess.CalledProcessError:
                return False
            except Exception:
                return False
        return True # If script missing, we can't sync but didn't "fail" a sync attempt

    def fix_permissions(self):
        try:
            import getpass
            user = getpass.getuser()
            subprocess.run(["pkexec", "usermod", "-aG", "video", user], check=True)
            QMessageBox.information(self, "Group Updated", f"Added '{user}' to video group. Please log out and back in.")
        except:
            QMessageBox.critical(self, "Error", "Failed to elevate permissions.")

    def update_download_btn(self, model_name, btn):
        if self.is_model_ready(model_name):
            btn.setText("READY")
            btn.setEnabled(False)
            btn.setStyleSheet("font-size: 10px; font-weight: bold; background: transparent; border: 1px solid #00ff88; color: #00ff88;")
        else:
            btn.setText("DOWNLOAD")
            btn.setEnabled(True)
            btn.setStyleSheet("font-size: 10px; font-weight: bold; background: transparent; border: 1px solid #007bff; color: #007bff;")

    def is_model_ready(self, model_name):
        """Robust check for model existence based on known filenames."""
        model_dir = f"/usr/share/linux-bonjour/models/models/{model_name}"
        if not os.path.exists(model_dir):
            return False
            
        # Check for detection markers
        markers = ["det_500m.onnx", "det_10g.onnx", "det_2g.onnx"]
        found_det = any(os.path.exists(os.path.join(model_dir, m)) for m in markers)
        
        # Check for recognition markers
        rec_markers = ["w600k_mbf.onnx", "w600k_r50.onnx"]
        found_rec = any(os.path.exists(os.path.join(model_dir, m)) for m in rec_markers)
        
        return found_det and found_rec

    def download_model(self, model_name, btn):
        btn.setText("DOWNLOADING...")
        btn.setEnabled(False)
        self.repaint() # Force UI update
        
        init_script = "/usr/share/linux-bonjour/src/daemon/init_models.py"
        if not os.path.exists(init_script):
            init_script = os.path.join(PROJECT_ROOT, "src", "daemon", "init_models.py")
            
        try:
            # Run model init via pkexec to ensure write permissions to /usr/share
            subprocess.run(["pkexec", "python3", init_script, "/usr/share/linux-bonjour/models", model_name], check=True)
            QMessageBox.information(self, "Success", f"Model '{model_name}' downloaded successfully!")
            self.update_download_btn(model_name, btn)
        except Exception as e:
            QMessageBox.critical(self, "Download Failed", f"Failed to download model: {e}")
            self.update_download_btn(model_name, btn)
