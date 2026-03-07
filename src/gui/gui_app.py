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
                             QListWidgetItem, QMessageBox, QFrame, QComboBox)
from PySide6.QtCore import Qt, QTimer, Slot, QThread, Signal, QSize
from PySide6.QtGui import QFont, QPalette, QColor, QImage, QPixmap

# Add project root to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(os.path.join(PROJECT_ROOT, "src"))

from daemon.camera import IRCamera
from daemon.sys_info import get_system_specs, suggest_model
from insightface.app import FaceAnalysis

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
                # Detection
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
                
                # Convert to QImage
                height, width, channel = display_frame.shape
                bytes_per_line = 3 * width
                q_img = QImage(display_frame.data, width, height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
                self.change_pixmap_signal.emit(q_img)
                self.face_detected_signal.emit(detected, face_obj)
            
            self.msleep(30) # ~30 FPS
        
        cam.release()

    def stop(self):
        self._run_flag = False
        self.wait()

class LinuxHelloGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux Hello | Management Console")
        self.setMinimumSize(800, 800)
        self.config_path = os.path.join(PROJECT_ROOT, "config", "config.json")
        self.load_config()
        
        self.video_thread = None
        self.current_face_embedding = None
        
        self.setup_ui()
        
        # Status update timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(2000)
        
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
            self.statusBar().showMessage("Settings Saved & Updated Real-time!", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"Error saving: {e}", 5000)

    def setup_ui(self):
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        
        # Left Panel: Controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Header
        header = QLabel("Linux Hello")
        header.setFont(QFont("Outfit", 24, QFont.Bold))
        left_layout.addWidget(header)
        
        self.status_label = QLabel("Daemon: Unknown")
        left_layout.addWidget(self.status_label)
        
        # Config Group
        config_group = QGroupBox("Security Settings")
        config_layout = QVBoxLayout()
        
        # Threshold
        config_layout.addWidget(QLabel("<b>Match Threshold</b>"))
        config_layout.addWidget(QLabel("<i>How strictly the AI matches your face. Higher means more secure.</i>"))
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
        config_layout.addWidget(QLabel("<i>Bufflo S (Lite) for 8GB RAM, Bufflo L (Precision) for 16GB+.</i>"))
        self.m_combo = QComboBox()
        self.m_combo.addItems(["buffalo_s", "buffalo_l"])
        self.m_combo.setCurrentText(self.config.get("model_name", "buffalo_s"))
        config_layout.addWidget(self.m_combo)
        
        # Cooldown
        config_layout.addWidget(QLabel("<b>Security Cooldown (sec)</b>"))
        config_layout.addWidget(QLabel("<i>Lockout duration after maximum failed attempts.</i>"))
        self.c_spin = QSpinBox()
        self.c_spin.setRange(0, 3600)
        self.c_spin.setValue(self.config.get("cooldown_time", 60))
        config_layout.addWidget(self.c_spin)
        
        # Max Failures
        config_layout.addWidget(QLabel("<b>Max Failures</b>"))
        config_layout.addWidget(QLabel("<i>Attempts allowed before triggering cooldown.</i>"))
        self.f_spin = QSpinBox()
        self.f_spin.setRange(1, 20)
        self.f_spin.setValue(self.config.get("max_failures", 5))
        config_layout.addWidget(self.f_spin)
        
        # Button Box
        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Settings")
        self.apply_btn.clicked.connect(self.apply_settings)
        self.apply_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
        
        self.reset_btn = QPushButton("Reset to Saved")
        self.reset_btn.clicked.connect(self.reset_settings)
        self.reset_btn.setStyleSheet("background-color: #616161; color: white; padding: 8px;")
        
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.apply_btn)
        config_layout.addLayout(btn_layout)
        
        config_group.setLayout(config_layout)
        left_layout.addWidget(config_group)
        
        # User List CRUD
        user_group = QGroupBox("Managed Identities (CRUD)")
        user_layout = QVBoxLayout()
        self.user_list = QListWidget()
        self.refresh_users()
        user_layout.addWidget(self.user_list)
        
        del_btn = QPushButton("Delete Selected User")
        del_btn.clicked.connect(self.delete_user)
        del_btn.setStyleSheet("background-color: #f44336; color: white;")
        user_layout.addWidget(del_btn)
        
        user_group.setLayout(user_layout)
        left_layout.addWidget(user_group)
        
        # Right Panel: Live Feed & Enrollment
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Camera Feed
        feed_group = QGroupBox("Live Security Feed")
        feed_layout = QVBoxLayout()
        self.image_label = QLabel("Camera Feed Inactive")
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
        self.save_enroll_btn.setStyleSheet("background-color: #2196F3; color: white;")
        enroll_layout.addWidget(self.save_enroll_btn)
        
        self.enroll_status = QLabel("Standby")
        self.enroll_status.setAlignment(Qt.AlignCenter)
        enroll_layout.addWidget(self.enroll_status)
        
        enroll_group.setLayout(enroll_layout)
        right_layout.addWidget(enroll_group)
        
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 1)
        
        self.setCentralWidget(central_widget)

    def on_threshold_changed(self, value):
        self.t_label.setText(f"{value/100:.2f}")

    def reset_settings(self):
        self.load_config()
        # Update widgets blindly (logic is simple enough to not need signals blocked usually)
        self.t_slider.setValue(int(self.config.get("threshold", 0.45) * 100))
        self.t_label.setText(f"{self.config.get('threshold', 0.45):.2f}")
        self.c_spin.setValue(self.config.get("cooldown_time", 60))
        self.f_spin.setValue(self.config.get("max_failures", 5))
        self.m_combo.setCurrentText(self.config.get("model_name", "buffalo_s"))
        self.statusBar().showMessage("Settings Reset to last saved state", 3000)

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
            users = [f.replace(".npy", "") for f in os.listdir(users_dir) if f.endswith(".npy")]
            for user in users:
                item = QListWidgetItem(user)
                self.user_list.addItem(item)

    def delete_user(self):
        item = self.user_list.currentItem()
        if not item: return
        
        username = item.text()
        reply = QMessageBox.question(self, 'Confirm Delete', 
                                   f"Are you sure you want to delete face data for '{username}'?",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
            path = os.path.join(users_dir, f"{username}.npy")
            if os.path.exists(path):
                os.remove(path)
                self.refresh_users()
                self.statusBar().showMessage(f"Deleted {username}", 3000)

    def update_status(self):
        try:
            res = subprocess.run(["systemctl", "is-active", "linux-hello"], capture_output=True, text=True)
            active = res.stdout.strip() == "active"
            self.status_label.setText(f"Daemon: {'ACTIVE' if active else 'STOPPED'}")
            color = "#4CAF50" if active else "#f44336"
            self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        except: pass

    @Slot()
    def toggle_video(self):
        if self.video_thread and self.video_thread.isRunning():
            self.stop_video()
        else:
            self.start_video()

    def start_video(self):
        # Prevent conflict by stopping daemon if it's running? 
        # For simplicity, we just try to open. If fails, user will see black.
        self.enroll_status.setText("Initializing Camera & AI...")
        self.enroll_btn.setText("Stop Feed")
        self.video_thread = VideoThread(self.config.get("model_name", "buffalo_s"))
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.face_detected_signal.connect(self.on_face_detected)
        self.video_thread.start()

    def stop_video(self):
        if self.video_thread:
            self.video_thread.stop()
        self.image_label.setText("Camera Feed Inactive")
        self.image_label.setPixmap(QPixmap())
        self.enroll_btn.setText("Start Live Capture")
        self.enroll_status.setText("Standby")
        self.save_enroll_btn.setEnabled(False)

    @Slot(QImage)
    def update_image(self, q_img):
        pixmap = QPixmap.fromImage(q_img)
        self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @Slot(bool, object)
    def on_face_detected(self, detected, face_obj):
        if detected:
            self.enroll_status.setText("<font color='green'>FACE DETECTED - READY TO SAVE</font>")
            self.enroll_status.setProperty("detected", True)
            self.current_face_embedding = face_obj.normed_embedding
            self.save_enroll_btn.setEnabled(True)
        else:
            self.enroll_status.setText("<font color='red'>NO FACE DETECTED</font>")
            self.save_enroll_btn.setEnabled(False)

    def save_identity(self):
        username = self.u_input.text().strip()
        if not username:
            QMessageBox.warning(self, "Error", "Please enter a username.")
            return
            
        if self.current_face_embedding is not None:
            users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
            if not os.path.exists(users_dir): os.makedirs(users_dir)
            
            save_path = os.path.join(users_dir, f"{username}.npy")
            np.save(save_path, self.current_face_embedding)
            
            # Legacy owner sync
            if not os.path.exists(os.path.join(PROJECT_ROOT, "config", "owner.npy")):
                np.save(os.path.join(PROJECT_ROOT, "config", "owner.npy"), self.current_face_embedding)
                
            QMessageBox.information(self, "Success", f"Identity saved for {username}!")
            self.refresh_users()
            self.stop_video()
            self.u_input.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Premium Dark Theme
    app.setStyle("Fusion")
    palette = QPalette()
    dark_gray = QColor(45, 45, 45)
    palette.setColor(QPalette.Window, dark_gray)
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, dark_gray)
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(60, 60, 60))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)
    
    # Global Font
    app.setFont(QFont("Inter", 10))
    
    window = LinuxHelloGUI()
    window.show()
    sys.exit(app.exec())
