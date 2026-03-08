import sys
import os
import time
import json
import psutil
import subprocess
import numpy as np
import cv2
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QSlider, QSpinBox, QPushButton, 
                             QGroupBox, QLineEdit, QListWidget, QProgressBar,
                             QListWidgetItem, QMessageBox, QFrame, QComboBox,
                             QScrollArea, QCheckBox)
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

class StatusWorker(QThread):
    status_signal = Signal(bool)
    pam_status_signal = Signal(bool)

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
                
                # PAM status (No sudo needed for status)
                pam_res = subprocess.run([os.path.join(PROJECT_ROOT, "scripts", "setup_pam.sh"), "--status"], 
                                       capture_output=True, text=True, timeout=2)
                # Detection: Look for ENABLED in common-auth
                pam_enabled = "[ENABLED]  common-auth" in pam_res.stdout
                self.pam_status_signal.emit(pam_enabled)
            except:
                self.status_signal.emit(False)
                self.pam_status_signal.emit(False)
            self.msleep(3000) # Check every 3s

    def stop(self):
        self._run_flag = False
        self.wait()

class VideoThread(QThread):
    change_pixmap_signal = Signal(QImage)
    face_detected_signal = Signal(bool, object) # detected, face_obj

    def __init__(self, model_name):
        super().__init__()
        self._run_flag = True
        self.model_name = model_name
        self.app = None

    def run(self):
        # Initialize AI inside thread
        if not self.app:
            self.app = FaceAnalysis(name=self.model_name, providers=['CPUExecutionProvider'])
            self.app.prepare(ctx_id=0, det_size=(320, 320))

        cam = IRCamera()
        while self._run_flag:
            frame = cam.get_frame()
            if frame is not None:
                faces = self.app.get(frame)
                detected = len(faces) > 0
                
                # Draw on frame
                display_frame = frame.copy()
                face_obj = None
                if detected:
                    face_obj = faces[0]
                    bbox = face_obj.bbox.astype(int)
                    cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                    cv2.putText(display_frame, f"Face Detected", (bbox[0], bbox[1]-10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
                # Convert to QImage (RGB for Qt)
                height, width, channel = display_frame.shape
                bytes_per_line = 3 * width
                q_img = QImage(display_frame.data, width, height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
                
                self.change_pixmap_signal.emit(q_img)
                self.face_detected_signal.emit(detected, face_obj)
            else:
                self.face_detected_signal.emit(False, None)
            
            self.msleep(10)
        
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
        self.scan_line_y = (self.scan_line_y + 5) % (self.parent().height() or 400)
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QColor, QRadialGradient
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Corner brackets
        w, h = self.width(), self.height()
        pen = QPen(QColor(0, 176, 244, 180), 3)
        painter.setPen(pen)
        
        length = 40
        # Top Left
        painter.drawLine(10, 10, 10 + length, 10)
        painter.drawLine(10, 10, 10, 10 + length)
        # Top Right
        painter.drawLine(w - 10, 10, w - 10 - length, 10)
        painter.drawLine(w - 10, 10, w - 10, 10 + length)
        # Bottom Left
        painter.drawLine(10, h - 10, 10 + length, h - 10)
        painter.drawLine(10, h - 10, 10, h - 10 - length)
        # Bottom Right
        painter.drawLine(w - 10, h - 10, w - 10 - length, h - 10)
        painter.drawLine(w - 10, h - 10, w - 10, h - 10 - length)

        # Scanning line
        grad = QLinearGradient(0, self.scan_line_y - 10, 0, self.scan_line_y + 10)
        grad.setColorAt(0, QColor(0, 176, 244, 0))
        grad.setColorAt(0.5, QColor(0, 176, 244, 150))
        grad.setColorAt(1, QColor(0, 176, 244, 0))
        painter.fillRect(0, self.scan_line_y - 10, w, 20, grad)

class LinuxHelloGUI(QMainWindow):
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
        
        self.apply_theme()
        self.setup_ui()
        self.start_status_monitoring()

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0c0d10;
            }
            QWidget {
                color: #e0e0e0;
                font-family: 'Inter', 'Segoe UI', 'Roboto', sans-serif;
            }
            QGroupBox {
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                margin-top: 20px;
                font-weight: bold;
                background-color: rgba(255, 255, 255, 0.03);
                padding: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
                color: #bb86fc;
            }
            QPushButton {
                background-color: #1f2128;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 10px 15px;
                font-weight: bold;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #2a2d37;
                border: 1px solid #00b0f4;
            }
            QPushButton:pressed {
                background-color: #121419;
            }
            QPushButton#primaryBtn {
                background-color: #00b0f4;
                color: #000000;
                border: none;
            }
            QPushButton#primaryBtn:hover {
                background-color: #33c0ff;
            }
            QPushButton#dangerBtn {
                background-color: rgba(240, 71, 71, 0.1);
                border: 1px solid #f04747;
                color: #f04747;
            }
            QPushButton#dangerBtn:hover {
                background-color: #f04747;
                color: white;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #16181d;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 8px;
                color: #ffffff;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #00b0f4;
            }
            QSlider::groove:horizontal {
                border: 1px solid #1f2128;
                height: 6px;
                background: #1f2128;
                margin: 2px 0;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #00b0f4;
                border: 1px solid #00b0f4;
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            QListWidget {
                background-color: #16181d;
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 8px;
                outline: none;
                padding: 5px;
            }
            QListWidget::item {
                padding: 10px;
                border-radius: 6px;
                margin: 2px 5px;
            }
            QListWidget::item:selected {
                background-color: rgba(0, 176, 244, 0.2);
                color: #00b0f4;
                border: 1px solid rgba(0, 176, 244, 0.3);
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 8px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.1);
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.2);
            }
            QCheckBox {
                spacing: 10px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid rgba(255, 255, 255, 0.2);
                background-color: #16181d;
            }
            QCheckBox::indicator:checked {
                background-color: #00b0f4;
                image: url(check_mark.png); /* Fallback to styled if no icon */
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
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
                "model_name": "buffalo_s",
                "users_dir": "config/users",
                "camera_index": None,
                "camera_type": "AUTO"
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
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # ---------------- LEFT SIDE: Fixed Header & Scrollable Settings ----------------
        left_side = QWidget()
        left_side_layout = QVBoxLayout(left_side)
        left_side_layout.setContentsMargins(0, 0, 0, 0)

        header_container = QWidget()
        header_hbox = QHBoxLayout(header_container)
        header_hbox.setContentsMargins(10, 10, 10, 20)
        
        if os.path.exists(self.logo_path):
            logo_label = QLabel()
            logo_px = QPixmap(self.logo_path).scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(logo_px)
            header_hbox.addWidget(logo_label)
            
        header_vbox = QVBoxLayout()
        header = QLabel("Linux Bonjour")
        header.setFont(QFont("Inter", 24, QFont.Bold))
        header.setStyleSheet("color: white; letter-spacing: 1px;")
        header_vbox.addWidget(header)
        
        self.status_label = QLabel("● Daemon: Checking...")
        self.status_label.setStyleSheet("color: #ffa000; font-weight: bold; font-size: 11px;")
        header_vbox.addWidget(self.status_label)
        header_hbox.addLayout(header_vbox)
        header_hbox.addStretch()
        
        left_side_layout.addWidget(header_container)
        
        status_h = QHBoxLayout()
        status_h.setContentsMargins(10, 0, 10, 10)
        
        self.start_daemon_btn = QPushButton(" Wake System")
        self.start_daemon_btn.setObjectName("primaryBtn")
        self.start_daemon_btn.setMinimumHeight(35)
        self.start_daemon_btn.clicked.connect(self.on_start_daemon)
        self.start_daemon_btn.hide()
        status_h.addWidget(self.start_daemon_btn)
        status_h.addStretch()
        
        left_side_layout.addLayout(status_h)

        # Scroll Area for the rest of the left side
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setStyleSheet("background: transparent;")
        
        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 0, 10, 0)
        settings_layout.setSpacing(15)
        
        # 1. System Integration Group
        system_group = QGroupBox("System Integration")
        system_layout = QVBoxLayout()
        self.pam_toggle = QCheckBox("Enable Face Unlock (System-wide)")
        self.pam_toggle.setStyleSheet("font-weight: bold; padding: 5px;")
        self.pam_toggle.stateChanged.connect(self.on_pam_toggle_changed)
        system_layout.addWidget(self.pam_toggle)
        system_layout.addWidget(QLabel("<i>Active security for Login, Sudo, and Lock Screen.</i>"))
        system_group.setLayout(system_layout)
        settings_layout.addWidget(system_group)

        # 2. Security Settings Group
        config_group = QGroupBox("Security Settings")
        config_layout = QVBoxLayout()
        config_layout.addWidget(QLabel("<b>Match Threshold</b>"))
        t_layout = QHBoxLayout()
        self.t_slider = QSlider(Qt.Horizontal)
        self.t_slider.setRange(0, 100)
        self.t_slider.setValue(int(self.config.get("threshold", 0.45) * 100))
        self.t_label = QLabel(f"{self.config.get('threshold', 0.45):.2f}")
        self.t_slider.valueChanged.connect(self.on_threshold_changed)
        t_layout.addWidget(self.t_slider)
        t_layout.addWidget(self.t_label)
        config_layout.addLayout(t_layout)
        
        self.global_unlock_cb = QCheckBox("Global Face Unlock (Any Enrolled Face)")
        self.global_unlock_cb.setChecked(self.config.get("global_unlock", False))
        self.global_unlock_cb.setToolTip("Allows any person whose face is enrolled to authenticate as any user.\nUse only in trusted environments.")
        self.global_unlock_cb.setStyleSheet("font-weight: bold; padding: 5px;")
        config_layout.addWidget(self.global_unlock_cb)
        
        config_layout.addWidget(QLabel("<b>AI Model</b>"))
        self.m_combo = QComboBox()
        self.m_combo.addItems(["buffalo_s", "buffalo_m", "buffalo_l", "antelopev2"])
        self.m_combo.setCurrentText(self.config.get("model_name", "buffalo_s"))
        config_layout.addWidget(self.m_combo)
        
        sub_layout = QHBoxLayout()
        c_vbox = QVBoxLayout()
        c_vbox.addWidget(QLabel("<b>Cooldown (s)</b>"))
        self.c_spin = QSpinBox()
        self.c_spin.setRange(0, 3600)
        self.c_spin.setValue(self.config.get("cooldown_time", 60))
        c_vbox.addWidget(self.c_spin)
        sub_layout.addLayout(c_vbox)
        f_vbox = QVBoxLayout()
        f_vbox.addWidget(QLabel("<b>Max Failures</b>"))
        self.f_spin = QSpinBox()
        self.f_spin.setRange(1, 20)
        self.f_spin.setValue(self.config.get("max_failures", 5))
        f_vbox.addWidget(self.f_spin)
        sub_layout.addLayout(f_vbox)
        config_layout.addLayout(sub_layout)
        config_group.setLayout(config_layout)
        settings_layout.addWidget(config_group)
        
        # 3. Hardware Settings
        hw_group = QGroupBox("Hardware Settings")
        hw_layout = QVBoxLayout()
        hw_layout.addWidget(QLabel("<b>Camera Selection</b>"))
        self.cam_type_combo = QComboBox()
        self.cam_type_combo.addItems(["AUTO", "IR", "RGB"])
        self.cam_type_combo.setCurrentText(self.config.get("camera_type", "AUTO"))
        hw_layout.addWidget(self.cam_type_combo)
        cam_idx_layout = QHBoxLayout()
        cam_idx_layout.addWidget(QLabel("Index (-1=Auto)"))
        self.cam_idx_spin = QSpinBox()
        self.cam_idx_spin.setRange(-1, 10)
        idx = self.config.get("camera_index")
        self.cam_idx_spin.setValue(-1 if idx is None else idx)
        cam_idx_layout.addWidget(self.cam_idx_spin)
        hw_layout.addLayout(cam_idx_layout)
        hw_group.setLayout(hw_layout)
        settings_layout.addWidget(hw_group)

        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Settings")
        self.apply_btn.setObjectName("primaryBtn")
        self.apply_btn.clicked.connect(self.apply_settings)
        self.reset_btn = QPushButton("Reset Defaults")
        self.reset_btn.clicked.connect(self.reset_settings)
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.apply_btn)
        settings_layout.addLayout(btn_layout)
        
        # 5. Users
        user_group = QGroupBox("Registered Identities")
        user_layout = QVBoxLayout()
        self.user_list = QListWidget()
        self.refresh_users()
        user_layout.addWidget(self.user_list)
        del_btn = QPushButton("Remove Identity")
        del_btn.setObjectName("dangerBtn")
        del_btn.clicked.connect(self.delete_user)
        user_layout.addWidget(del_btn)
        user_group.setLayout(user_layout)
        settings_layout.addWidget(user_group)
        
        left_scroll.setWidget(settings_container)
        left_side_layout.addWidget(left_scroll)

        # ---------------- RIGHT SIDE: Fixed Live Feed & Enrollment ----------------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        feed_group = QGroupBox("Security Monitor")
        feed_layout = QVBoxLayout()
        self.image_label = QLabel("System Standby")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(450, 350)
        self.image_label.setStyleSheet("""
            background-color: #000; 
            border: 2px solid rgba(0, 176, 244, 0.3); 
            border-radius: 15px;
            color: rgba(255, 255, 255, 0.3);
            font-weight: bold;
        """)
        feed_layout.addWidget(self.image_label)
        
        # Overlay for Holographic Scanner
        self.scanner_overlay = ScannerOverlay(self.image_label)
        self.scanner_overlay.setGeometry(0, 0, 450, 350)
        self.scanner_overlay.hide()
        
        feed_group.setLayout(feed_layout)
        right_layout.addWidget(feed_group)
        
        enroll_group = QGroupBox("New Enrollment")
        enroll_layout = QVBoxLayout()
        self.u_input = QLineEdit()
        self.u_input.setPlaceholderText("Enter System Username")
        # Auto-fill with system username
        import getpass
        self.u_input.setText(getpass.getuser())
        self.u_input.setStyleSheet("padding: 8px; background-color: #40444b; border-radius: 5px;")
        enroll_layout.addWidget(self.u_input)
        
        warning_label = QLabel("⚠️ Important: Name must match your system username exactly.")
        warning_label.setStyleSheet("color: #ffa000; font-size: 10px;")
        enroll_layout.addWidget(warning_label)
        
        self.auto_capture_cb = QCheckBox("Enable Auto-Capture")
        self.auto_capture_cb.setChecked(True)
        self.auto_capture_cb.setStyleSheet("color: #00b0f4; font-size: 11px;")
        enroll_layout.addWidget(self.auto_capture_cb)

        self.enroll_btn = QPushButton("Access Camera")
        self.enroll_btn.setMinimumHeight(45)
        self.enroll_btn.clicked.connect(self.toggle_video)
        enroll_layout.addWidget(self.enroll_btn)
        self.save_enroll_btn = QPushButton("Capture Signature")
        self.save_enroll_btn.setObjectName("primaryBtn")
        self.save_enroll_btn.setMinimumHeight(50)
        self.save_enroll_btn.setEnabled(False)
        self.save_enroll_btn.clicked.connect(self.save_identity)
        enroll_layout.addWidget(self.save_enroll_btn)
        self.enroll_status = QLabel("Ready for scan")
        self.enroll_status.setAlignment(Qt.AlignCenter)
        self.enroll_status.setStyleSheet("color: rgba(255, 255, 255, 0.5); padding: 5px;")
        enroll_layout.addWidget(self.enroll_status)
        enroll_group.setLayout(enroll_layout)
        right_layout.addWidget(enroll_group)
        
        main_layout.addWidget(left_side, 1)
        main_layout.addWidget(right_panel, 1)
        self.setCentralWidget(main_content)

    def start_status_monitoring(self):
        self.status_thread = StatusWorker()
        self.status_thread.status_signal.connect(self.update_status_label)
        self.status_thread.pam_status_signal.connect(self.update_pam_toggle)
        self.status_thread.start()

    def update_status_label(self, active):
        self.status_label.setText(f"● Daemon: {'ACTIVE' if active else 'STOPPED'}")
        color = "#03dac6" if active else "#f04747"
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 11px;")
        
        # Toggle button visibility
        if active:
            self.start_daemon_btn.hide()
        else:
            self.start_daemon_btn.show()

    @Slot(bool)
    def update_pam_toggle(self, enabled):
        # Only update if we are not currently processsing a user click
        # AND if the state has actually changed from what we last confirmed
        if not self.pam_updating and enabled != self.last_known_pam_state:
            self.last_known_pam_state = enabled # Store first
            self.pam_toggle.blockSignals(True)
            self.pam_toggle.setChecked(enabled)
            self.pam_toggle.blockSignals(False)

    def on_pam_toggle_changed(self, state):
        current_bool = (state == 2)
        # Prevent loop: If this trigger matches what we last confirmed, do nothing
        if current_bool == self.last_known_pam_state:
            return

        # Safety Guard: Check for face data before enabling
        if current_bool:
            users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
            if not os.path.exists(users_dir) or not any(f.endswith(".npy") or f.endswith(".enc") for f in os.listdir(users_dir)):
                QMessageBox.critical(self, "No Face Data", "Cannot enable face unlock without any enrolled identities.\nPlease enroll at least one face profile first.")
                self.pam_toggle.blockSignals(True)
                self.pam_toggle.setChecked(False)
                self.pam_toggle.blockSignals(False)
                return

        self.pam_updating = True
        command = "--enable-all" if current_bool else "--disable-all"
        try:
            # Fix: Use pkexec for graphical environments to trigger a password prompt
            script_path = os.path.join(PROJECT_ROOT, "scripts", "setup_pam.sh")
            subprocess.run(["pkexec", script_path, command], check=True)
            self.last_known_pam_state = current_bool
            self.statusBar().showMessage(f"System Security {'Enabled' if current_bool else 'Disabled'}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Elevation Failed", f"Could not update system security settings.\nA password prompt should have appeared to authorize this change.\n\nError: {e}")
            # Revert UI state
            self.pam_toggle.blockSignals(True)
            self.pam_toggle.setChecked(not current_bool)
            self.pam_toggle.blockSignals(False)
        finally:
            self.pam_updating = False

    def on_start_daemon(self):
        try:
            self.statusBar().showMessage("Starting Daemon...", 5000)
            # Start and ENABLE for persistence
            subprocess.run(["pkexec", "systemctl", "enable", "--now", "linux-bonjour"], check=True)
            self.statusBar().showMessage("Daemon Started and Enabled! 🎉", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Service Error", f"Failed to start daemon: {e}")
            self.statusBar().showMessage("Start Failed ❌", 5000)

    def on_threshold_changed(self, value):
        self.t_label.setText(f"{value/100:.2f}")

    def reset_settings(self):
        self.load_config()
        self.t_slider.setValue(int(self.config.get("threshold", 0.45) * 100))
        self.m_combo.setCurrentText(self.config.get("model_name", "buffalo_s"))
        self.c_spin.setValue(self.config.get("cooldown_time", 60))
        self.f_spin.setValue(self.config.get("max_failures", 5))
        idx = self.config.get("camera_index")
        self.cam_idx_spin.setValue(-1 if idx is None else idx)
        self.cam_type_combo.setCurrentText(self.config.get("camera_type", "AUTO"))

    def apply_settings(self):
        new_model = self.m_combo.currentText()
        old_model = self.config.get("model_name", "buffalo_s")

        if new_model != old_model:
            reply = QMessageBox.warning(self, "Model Switch Warning", 
                                       f"You are switching the AI engine from '{old_model}' to '{new_model}'.\n\n"
                                       "IMPORTANT: Face signatures are model-specific. Your existing face profiles "
                                       "will NOT work with the new model and you will need to re-enroll them.\n\n"
                                       "Do you want to proceed with the switch?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                self.m_combo.setCurrentText(old_model)
                return

        self.config["threshold"] = self.t_slider.value() / 100
        self.config["model_name"] = new_model
        self.config["cooldown_time"] = self.c_spin.value()
        self.config["max_failures"] = self.f_spin.value()
        idx = self.cam_idx_spin.value()
        self.config["camera_index"] = None if idx == -1 else idx
        self.config["camera_type"] = self.cam_type_combo.currentText()
        self.config["global_unlock"] = self.global_unlock_cb.isChecked()
        self.save_config()
        self.statusBar().showMessage("Settings applied successfully! ✨", 3000)
        
    def refresh_users(self):
        self.user_list.clear()
        users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
        if os.path.exists(users_dir):
            try:
                # Show both .npy and .enc, but only unique names
                files = os.listdir(users_dir)
                users = set()
                for f in files:
                    if f.endswith(".npy") or f.endswith(".enc"):
                        users.add(f.rsplit(".", 1)[0])
                
                for user in sorted(list(users)):
                    item = QListWidgetItem(user)
                    self.user_list.addItem(item)
            except: pass

    def delete_user(self):
        item = self.user_list.currentItem()
        if not item: return
        username = item.text()
        if QMessageBox.question(self, 'Delete', f"Delete {username}?") == QMessageBox.Yes:
            path_enc = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"), f"{username}.enc")
            path_npy = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"), f"{username}.npy")
            
            deleted = False
            if os.path.exists(path_enc):
                os.remove(path_enc)
                deleted = True
            if os.path.exists(path_npy):
                os.remove(path_npy)
                deleted = True
                
            if deleted:
                self.refresh_users()

    @Slot()
    def toggle_video(self):
        if self.video_thread and self.video_thread.isRunning():
            self.stop_video()
        else:
            self.start_video()

    def start_video(self):
        self.enroll_status.setText("Initializing...")
        self.enroll_btn.setText("Stop Feed")
        self.scanner_overlay.show()
        self.video_thread = VideoThread(self.config.get("model_name", "buffalo_s"))
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.face_detected_signal.connect(self.on_face_detected)
        self.video_thread.start()

    def stop_video(self):
        if self.video_thread: self.video_thread.stop()
        self.scanner_overlay.hide()
        self.image_label.setText("System Standby")
        self.image_label.setPixmap(QPixmap())
        self.enroll_btn.setText("Start Feed")
        self.enroll_status.setText("Standby")
        self.save_enroll_btn.setEnabled(False)

    @Slot(QImage)
    def update_image(self, q_img):
        pixmap = QPixmap.fromImage(q_img)
        target_size = self.image_label.size()
        self.image_label.setPixmap(pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.scanner_overlay.resize(target_size) # Keep overlay synced

    @Slot(bool, object)
    def on_face_detected(self, detected, face_obj):
        now = time.time()
        
        if detected and face_obj is not None:
            self.current_face_embedding = face_obj.normed_embedding
            self.save_enroll_btn.setEnabled(True)
            self.face_lost_time = None # Reset lost timer
            
            if self.auto_capture_cb.isChecked():
                if self.face_detect_start_time is None:
                    print(f"[DEBUG] Auto-capture timer started at {now}")
                    self.face_detect_start_time = now
                
                elapsed = now - self.face_detect_start_time
                remaining = max(0, self.capture_delay - elapsed)
                
                if remaining > 0:
                    self.enroll_status.setText(f"<font color='#00b0f4' size='5'><b>LOCKING ON... {remaining:.1f}s</b></font><br><font color='#888888'>(or click button below to skip)</font>")
                else:
                    print(f"[DEBUG] Auto-capture triggered!")
                    self.enroll_status.setText("<font color='#03dac6' size='5'><b>SIGNATURE CAPTURED!</b></font>")
                    self.face_detect_start_time = None 
                    self.save_identity()
            else:
                self.enroll_status.setText("<font color='#4CAF50' size='4'><b>FACE READY</b></font><br><font color='#888888'>Click 'Capture Signature'</font>")
        else:
            # Face lost - check grace period
            if self.face_detect_start_time is not None:
                if self.face_lost_time is None:
                    self.face_lost_time = now
                    print("[DEBUG] Face lost, starting grace period...")
                
                lost_for = now - self.face_lost_time
                if lost_for > self.grace_period:
                    print(f"[DEBUG] Grace period expired ({lost_for:.1f}s), resetting timer.")
                    self.enroll_status.setText("<font color='#f44336'>SEARCHING FOR FACE...</font>")
                    self.save_enroll_btn.setEnabled(False)
                    self.face_detect_start_time = None
                    self.face_lost_time = None
                else:
                    self.enroll_status.setText(f"<font color='#ff9800'><b>STAND STILL (RESCANNING...)</b></font>")
            else:
                self.enroll_status.setText("<font color='#888888'>POSITION FACE IN FRAME</font>")
                self.save_enroll_btn.setEnabled(False)

    def save_identity(self):
        username = self.u_input.text().strip()
        if not username:
            QMessageBox.warning(self, "Validation Error", "Please enter a username.")
            return

        # Sanitize username (alphanumeric, underscores, hyphens)
        import re
        if not re.match(r"^[a-zA-Z0-9_-]+$", username):
            QMessageBox.warning(self, "Validation Error", "Username contains illegal characters.\nOnly alphanumeric, underscores, and hyphens are allowed.")
            return

        if self.current_face_embedding is None:
            QMessageBox.warning(self, "No Face Detected", "Please start the live capture and look at the camera first.")
            return

        users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
        path_enc = os.path.join(users_dir, f"{username}.enc")
        path_npy = os.path.join(users_dir, f"{username}.npy")

        # Overwrite Protection
        if os.path.exists(path_enc) or os.path.exists(path_npy):
            reply = QMessageBox.question(self, "Overwrite Identity", 
                                       f"An identity named '{username}' already exists. Overwrite it?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return

        try:
            print(f"[DEBUG] Ensuring directory exists: {users_dir}")
            os.makedirs(users_dir, exist_ok=True)
            
            # Encrypt the embedding
            print(f"[DEBUG] Preparing embedding for encryption...")
            buffer = io.BytesIO()
            np.save(buffer, self.current_face_embedding)
            embedding_bytes = buffer.getvalue()
            print(f"[DEBUG] Embedding size: {len(embedding_bytes)} bytes")
            
            print(f"[DEBUG] Encrypting data...")
            encrypted_data = encrypt_data(embedding_bytes)
            print(f"[DEBUG] Encryption successful, size: {len(encrypted_data)} bytes")
            
            print(f"[DEBUG] Writing to file: {path_enc}")
            with open(path_enc, 'wb') as ef:
                ef.write(encrypted_data)
                
            # If an old .npy exists, remove it after encryption
            if os.path.exists(path_npy):
                print(f"[DEBUG] Removing legacy unencrypted file: {path_npy}")
                os.remove(path_npy)
                
            self.refresh_users()
            self.stop_video()
            self.u_input.clear()
            self.statusBar().showMessage(f"Identity '{username}' saved successfully! ✅", 3000)
            print(f"[DEBUG] Enrollment for '{username}' COMPLETED successfully.")
        except Exception as e:
            import traceback
            err_details = traceback.format_exc()
            print(f"[DEBUG] CRITICAL ERROR DURING SAVE:\n{err_details}")
            QMessageBox.critical(self, "Save Error", f"Could not save identity: {e}\n\nCheck terminal for full trace.")

    def closeEvent(self, event):
        if self.video_thread: self.video_thread.stop()
        if self.status_thread: self.status_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = QPalette()
    bg = QColor(44, 47, 51)
    palette.setColor(QPalette.Window, bg)
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(35, 39, 42))
    palette.setColor(QPalette.Button, QColor(64, 68, 75))
    palette.setColor(QPalette.Highlight, QColor(0, 176, 244))
    app.setPalette(palette)
    app.setFont(QFont("Inter", 10))
    window = LinuxHelloGUI()
    window.show()
    sys.exit(app.exec())
