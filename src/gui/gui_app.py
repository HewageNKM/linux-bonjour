import sys
import os
import json
import psutil
import subprocess
import numpy as np
import cv2
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QSlider, QSpinBox, QPushButton, 
                             QGroupBox, QLineEdit, QListWidget, QProgressBar,
                             QListWidgetItem, QMessageBox, QFrame, QComboBox,
                             QScrollArea)
from PySide6.QtCore import Qt, QTimer, Slot, QThread, Signal, QSize
from PySide6.QtGui import QFont, QPalette, QColor, QImage, QPixmap

# Add project root to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(os.path.join(PROJECT_ROOT, "src"))

from daemon.camera import IRCamera
from daemon.sys_info import get_system_specs, suggest_model
from insightface.app import FaceAnalysis

class StatusWorker(QThread):
    status_signal = Signal(bool)

    def __init__(self):
        super().__init__()
        self._run_flag = True

    def run(self):
        while self._run_flag:
            try:
                res = subprocess.run(["systemctl", "is-active", "linux-hello"], 
                                   capture_output=True, text=True, timeout=2)
                active = res.stdout.strip() == "active"
                self.status_signal.emit(active)
            except:
                self.status_signal.emit(False)
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
            
            self.msleep(10)
        
        cam.release()

    def stop(self):
        self._run_flag = False
        self.wait()

class LinuxHelloGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux Hello")
        self.setMinimumSize(900, 700)
        self.config_path = os.path.join(PROJECT_ROOT, "config", "config.json")
        self.load_config()
        
        self.video_thread = None
        self.status_thread = None
        self.current_face_embedding = None
        
        self.setup_ui()
        self.start_status_monitoring()
        
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
                "users_dir": "config/users"
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

        # Header
        header = QLabel("Linux Hello")
        header.setFont(QFont("Outfit", 26, QFont.Bold))
        left_side_layout.addWidget(header)
        
        self.status_label = QLabel("Daemon: Checking...")
        self.status_label.setStyleSheet("color: #ffa000; font-weight: bold;")
        left_side_layout.addWidget(self.status_label)

        # Scroll Area for the rest of the left side
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        
        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 0, 10, 0)
        
        # Config Group
        config_group = QGroupBox("Security Settings")
        config_layout = QVBoxLayout()
        
        # Threshold
        config_layout.addWidget(QLabel("<b>Match Threshold</b>"))
        config_layout.addWidget(QLabel("<i>How strictly the AI matches your face.</i>"))
        t_layout = QHBoxLayout()
        self.t_slider = QSlider(Qt.Horizontal)
        self.t_slider.setRange(0, 100)
        self.t_slider.setValue(int(self.config.get("threshold", 0.45) * 100))
        self.t_label = QLabel(f"{self.config.get('threshold', 0.45):.2f}")
        self.t_slider.valueChanged.connect(self.on_threshold_changed)
        t_layout.addWidget(self.t_slider)
        t_layout.addWidget(self.t_label)
        config_layout.addLayout(t_layout)
        
        # Model Selection
        config_layout.addWidget(QLabel("<b>AI Model</b>"))
        config_layout.addWidget(QLabel("<i>Bufflo S (Lite) vs Bufflo L (Precision).</i>"))
        self.m_combo = QComboBox()
        self.m_combo.addItems(["buffalo_s", "buffalo_l"])
        self.m_combo.setCurrentText(self.config.get("model_name", "buffalo_s"))
        config_layout.addWidget(self.m_combo)
        
        # Cooldown
        config_layout.addWidget(QLabel("<b>Security Cooldown (sec)</b>"))
        config_layout.addWidget(QLabel("<i>Lockout duration after failures.</i>"))
        self.c_spin = QSpinBox()
        self.c_spin.setRange(0, 3600)
        self.c_spin.setValue(self.config.get("cooldown_time", 60))
        config_layout.addWidget(self.c_spin)
        
        # Max Failures
        config_layout.addWidget(QLabel("<b>Max Failures</b>"))
        config_layout.addWidget(QLabel("<i>Attempts allowed before lockout.</i>"))
        self.f_spin = QSpinBox()
        self.f_spin.setRange(1, 20)
        self.f_spin.setValue(self.config.get("max_failures", 5))
        config_layout.addWidget(self.f_spin)
        
        # Apply/Reset Buttons
        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Settings")
        self.apply_btn.clicked.connect(self.apply_settings)
        self.apply_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-weight: bold;")
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset_settings)
        self.reset_btn.setStyleSheet("background-color: #616161; color: white; padding: 10px;")
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.apply_btn)
        config_layout.addLayout(btn_layout)
        
        config_group.setLayout(config_layout)
        settings_layout.addWidget(config_group)
        
        # User List CRUD
        user_group = QGroupBox("Managed Identities (CRUD)")
        user_layout = QVBoxLayout()
        self.user_list = QListWidget()
        self.refresh_users()
        user_layout.addWidget(self.user_list)
        del_btn = QPushButton("Delete Selected User")
        del_btn.clicked.connect(self.delete_user)
        del_btn.setStyleSheet("background-color: #f44336; color: white; padding: 8px;")
        user_layout.addWidget(del_btn)
        user_group.setLayout(user_layout)
        settings_layout.addWidget(user_group)
        
        left_scroll.setWidget(settings_container)
        left_side_layout.addWidget(left_scroll)

        # ---------------- RIGHT SIDE: Fixed Live Feed & Enrollment ----------------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Camera Feed
        feed_group = QGroupBox("Live Security Feed")
        feed_layout = QVBoxLayout()
        self.image_label = QLabel("Camera Inactive")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setStyleSheet("background-color: black; border: 2px solid #555;")
        feed_layout.addWidget(self.image_label)
        feed_group.setLayout(feed_layout)
        right_layout.addWidget(feed_group)
        
        # Enrollment
        enroll_group = QGroupBox("New Enrollment")
        enroll_layout = QVBoxLayout()
        self.u_input = QLineEdit()
        self.u_input.setPlaceholderText("Enter username...")
        enroll_layout.addWidget(self.u_input)
        self.enroll_btn = QPushButton("Start Live Capture")
        self.enroll_btn.clicked.connect(self.toggle_video)
        enroll_layout.addWidget(self.enroll_btn)
        self.save_enroll_btn = QPushButton("Save Identity")
        self.save_enroll_btn.setEnabled(False)
        self.save_enroll_btn.clicked.connect(self.save_identity)
        self.save_enroll_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 10px;")
        enroll_layout.addWidget(self.save_enroll_btn)
        self.enroll_status = QLabel("Standby")
        self.enroll_status.setAlignment(Qt.AlignCenter)
        enroll_layout.addWidget(self.enroll_status)
        
        enroll_group.setLayout(enroll_layout)
        right_layout.addWidget(enroll_group)
        
        # Assemble
        main_layout.addWidget(left_side, 1)
        main_layout.addWidget(right_panel, 1)
        
        self.setCentralWidget(main_content)

    def start_status_monitoring(self):
        self.status_thread = StatusWorker()
        self.status_thread.status_signal.connect(self.update_status_label)
        self.status_thread.start()

    @Slot(bool)
    def update_status_label(self, active):
        self.status_label.setText(f"Daemon: {'ACTIVE' if active else 'STOPPED'}")
        color = "#4CAF50" if active else "#f44336"
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def on_threshold_changed(self, value):
        self.t_label.setText(f"{value/100:.2f}")

    def reset_settings(self):
        self.load_config()
        self.t_slider.setValue(int(self.config.get("threshold", 0.45) * 100))
        self.t_label.setText(f"{self.config.get('threshold', 0.45):.2f}")
        self.c_spin.setValue(self.config.get("cooldown_time", 60))
        self.f_spin.setValue(self.config.get("max_failures", 5))
        self.m_combo.setCurrentText(self.config.get("model_name", "buffalo_s"))
        self.statusBar().showMessage("Settings Reset", 3000)

    def apply_settings(self):
        self.config["threshold"] = self.t_slider.value() / 100
        self.config["cooldown_time"] = self.c_spin.value()
        self.config["max_failures"] = self.f_spin.value()
        self.config["model_name"] = self.m_combo.currentText()
        self.save_config()
        
    def refresh_users(self):
        self.user_list.clear()
        users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
        if os.path.exists(users_dir):
            try:
                users = [f.replace(".npy", "") for f in os.listdir(users_dir) if f.endswith(".npy")]
                for user in users:
                    item = QListWidgetItem(user)
                    self.user_list.addItem(item)
            except: pass

    def delete_user(self):
        item = self.user_list.currentItem()
        if not item: return
        username = item.text()
        reply = QMessageBox.question(self, 'Confirm Delete', 
                                   f"Delete identity for '{username}'?",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
            path = os.path.join(users_dir, f"{username}.npy")
            if os.path.exists(path):
                os.remove(path)
                self.refresh_users()

    @Slot()
    def toggle_video(self):
        if self.video_thread and self.video_thread.isRunning():
            self.stop_video()
        else:
            self.start_video()

    def start_video(self):
        self.enroll_status.setText("Initializing...")
        self.enroll_btn.setText("Stop Live Feed")
        self.video_thread = VideoThread(self.config.get("model_name", "buffalo_s"))
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.face_detected_signal.connect(self.on_face_detected)
        self.video_thread.start()

    def stop_video(self):
        if self.video_thread:
            self.video_thread.stop()
        self.image_label.setText("Camera Inactive")
        self.image_label.setPixmap(QPixmap())
        self.enroll_btn.setText("Start Live Capture")
        self.enroll_status.setText("Standby")
        self.save_enroll_btn.setEnabled(False)

    @Slot(QImage)
    def update_image(self, q_img):
        pixmap = QPixmap.fromImage(q_img)
        self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), 
                                               Qt.KeepAspectRatio, 
                                               Qt.SmoothTransformation))

    @Slot(bool, object)
    def on_face_detected(self, detected, face_obj):
        if detected:
            self.enroll_status.setText("<font color='#4CAF50'><b>READY: FACE DETECTED</b></font>")
            self.current_face_embedding = face_obj.normed_embedding
            self.save_enroll_btn.setEnabled(True)
        else:
            self.enroll_status.setText("<font color='#f44336'>SEARCHING...</font>")
            self.save_enroll_btn.setEnabled(False)

    def save_identity(self):
        username = self.u_input.text().strip()
        if not username: return
        if self.current_face_embedding is not None:
            users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
            if not os.path.exists(users_dir): os.makedirs(users_dir)
            save_path = os.path.join(users_dir, f"{username}.npy")
            np.save(save_path, self.current_face_embedding)
            self.refresh_users()
            self.stop_video()
            self.u_input.clear()

    def closeEvent(self, event):
        if self.video_thread: self.video_thread.stop()
        if self.status_thread: self.status_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = QPalette()
    bg = QColor(32, 34, 37)
    palette.setColor(QPalette.Window, bg)
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(47, 49, 54))
    palette.setColor(QPalette.AlternateBase, bg)
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(64, 68, 75))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.Link, QColor(0, 176, 244))
    palette.setColor(QPalette.Highlight, QColor(0, 176, 244))
    app.setPalette(palette)
    app.setFont(QFont("Segoe UI", 9))
    window = LinuxHelloGUI()
    window.show()
    sys.exit(app.exec())
