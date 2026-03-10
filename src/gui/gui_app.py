import sys
import os
import time
import json
import io
import psutil
import subprocess
import numpy as np
import cv2
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QSlider, QSpinBox, QPushButton, 
                             QGroupBox, QLineEdit, QListWidget, QProgressBar,
                              QListWidgetItem, QMessageBox, QFrame, QComboBox,
                             QScrollArea, QCheckBox, QStackedWidget, QListWidget, QSizePolicy)
from PySide6.QtCore import Qt, QTimer, Slot, QThread, Signal, QSize
from PySide6.QtGui import QFont, QPalette, QColor, QImage, QPixmap, QLinearGradient, QBrush

# Add project root to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(os.path.join(PROJECT_ROOT, "src"))

from daemon.camera import IRCamera
from daemon.sys_info import get_system_specs, suggest_model
from insightface.app import FaceAnalysis
import io
from daemon.crypto_utils import encrypt_data
from gui.ui.styles import GLOBAL_STYLE, SIDEBAR_COLOR, ACCENT_CYAN, GLASS_WHITE, ACCENT_TEAL, TEXT_SECONDARY, ERROR_RED, WARNING_GOLD

# Import views
from gui.ui.views.dashboard import DashboardView
from gui.ui.views.enrollment import EnrollmentView
from gui.ui.views.settings import SettingsView

class StatusWorker(QThread):
    status_signal = Signal(bool)
    pam_status_signal = Signal(bool)
    granular_status_signal = Signal(dict)

    def __init__(self):
        super().__init__()
        self._run_flag = True

    def run(self):
        while self._run_flag:
            try:
                # Daemon status
                res = subprocess.run(["systemctl", "is-active", "linux-bonjour"], 
                                   capture_output=True, text=True, timeout=2)
                active = res.stdout.strip() == "active"
                self.status_signal.emit(active)
                
                # PAM status
                pam_res = subprocess.run([os.path.join(PROJECT_ROOT, "scripts", "setup_pam.sh"), "--status"], 
                                       capture_output=True, text=True, timeout=2)
                
                # Global Detection
                pam_enabled = "[ENABLED]  common-auth" in pam_res.stdout
                self.pam_status_signal.emit(pam_enabled)
                
                # Granular Detection
                granular = {
                    "login": any(x in pam_res.stdout for x in ["[ENABLED]  gdm-password", "[ENABLED]  sddm", "[ENABLED]  lightdm"]),
                    "sudo": "[ENABLED]  sudo" in pam_res.stdout,
                    "polkit": "[ENABLED]  polkit-1" in pam_res.stdout
                }
                self.granular_status_signal.emit(granular)
            except:
                self.status_signal.emit(False)
                self.pam_status_signal.emit(False)
                self.granular_status_signal.emit({"login": False, "sudo": False, "polkit": False})
            self.msleep(3000) # Check every 3s

    def stop(self):
        self._run_flag = False
        self.wait()

class ModelDownloadWorker(QThread):
    finished = Signal(bool, str)
    progress = Signal(str)

    def __init__(self, model_names):
        super().__init__()
        self.model_names = model_names

    def run(self):
        try:
            from daemon.init_models import init_models
            # We patch init_models temporarily or just call it if it's flexible
            # Actually, let's just use the logic from it
            models_dir = "/usr/share/linux-bonjour/models"
            from insightface.app import FaceAnalysis
            
            for model_name in self.model_names:
                self.progress.emit(f"Downloading {model_name}...")
                app = FaceAnalysis(name=model_name, root=models_dir, providers=['CPUExecutionProvider'])
                app.prepare(ctx_id=0, det_size=(320, 320))
            
            self.finished.emit(True, "All selected models are ready! ✅")
        except Exception as e:
            self.finished.emit(False, f"Download failed: {e}")

class RestartWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        try:
            # Use a longer timeout for pkexec/systemctl restarts
            res = subprocess.run(self.command, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                self.finished.emit(True, "Service restarted successfully.")
            else:
                self.finished.emit(False, res.stderr or res.stdout)
        except Exception as e:
            self.finished.emit(False, str(e))

class VideoThread(QThread):
    change_pixmap_signal = Signal(QImage)
    face_detected_signal = Signal(bool, object) # detected, face_obj
    status_msg_signal = Signal(str)

    def __init__(self, config):
        super().__init__()
        self._run_flag = True
        self.config = config
        self.model_name = config.get("model_name", "buffalo_s")
        self.app = None

    def is_model_ready(self, model_name=None):
        """Check if model files exist and aren't being actively written (rudimentary check)."""
        target_model = model_name or self.model_name
        models_base = "/usr/share/linux-bonjour/models/models"
        model_path = os.path.join(models_base, target_model)
        
        if not os.path.exists(model_path):
            return False
            
        # Insightface models usually have at least 2-3 files (.onnx, etc)
        try:
            files = os.listdir(model_path)
            # Most models have ~5 files, SC has 2.
            if len(files) < 2:
                return False
            
            # Check for the primary detection file
            if not os.path.exists(os.path.join(model_path, "det_500m.onnx")):
                return False
                
            return True
        except:
            return False

    def run(self):
        # 1. Open Camera Immediately for instant feedback
        self.status_msg_signal.emit("Connecting to Camera...")
        cam = IRCamera(config=self.config)
        
        # 2. Main Loop
        retry_count = 0
        self.status_msg_signal.emit("Preview Active")
        while self._run_flag:
            frame = cam.get_frame()
            if frame is not None:
                # 3. Check/Initialize AI in background without blocking
                if not self.app:
                    if self.is_model_ready():
                        self.status_msg_signal.emit("Initializing AI Engine...")
                        try:
                            models_dir = "/usr/share/linux-bonjour/models"
                            self.app = FaceAnalysis(name=self.model_name, root=models_dir, providers=['CPUExecutionProvider'])
                            self.app.prepare(ctx_id=0, det_size=(320, 320))
                            self.status_msg_signal.emit("AI Engine Active")
                        except Exception as e:
                            self.status_msg_signal.emit(f"AI Loading...")
                    else:
                        if retry_count % 100 == 0:
                            self.status_msg_signal.emit(f"Downloading Models ({self.model_name})...")
                        retry_count += 1

                # 4. Processing
                detected = False
                face_obj = None
                display_frame = frame.copy()

                if self.app:
                    try:
                        faces = self.app.get(frame)
                        detected = len(faces) > 0
                        if detected:
                            face_obj = faces[0]
                            bbox = face_obj.bbox.astype(int)
                            cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                    except:
                        pass
                
                # Convert to QImage (RGB for Qt)
                height, width, channel = display_frame.shape
                bytes_per_line = 3 * width
                q_img = QImage(display_frame.data, width, height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
                
                self.change_pixmap_signal.emit(q_img)
                self.face_detected_signal.emit(detected, face_obj)
            else:
                self.face_detected_signal.emit(False, None)
            
            self.msleep(30) # ~33 FPS
        
        cam.release()

    def stop(self):
        self._run_flag = False
        self.wait()

class ScannerOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.scan_line_y = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate_scan)
        self.timer.start(30)

    def animate_scan(self):
        h = self.height()
        if h > 0:
            self.scan_line_y = (self.scan_line_y + 5) % h
        else:
            self.scan_line_y = 0
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QColor, QRadialGradient
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Corner brackets
        w, h = self.width(), self.height()
        pen = QPen(QColor(ACCENT_CYAN), 2)
        pen.setOpacity(0.6)
        painter.setPen(pen)
        
        length = 30
        # Top Left
        painter.drawLine(15, 15, 15 + length, 15)
        painter.drawLine(15, 15, 15, 15 + length)
        # Top Right
        painter.drawLine(w - 15, 15, w - 15 - length, 15)
        painter.drawLine(w - 15, 15, w - 15, 15 + length)
        # Bottom Left
        painter.drawLine(15, h - 15, 15 + length, h - 15)
        painter.drawLine(15, h - 15, 15, h - 15 - length)
        # Bottom Right
        painter.drawLine(w - 15, h - 15, w - 15 - length, h - 15)
        painter.drawLine(w - 15, h - 15, w - 15, h - 15 - length)

        # Scanning line (Glassy Cyan)
        grad = QLinearGradient(0, self.scan_line_y - 20, 0, self.scan_line_y + 20)
        grad.setColorAt(0, QColor(0, 176, 244, 0))
        grad.setColorAt(0.5, QColor(0, 176, 244, 80))
        grad.setColorAt(1, QColor(0, 176, 244, 0))
        painter.fillRect(0, self.scan_line_y - 20, w, 40, grad)
        
        painter.setPen(QPen(QColor(ACCENT_CYAN), 1))
        painter.drawLine(0, self.scan_line_y, w, self.scan_line_y)

class LinuxBonjourGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux Bonjour")
        self.setMinimumSize(1000, 750)
        
        # Set Window Icon
        self.logo_path = os.path.join(PROJECT_ROOT, "src", "gui", "assets", "logo.png")
        if not os.path.exists(self.logo_path): # Fallback for installed package
            self.logo_path = "/usr/share/linux-bonjour/logo.png"
        
        if os.path.exists(self.logo_path):
            self.setWindowIcon(QPixmap(self.logo_path))
        
        self.config_path = os.path.join(PROJECT_ROOT, "config", "config.json")
        self.load_config()
        
        self.video_thread = None
        self.status_thread = None
        self.current_face_embedding = None
        self.pam_updating = False
        self.last_known_pam_state = None # To prevent loops
        
        # Auto-capture state
        self.auto_capture_enabled = True
        self.face_detect_start_time = None
        self.face_lost_time = None
        self.capture_delay = 1.6 # Slight increase for better capture quality
        self.grace_period = 0.6 # seconds to allow for flickers
        self.is_saving = False # Flag to prevent auto-capture re-trigger during dialogs
        
        self.apply_theme()
        self.setup_ui()
        self.start_status_monitoring()

    def apply_theme(self):
        self.setStyleSheet(GLOBAL_STYLE)
        
    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            self.config = {
                "threshold": 0.45,
                "cooldown_time": 60,
                "max_failures": 5,
                "model_name": "buffalo_l",
                "users_dir": "config/users",
                "camera_index": None,
                "camera_type": "AUTO",
                "auth_approval": True,
                "notifications_enabled": True
            }

    def save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            self.statusBar().showMessage("Settings Saved Successfully!", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"Error saving: {e}", 5000)

    def setup_ui(self):
        # Parent layout
        main_content = QWidget()
        main_layout = QHBoxLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. SIDEBAR
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(250)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setSpacing(5)
        self.sidebar.setContentsMargins(10, 20, 10, 20)
        
        # Sidebar Items
        items = [
            (" 🏠 DASHBOARD", "overview"),
            (" 🤳 ENROLLMENT", "enroll"),
            (" ⚙️ SETTINGS", "settings")
        ]
        for text, key in items:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(0, 50))
            self.sidebar.addItem(item)
        
        self.sidebar.currentRowChanged.connect(self.on_nav_changed)
        
        # v1.2.0 Fullscreen Toggle Button at Sidebar Bottom
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.fs_btn = QPushButton(" 📺  FULLSCREEN ")
        self.fs_btn.setObjectName("secondaryBtn")
        self.fs_btn.setMinimumHeight(50)
        self.fs_btn.clicked.connect(self.toggle_fullscreen)
        
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(10, 20, 10, 20)
        sidebar_layout.addWidget(self.sidebar)
        sidebar_layout.addStretch()
        sidebar_layout.addWidget(self.fs_btn)
        
        sidebar_container = QWidget()
        sidebar_container.setLayout(sidebar_layout)
        sidebar_container.setFixedWidth(250)
        sidebar_container.setObjectName("sidebarContainer")
        
        main_layout.addWidget(sidebar_container)

        # 2. MAIN CONTENT AREA
        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        self.container_layout.setContentsMargins(30, 30, 30, 30)
        
        # Header in title area (Appears on all pages)
        self.header_label = QLabel("LINUX BONJOUR")
        self.header_label.setFont(QFont("Inter", 24, QFont.Bold))
        self.header_label.setStyleSheet("color: white; margin-bottom: 20px;")
        self.container_layout.addWidget(self.header_label)

        self.stack = QStackedWidget()
        
        # Initialize Views
        self.dashboard_view = DashboardView()
        self.enrollment_view = EnrollmentView()
        self.settings_view = SettingsView()
        
        self.stack.addWidget(self.dashboard_view)
        self.stack.addWidget(self.enrollment_view)
        self.stack.addWidget(self.settings_view)
        
        self.container_layout.addWidget(self.stack)
        main_layout.addWidget(container, 1)
        
        self.setCentralWidget(main_content)
        
        # Setup Overlay on the correct label
        self.scanner_overlay = ScannerOverlay(self.dashboard_view.image_label)
        self.scanner_overlay.hide()
        
        # Connect View Signals
        self.dashboard_view.start_daemon_requested.connect(self.on_start_daemon)
        self.enrollment_view.enroll_signal.connect(self.toggle_video)
        self.enrollment_view.save_signal.connect(self.save_identity)
        self.enrollment_view.delete_signal.connect(self.delete_user)
        self.settings_view.config_changed.connect(self.apply_settings_from_view)
        self.settings_view.pam_toggle_requested.connect(self.on_pam_toggle_changed)
        self.settings_view.granular_toggle_requested.connect(self.on_granular_toggle_changed)
        self.settings_view.download_requested.connect(self.download_heavy_models)
        self.settings_view.m_combo.currentTextChanged.connect(self.on_model_selection_changed)
        self.settings_view.reset_requested.connect(self.reset_settings)
        self.settings_view.probe_requested.connect(self.probe_camera)
        self.settings_view.fix_perms_requested.connect(self.fix_permissions)
        
        # Initial Data Fill
        self.sidebar.setCurrentRow(0)
        self.refresh_users()
        self.settings_view.update_ui_from_config(self.config)

    def on_nav_changed(self, index):
        self.stack.setCurrentIndex(index)
        titles = ["DASHBOARD", "IDENTITY ENROLLMENT", "ADVANCED SETTINGS"]
        self.header_label.setText(titles[index])
        
        if index == 0: # Dashboard
            self.scanner_overlay.setParent(self.dashboard_view.image_label)
            is_active = self.video_thread and self.video_thread.isRunning()
            if is_active and self.config.get("show_scanner_overlay", True):
                self.scanner_overlay.show()
            else:
                self.scanner_overlay.hide()
        elif index == 1: # Enrollment
            self.scanner_overlay.setParent(self.enrollment_view.image_label)
            is_active = self.video_thread and self.video_thread.isRunning()
            if is_active and self.config.get("show_scanner_overlay", True):
                self.scanner_overlay.show()
            else:
                self.scanner_overlay.hide()
        else:
            self.scanner_overlay.hide()

    def sync_overlay_size(self):
        if hasattr(self, 'scanner_overlay'):
            parent = self.scanner_overlay.parentWidget()
            if parent:
                self.scanner_overlay.resize(parent.size())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
        super().keyPressEvent(event)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.statusBar().showMessage("Window Mode", 2000)
        else:
            self.showFullScreen()
            self.statusBar().showMessage("Fullscreen Mode (Press F11 or Esc to exit)", 3000)

    def start_status_monitoring(self):
        self.status_thread = StatusWorker()
        self.status_thread.status_signal.connect(self.update_status_label)
        self.status_thread.pam_status_signal.connect(self.update_pam_toggle)
        self.status_thread.granular_status_signal.connect(self.update_granular_pam)
        self.status_thread.start()

    def update_status_label(self, active):
        self.dashboard_view.update_status(active)
        # Update small status in main header too
        color = "#03dac6" if active else "#f04747"
        # Since I replaced status_label with header_label in setup_ui, 
        # I'll just skip the small label for now or re-add it if needed.
        pass

    @Slot(bool)
    def update_pam_toggle(self, enabled):
        if not self.pam_updating and enabled != self.last_known_pam_state:
            self.last_known_pam_state = enabled
            self.settings_view.pam_toggle.blockSignals(True)
            self.settings_view.pam_toggle.setChecked(enabled)
            self.settings_view.pam_toggle.blockSignals(False)
            
            # If global is enabled, granular ones should be checked and disabled
            for toggle in [self.settings_view.login_toggle, self.settings_view.sudo_toggle, self.settings_view.polkit_toggle]:
                toggle.blockSignals(True)
                if enabled: toggle.setChecked(True)
                toggle.setEnabled(not enabled)
                toggle.blockSignals(False)

    @Slot(dict)
    def update_granular_pam(self, granular):
        if self.pam_updating or self.last_known_pam_state: # Skip if global is active or updating
            return
        
        self.settings_view.login_toggle.blockSignals(True)
        self.settings_view.login_toggle.setChecked(granular.get("login", False))
        self.settings_view.login_toggle.blockSignals(False)
        
        self.settings_view.sudo_toggle.blockSignals(True)
        self.settings_view.sudo_toggle.setChecked(granular.get("sudo", False))
        self.settings_view.sudo_toggle.blockSignals(False)
        
        self.settings_view.polkit_toggle.blockSignals(True)
        self.settings_view.polkit_toggle.setChecked(granular.get("polkit", False))
        self.settings_view.polkit_toggle.blockSignals(False)

    def refresh_pam_status(self):
        # Manually trigger a status check if needed
        script_path = os.path.join(PROJECT_ROOT, "scripts", "setup_pam.sh")
        pam_res = subprocess.run([script_path, "--status"], capture_output=True, text=True)
        
        global_enabled = "[ENABLED]  common-auth" in pam_res.stdout
        granular = {
            "login": any(x in pam_res.stdout for x in ["[ENABLED]  gdm-password", "[ENABLED]  sddm", "[ENABLED]  lightdm"]),
            "sudo": "[ENABLED]  sudo" in pam_res.stdout,
            "polkit": "[ENABLED]  polkit-1" in pam_res.stdout
        }
        
        self.update_pam_toggle(global_enabled)
        self.update_granular_pam(granular)

    def on_pam_toggle_changed(self, state):
        current_bool = (state == 2)
        if current_bool == self.last_known_pam_state:
            return

        if current_bool:
            if not self.has_face_data():
                QMessageBox.critical(self, "No Face Data", "Cannot enable face unlock without any enrolled identities.\nPlease enroll at least one face profile first.")
                self.settings_view.pam_toggle.blockSignals(True)
                self.settings_view.pam_toggle.setChecked(False)
                self.settings_view.pam_toggle.blockSignals(False)
                return

        self.pam_updating = True
        command = "--enable-all" if current_bool else "--disable-all"
        try:
            script_path = os.path.join(PROJECT_ROOT, "scripts", "setup_pam.sh")
            subprocess.run(["pkexec", script_path, command], check=True)
            self.last_known_pam_state = current_bool
            
            # Disable granular toggles if global is ON to show it overrides them
            for toggle in [self.settings_view.login_toggle, self.settings_view.sudo_toggle, self.settings_view.polkit_toggle]:
                toggle.blockSignals(True)
                toggle.setChecked(current_bool)
                toggle.setEnabled(not current_bool)
                toggle.blockSignals(False)
                
            self.statusBar().showMessage(f"Global Security {'Enabled' if current_bool else 'Disabled'}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Elevation Failed", f"Could not update system security settings: {e}")
            self.settings_view.pam_toggle.blockSignals(True)
            self.settings_view.pam_toggle.setChecked(not current_bool)
            self.settings_view.pam_toggle.blockSignals(False)
        finally:
            self.pam_updating = False

    def on_granular_toggle_changed(self, service, state):
        if self.pam_updating: return
        current_bool = (state == 2)
        
        if current_bool and not self.has_face_data():
            QMessageBox.critical(self, "No Face Data", "Cannot enable face unlock without any enrolled identities.")
            self.refresh_pam_status() # Revert
            return

        self.pam_updating = True
        command = f"--{'enable' if current_bool else 'disable'}-{service}"
        try:
            script_path = os.path.join(PROJECT_ROOT, "scripts", "setup_pam.sh")
            subprocess.run(["pkexec", script_path, command], check=True)
            self.statusBar().showMessage(f"{service.capitalize()} Security {'Enabled' if current_bool else 'Disabled'}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Elevation Failed", f"Could not update {service} security: {e}")
            self.refresh_pam_status()
        finally:
            self.pam_updating = False

    def has_face_data(self):
        model_name = self.config.get("model_name", "buffalo_l")
        users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"), model_name)
        return os.path.exists(users_dir) and any(f.endswith(".npy") or f.endswith(".enc") for f in os.listdir(users_dir))

    def on_start_daemon(self):
        try:
            self.statusBar().showMessage("Attempting to start daemon...", 5000)
            # Start and ENABLE for persistence
            res = subprocess.run(["pkexec", "systemctl", "enable", "--now", "linux-bonjour"], 
                                 capture_output=True, text=True)
            if res.returncode == 0:
                self.statusBar().showMessage("Daemon Started and Enabled! 🎉", 3000)
                QMessageBox.information(self, "Service Started", "The Linux Bonjour background service is now active and set to start automatically on boot.")
            else:
                raise subprocess.CalledProcessError(res.returncode, res.args, res.stdout, res.stderr)
        except Exception as e:
            err_msg = str(e)
            if "polkit" in err_msg.lower() or "not authorized" in err_msg.lower():
                QMessageBox.warning(self, "Authorization Denied", "Action cancelled by user or lack of permissions.")
            else:
                QMessageBox.critical(self, "Service Error", 
                                     f"Failed to start daemon: {err_msg}\n\n"
                                     "Troubleshooting:\n"
                                     "1. Check if the package is correctly installed.\n"
                                     "2. Run 'systemctl status linux-bonjour' in terminal.\n"
                                     "3. Ensure your hardware (camera) is connected.")
            self.statusBar().showMessage("Start Failed ❌", 5000)

    def on_threshold_changed(self, value):
        self.settings_view.t_label.setText(f"{value/100:.2f}")

    def reset_settings(self):
        self.load_config()
        self.settings_view.update_ui_from_config(self.config)
        self.statusBar().showMessage("Settings Reset to Defaults", 3000)

    def apply_settings_from_view(self, new_config):
        new_model = new_config.get("model_name")
        old_model = self.config.get("model_name", "buffalo_s")

        if new_model != old_model:
            reply = QMessageBox.warning(self, "Model Switch Warning", 
                                       f"You are switching the AI engine from '{old_model}' to '{new_model}'.\n\n"
                                       "IMPORTANT: Face signatures are model-specific. Your existing face profiles "
                                       "will NOT work with the new model.\n\n"
                                       "Do you want to proceed?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                self.settings_view.m_combo.setCurrentText(old_model)
                return

        # Range checks for config
        t = new_config.get("threshold", 0.45)
        if not (0.1 <= t <= 0.95):
            QMessageBox.warning(self, "Invalid Setting", f"Threshold {t:.2f} is out of safe range (0.10 - 0.95).")
            return

        self.config.update(new_config)
        self.save_config()
        self.refresh_users()
        
        # Critical: Restart daemon if model or logging changed
        if new_model != old_model:
            self.statusBar().showMessage("Scheduling service restart for new AI engine...", 5000)
            self.restart_worker = RestartWorker(["pkexec", "systemctl", "restart", "linux-bonjour"])
            self.restart_worker.finished.connect(self.on_restart_finished)
            self.restart_worker.start()

        self.statusBar().showMessage("Configuration Applied! ✨", 3000)
        
        # Update UI components that depend on config immediately
        is_active = self.video_thread and self.video_thread.isRunning()
        visible_tab = self.stack.currentIndex() in [0, 1]
        if is_active and visible_tab and self.config.get("show_scanner_overlay", True):
            self.scanner_overlay.show()
        else:
            self.scanner_overlay.hide()

        QMessageBox.information(self, "Settings Saved", "System configuration has been successfully updated and applied.")

    def on_restart_finished(self, success, message):
        if success:
            self.statusBar().showMessage("Service Restarted! ✅", 3000)
        else:
            if "polkit" not in message.lower():
                self.statusBar().showMessage(f"Restart Failed: {message}", 5000)

    def on_model_selection_changed(self, index):
        self.update_model_download_button_visibility()

    def update_model_download_button_visibility(self):
        model_name = self.settings_view.m_combo.currentText()
        if not self.video_thread.is_model_ready(model_name):
            self.settings_view.download_btn.show()
            self.settings_view.download_btn.setText(f"☁️ Download {model_name}")
        else:
            self.settings_view.download_btn.hide()

    def download_heavy_models(self, model_name):
        self.settings_view.download_btn.setEnabled(False)
        self.settings_view.download_btn.setText("⏳ Downloading...")
        
        self.download_worker = ModelDownloadWorker([model_name])
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.progress.connect(lambda p: self.statusBar().showMessage(p, 5000))
        self.download_worker.start()

    def on_download_finished(self, success, message):
        self.settings_view.download_btn.setEnabled(True)
        self.update_model_download_button_visibility()
        if success:
            QMessageBox.information(self, "Download Complete", message)
            self.statusBar().showMessage(message, 5000)
        else:
            QMessageBox.warning(self, "Download Failed", message)
            self.statusBar().showMessage(message, 5000)
        
    def refresh_users(self):
        model_name = self.config.get("model_name", "buffalo_s")
        users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"), model_name)
        users = set()
        if os.path.exists(users_dir):
            try:
                files = os.listdir(users_dir)
                for f in files:
                    if f.endswith(".npy") or f.endswith(".enc"):
                        users.add(f.rsplit(".", 1)[0])
            except: pass
        self.enrollment_view.update_user_list(users)

    def delete_user(self, username):
        if not username: return
        if QMessageBox.question(self, 'Delete', f"Delete {username}?") == QMessageBox.Yes:
            model_name = self.config.get("model_name", "buffalo_s")
            users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"), model_name)
            path_enc = os.path.join(users_dir, f"{username}.enc")
            path_npy = os.path.join(users_dir, f"{username}.npy")
            
            deleted = False
            if os.path.exists(path_enc):
                os.remove(path_enc)
                deleted = True
            if os.path.exists(path_npy):
                os.remove(path_npy)
                deleted = True
                
            if deleted:
                self.refresh_users()
                self.statusBar().showMessage(f"Identity '{username}' Removed", 3000)

    @Slot()
    def toggle_video(self):
        if self.video_thread and self.video_thread.isRunning():
            self.stop_video()
        else:
            self.start_video()

    def start_video(self):
        self.enrollment_view.status_label.setText("Initializing Scanner...")
        self.enrollment_view.set_enrolling(True)
        if self.config.get("show_scanner_overlay", True):
            self.scanner_overlay.show()
        else:
            self.scanner_overlay.hide()
        self.video_thread = VideoThread(self.config)
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.face_detected_signal.connect(self.on_face_detected)
        self.video_thread.status_msg_signal.connect(lambda msg: self.enrollment_view.status_label.setText(msg))
        self.video_thread.start()

    def stop_video(self):
        if self.video_thread: self.video_thread.stop()
        self.scanner_overlay.hide()
        # Reset labels
        self.dashboard_view.image_label.setText("SYSTEM STANDBY")
        self.dashboard_view.image_label.setPixmap(QPixmap())
        self.enrollment_view.set_enrolling(False)

    @Slot(QImage)
    def update_image(self, qt_img):
        if self.video_thread is None: return
        
        pixmap = QPixmap.fromImage(qt_img)
        
        # Update Dashboard (Large Feed)
        label_dash = self.dashboard_view.image_label
        size_dash = label_dash.size()
        if not size_dash.isEmpty():
            scaled = pixmap.scaled(size_dash, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label_dash.setPixmap(scaled)
            self.sync_overlay_size()
        
        # Update Enrollment (Small Preview)
        label_enroll = self.enrollment_view.image_label
        size_enroll = label_enroll.size()
        if not size_enroll.isEmpty():
            scaled = pixmap.scaled(size_enroll, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label_enroll.setPixmap(scaled)

    @Slot(bool, object)
    def on_face_detected(self, detected, face_obj):
        now = time.time()
        view = self.enrollment_view
        
        if detected and face_obj is not None:
            self.current_face_embedding = face_obj.normed_embedding
            view.save_btn.setEnabled(True)
            self.face_lost_time = None 
            
            if view.auto_capture_cb.isChecked():
                username = view.u_input.text().strip()
                if not username:
                    view.status_label.setText("<font color='#ffa000'><b>ENTER USERNAME TO START</b></font>")
                    self.face_detect_start_time = None
                    return
                
                if self.face_detect_start_time is None:
                    self.face_detect_start_time = now
                
                elapsed = now - self.face_detect_start_time
                remaining = max(0, self.capture_delay - elapsed)
                
                if remaining > 0:
                    view.status_label.setText(f"<font color='#00b0f4' size='5'><b>LOCKING ON... {remaining:.1f}s</b></font>")
                else:
                    view.status_label.setText(f"<font color='{ACCENT_TEAL}' size='5'><b>SIGNATURE CAPTURED!</b></font>")
                    if self.save_identity(username):
                        self.face_detect_start_time = None
                    else:
                        self.face_detect_start_time = None
            else:
                view.status_label.setText(f"<font color='{ACCENT_TEAL}' size='4'><b>FACE READY</b></font>")
        else:
            if self.face_detect_start_time is not None:
                if self.face_lost_time is None:
                    self.face_lost_time = time.time()
                
                if time.time() - self.face_lost_time > self.grace_period:
                    self.face_detect_start_time = None
                    self.face_lost_time = None
                    view.status_label.setText("FACE LOST - RESETTING...")
                    view.status_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
            else:
                view.status_label.setText("POSITION YOUR FACE IN THE CENTER")
                view.status_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
            
            view.save_btn.setEnabled(False)
            self.current_face_embedding = None

    def save_identity(self, username=None):
        if self.is_saving: return False
        self.is_saving = True
        
        view = self.enrollment_view
        if username is None:
            username = view.u_input.text().strip()
        
        if not username:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid identity name.")
            self.is_saving = False
            return False

        # v1.2.0 Validation: Ensure system user exists
        import pwd
        try:
            pwd.getpwnam(username)
        except KeyError:
            reply = QMessageBox.question(self, "Unknown User", 
                                        f"The user '{username}' was not found on this system.\n\n"
                                        "Biometric auth only works for existing Ubuntu accounts.\n"
                                        "Do you want to save this profile anyway?",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                self.is_saving = False
                return False

        model_name = self.config.get("model_name", "buffalo_s")

        # Sanitize username (Linux standard: lowercase, starts with letter/underscore)
        import re
        if not re.match(r"^[a-z_][a-z0-9_-]*$", username):
            QMessageBox.warning(self, "Invalid Username", 
                                "Username must start with a lowercase letter or underscore, "
                                "and only contain lowercase letters, numbers, underscores, or hyphens.")
            self.is_saving = False
            return False
        
        if len(username) > 32:
            QMessageBox.warning(self, "Invalid Username", "Username is too long (max 32 characters).")
            self.is_saving = False
            return False

        if self.current_face_embedding is None:
            QMessageBox.warning(self, "No Face Detected", "Please start the live capture and look at the camera first.")
            self.is_saving = False
            return False

        model_name = self.config.get("model_name", "buffalo_s")
        users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"), model_name)
        path_enc = os.path.join(users_dir, f"{username}.enc")
        path_npy = os.path.join(users_dir, f"{username}.npy")

        # Overwrite Protection
        if os.path.exists(path_enc) or os.path.exists(path_npy):
            reply = QMessageBox.question(self, "Overwrite Identity", 
                                       f"An identity named '{username}' already exists. Overwrite it?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                self.is_saving = False
                return False

        try:
            os.makedirs(users_dir, exist_ok=True)
            
            # Encrypt the embedding
            buffer = io.BytesIO()
            np.save(buffer, self.current_face_embedding)
            embedding_bytes = buffer.getvalue()
            encrypted_data = encrypt_data(embedding_bytes)
            
            with open(path_enc, 'wb') as ef:
                ef.write(encrypted_data)
                
            # If an old .npy exists, remove it after encryption
            if os.path.exists(path_npy):
                os.remove(path_npy)
                
            self.refresh_users()
            self.stop_video()
            view.u_input.clear()
            self.statusBar().showMessage(f"Identity '{username}' saved successfully! ✅", 3000)
            QMessageBox.information(self, "Enrollment Success", f"Face signature for '{username}' has been securely encrypted and saved.")
            self.is_saving = False
            return True
        except Exception as e:
            import traceback
            err_details = traceback.format_exc()
            QMessageBox.critical(self, "Save Error", f"Could not save identity: {e}\n\nCheck logs for full trace.")
            
            self.is_saving = False
            return False

    def probe_camera(self):
        self.settings_view.log_area.setText("🔍 Probing hardware...")
        self.settings_view.log_area.setStyleSheet("color: #00b0f4;")
        
        try:
            # 1. Check /dev/video devices
            if not os.path.exists('/dev'):
                self.settings_view.log_area.setText("❌ /dev/ not found!")
                return

            videos = [f for f in os.listdir('/dev') if f.startswith('video')]
            if not videos:
                self.settings_view.log_area.setText("❌ No camera devices found in /dev/")
                self.settings_view.log_area.setStyleSheet("color: #ff5555;")
                return

            # 2. Check Permissions
            import stat
            problematic = []
            for v in videos:
                path = f"/dev/{v}"
                try:
                    st = os.stat(path)
                    mode = st.st_mode
                    # Check if group readable/writable
                    if not (mode & stat.S_IRGRP and mode & stat.S_IWGRP):
                        problematic.append(v)
                except:
                    problematic.append(v)
            
            if problematic:
                self.settings_view.log_area.setText(f"⚠️ Permission issue on: {', '.join(problematic)}")
                self.settings_view.log_area.setStyleSheet("color: #ffaa00;")
            else:
                self.settings_view.log_area.setText(f"✅ Hardware OK: Found {len(videos)} devices with correct access.")
                self.settings_view.log_area.setStyleSheet("color: #55ff55;")
                
        except Exception as e:
            self.settings_view.log_area.setText(f"❌ Probe Failed: {str(e)}")
            self.settings_view.log_area.setStyleSheet("color: #ff5555;")

    def fix_permissions(self):
        reply = QMessageBox.question(self, "Fix Permissions", 
                                   "This will attempt to reset hardware rules and add your user to the 'video' and 'render' groups.\n\n"
                                   "This requires administrative privileges. Proceed?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No: return

        self.settings_view.log_area.setText("🛠️ Applying fixes...")
        
        try:
            user = os.getenv("USER") or os.getenv("SUDO_USER")
            if not user:
                import getpass
                user = getpass.getuser()

            # Execute via pkexec for root privileges
            cmd = f"pkexec bash -c 'gpasswd -a {user} video && gpasswd -a {user} render && udevadm control --reload-rules && udevadm trigger'"
            
            subprocess.Popen(cmd, shell=True)
            self.settings_view.log_area.setText("✅ Fix commands sent. Please REBOOT for group changes to take effect.")
            self.settings_view.log_area.setStyleSheet("color: #55ff55;")
            QMessageBox.information(self, "Fix Applied", "Hardware permission fixes have been triggered.\n\nIMPORTANT: You MUST log out and log back in (or reboot) for group changes to take effect.")
        except Exception as e:
            self.settings_view.log_area.setText(f"❌ Fix Failed: {str(e)}")
            self.settings_view.log_area.setStyleSheet("color: #ff5555;")

    def closeEvent(self, event):
        if self.video_thread: self.video_thread.stop()
        if self.status_thread: self.status_thread.stop()
        event.accept()

if __name__ == "__main__":
    from gui.ui.styles import BACKGROUND_COLOR, ACCENT_CYAN
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BACKGROUND_COLOR))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(SIDEBAR_COLOR))
    palette.setColor(QPalette.Button, QColor(SIDEBAR_COLOR))
    palette.setColor(QPalette.Highlight, QColor(ACCENT_CYAN))
    app.setPalette(palette)
    
    app.setFont(QFont("Inter", 10))
    window = LinuxBonjourGUI()
    window.show()
    sys.exit(app.exec())
