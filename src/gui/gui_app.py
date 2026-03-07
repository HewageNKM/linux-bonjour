import sys
import os
import json
import psutil
import subprocess
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QSlider, QSpinBox, QPushButton, 
                             QGroupBox, QLineEdit, QListWidget, QProgressBar)
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QPalette, QColor

# Add project root to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(os.path.join(PROJECT_ROOT, "src"))

from daemon.camera import IRCamera
from daemon.sys_info import get_system_specs, suggest_model

class LinuxHelloGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux Hello | Management Console")
        self.setMinimumSize(600, 700)
        self.config_path = os.path.join(PROJECT_ROOT, "config", "config.json")
        self.load_config()
        
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
            self.config = {}

    def save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            self.statusBar().showMessage("Settings Saved!", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"Error saving: {e}", 5000)

    def setup_ui(self):
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        
        # Header
        header = QLabel("Linux Hello")
        header.setFont(QFont("Outfit", 24, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        # Daemon Status
        self.status_label = QLabel("Daemon: Unknown")
        self.status_label.setMargin(10)
        layout.addWidget(self.status_label)
        
        # Config Group
        config_group = QGroupBox("Configuration")
        config_layout = QVBoxLayout()
        
        # Threshold Slider
        t_layout = QHBoxLayout()
        t_layout.addWidget(QLabel("Match Threshold:"))
        self.t_slider = QSlider(Qt.Horizontal)
        self.t_slider.setRange(0, 100)
        self.t_slider.setValue(int(self.config.get("threshold", 0.45) * 100))
        self.t_label = QLabel(f"{self.config.get('threshold', 0.45):.2f}")
        self.t_slider.valueChanged.connect(self.on_threshold_changed)
        t_layout.addWidget(self.t_slider)
        t_layout.addWidget(self.t_label)
        config_layout.addLayout(t_layout)
        
        # Cooldown
        c_layout = QHBoxLayout()
        c_layout.addWidget(QLabel("Security Cooldown (sec):"))
        self.c_spin = QSpinBox()
        self.c_spin.setRange(0, 3600)
        self.c_spin.setValue(self.config.get("cooldown_time", 60))
        c_layout.addWidget(self.c_spin)
        config_layout.addLayout(c_layout)
        
        # Max Failures
        f_layout = QHBoxLayout()
        f_layout.addWidget(QLabel("Max Failures:"))
        self.f_spin = QSpinBox()
        self.f_spin.setRange(1, 20)
        self.f_spin.setValue(self.config.get("max_failures", 5))
        f_layout.addWidget(self.f_spin)
        config_layout.addLayout(f_layout)
        
        save_btn = QPushButton("Apply All Settings")
        save_btn.clicked.connect(self.apply_settings)
        save_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        config_layout.addWidget(save_btn)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # Enrollment Group
        enroll_group = QGroupBox("Identity Enrollment")
        enroll_layout = QVBoxLayout()
        
        u_layout = QHBoxLayout()
        self.u_input = QLineEdit()
        self.u_input.setPlaceholderText("Enter username to enroll...")
        self.enroll_btn = QPushButton("Start Enrollment")
        self.enroll_btn.clicked.connect(self.enroll_user)
        u_layout.addWidget(self.u_input)
        u_layout.addWidget(self.enroll_btn)
        enroll_layout.addLayout(u_layout)
        
        self.enroll_progress = QProgressBar()
        self.enroll_progress.hide()
        enroll_layout.addWidget(self.enroll_progress)
        
        self.enroll_status = QLabel("")
        enroll_layout.addWidget(self.enroll_status)
        
        enroll_group.setLayout(enroll_layout)
        layout.addWidget(enroll_group)
        
        # User List
        self.user_list = QListWidget()
        self.refresh_users()
        layout.addWidget(QLabel("Enrolled Users:"))
        layout.addWidget(self.user_list)
        
        self.setCentralWidget(central_widget)

    def on_threshold_changed(self, value):
        self.t_label.setText(f"{value/100:.2f}")

    def apply_settings(self):
        self.config["threshold"] = self.t_slider.value() / 100
        self.config["cooldown_time"] = self.c_spin.value()
        self.config["max_failures"] = self.f_spin.value()
        self.save_config()
        
    def refresh_users(self):
        self.user_list.clear()
        users_dir = os.path.join(PROJECT_ROOT, self.config.get("users_dir", "config/users"))
        if os.path.exists(users_dir):
            users = [f.replace(".npy", "") for f in os.listdir(users_dir) if f.endswith(".npy")]
            self.user_list.addItems(users)

    def update_status(self):
        # Check systemd service status
        try:
            res = subprocess.run(["systemctl", "is-active", "linux-hello"], capture_output=True, text=True)
            active = res.stdout.strip() == "active"
            self.status_label.setText(f"Daemon: {'ACTIVE' if active else 'STOPPED'}")
            color = "#4CAF50" if active else "#f44336"
            self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        except:
             pass

    def enroll_user(self):
        username = self.u_input.text().strip()
        if not username:
            self.enroll_status.setText("Error: Enter a username")
            return
            
        self.enroll_status.setText("Capturing identity... Please look at the camera.")
        self.enroll_progress.show()
        self.enroll_progress.setRange(0, 0) # Pulsing
        
        # We run the actual enrollment via subprocess to keep GUI responsive
        # and reuse the fixed enroll.py logic
        try:
            cmd = [os.path.join(PROJECT_ROOT, "venv", "bin", "python"), 
                   os.path.join(PROJECT_ROOT, "src", "cli", "enroll.py"), username]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # Simple way to wait without blocking GUI too much (in a real app we'd use QThread)
            # For now, we'll just check status after capture
            QTimer.singleShot(5000, lambda: self.finish_enroll(process, username))
        except Exception as e:
            self.enroll_status.setText(f"Launch Error: {e}")

    def finish_enroll(self, process, username):
        if process.poll() is None:
            # Still running? Wait more
            QTimer.singleShot(2000, lambda: self.finish_enroll(process, username))
            return
            
        self.enroll_progress.hide()
        out, err = process.communicate()
        if "Enrollment Complete" in out:
            self.enroll_status.setText(f"Success! {username} enrolled.")
            self.refresh_users()
        else:
            self.enroll_status.setText(f"Failed: {err or out}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Simple Modern Theme
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)
    
    window = LinuxHelloGUI()
    window.show()
    sys.exit(app.exec())
