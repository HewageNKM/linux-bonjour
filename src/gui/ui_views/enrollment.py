import os
import sys
import json
import threading
import time
import io
import subprocess
import numpy as np
import cv2
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QLineEdit, QListWidget,
                             QMessageBox, QCheckBox, QSizePolicy, QListWidgetItem)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QImage, QPixmap
from insightface.app import FaceAnalysis
from daemon.camera import IRCamera
from daemon.crypto_utils import encrypt_data, decrypt_data

# Resolve Project Root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

ACCENT_BLUE = "#007bff"
ERROR_RED = "#f04747"
CARD_BG = "#1A1C1E"

class EnrollmentWidget(QWidget):
    def __init__(self, config=None):
        super().__init__()
        self.config = config or {}
        self.video_running = False
        self.ai_thread_running = False
        self.cam = None
        self.face_analyzer = None
        
        # State
        self.latest_bbox = None
        self.current_face_embedding = None
        self.ai_frame = None
        self.ai_frame_lock = threading.Lock()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        
        # Header
        header = QLabel("ENROLLMENT")
        header.setFont(QFont("Segoe UI", 26, QFont.Bold))
        header.setStyleSheet(f"color: {ACCENT_BLUE};")
        layout.addWidget(header)
        
        content = QHBoxLayout()
        
        # Left: Identity List
        left_panel = QFrame()
        left_panel.setStyleSheet(f"background-color: {CARD_BG}; border-radius: 15px; border: 1px solid #20ffffff;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("ENROLLED IDENTITIES"))
        
        self.user_list = QListWidget()
        self.user_list.setStyleSheet("""
            QListWidget {
                border: none; 
                background: transparent; 
                color: white; 
                font-size: 14px;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #10ffffff;
            }
        """)
        left_layout.addWidget(self.user_list)
        
        delete_btn = QPushButton("DELETE SELECTED")
        delete_btn.setStyleSheet(f"background-color: transparent; color: {ACCENT_BLUE}; border: 1px solid {ACCENT_BLUE}; border-radius: 5px; font-weight: bold;")
        delete_btn.clicked.connect(self.delete_identity)
        left_layout.addWidget(delete_btn)
        
        content.addWidget(left_panel, 1)
        
        # Right: Scanner
        right_panel = QFrame()
        right_panel.setStyleSheet(f"background-color: {CARD_BG}; border-radius: 15px; border: 1px solid #20ffffff;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setAlignment(Qt.AlignCenter)
        
        self.preview_lbl = QLabel()
        self.preview_lbl.setMinimumSize(480, 360)
        self.preview_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self.preview_lbl)
        
        self.status_lbl = QLabel("POSITION YOUR FACE IN THE CENTER")
        self.status_lbl.setStyleSheet("color: #9499ff;")
        right_layout.addWidget(self.status_lbl, alignment=Qt.AlignCenter)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username (must exist on system)...")
        self.username_input.setFixedHeight(40)
        self.username_input.setStyleSheet("background: #0a0c14; border: 1px solid #20ffffff; color: white; padding: 5px; border-radius: 5px;")
        right_layout.addWidget(self.username_input)
        
        self.auto_capture_cb = QCheckBox("Enable Auto-Capture")
        self.auto_capture_cb.setStyleSheet("color: #8a8fb5;")
        self.auto_capture_cb.setChecked(True)
        right_layout.addWidget(self.auto_capture_cb)
        
        btns = QHBoxLayout()
        self.enroll_btn = QPushButton("START ENROLLMENT")
        self.enroll_btn.setFixedHeight(45)
        self.enroll_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_BLUE};
                color: white;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: #0056b3;
            }}
        """)
        self.enroll_btn.clicked.connect(self.toggle_enrollment)
        
        self.save_btn = QPushButton("SAVE IDENTITY")
        self.save_btn.setEnabled(False)
        self.save_btn.setFixedHeight(45)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_BLUE}88;
                color: white;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:enabled {{
                background-color: {ACCENT_BLUE};
            }}
        """)
        self.save_btn.clicked.connect(self.save_identity)
        
        btns.addWidget(self.enroll_btn)
        btns.addWidget(self.save_btn)
        right_layout.addLayout(btns)
        
        content.addWidget(right_panel, 2)
        layout.addLayout(content)
        
        # Video Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        
        self.refresh_identities()

    def refresh_identities(self):
        self.user_list.clear()
        try:
            model_name = self.config.get("model_name", "buffalo_s")
            # Locations to scan
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
            
            self.user_list.addItems(sorted(list(unique_users)))
        except Exception as e:
            print(f"Error refresh_identities: {e}")

    def toggle_enrollment(self):
        # Validation: Ensure username is provided before starting camera
        username = self.username_input.text().strip()
        if not self.video_running and not username:
            QMessageBox.warning(self, "Invalid Request", "Please enter a valid system username before starting the enrollment scanner.")
            return

        if not self.video_running:
            self.cam = IRCamera(config=self.config)
            self.video_running = True
            self.ai_thread_running = True
            self.latest_bbox = None
            self.current_face_embedding = None
            
            # Start Worker Threads
            threading.Thread(target=self.ai_worker, daemon=True).start()
            self.timer.start(33) # ~30 FPS
            
            self.enroll_btn.setText("STOP SCANNER")
            self.enroll_btn.setStyleSheet(f"background-color: {ERROR_RED}; color: white; border-radius: 8px; font-weight: bold;")
        else:
            self.stop_enrollment()

    def stop_enrollment(self):
        self.video_running = False
        self.ai_thread_running = False
        self.timer.stop()
        if self.cam: 
            self.cam.release()
            self.cam = None
        self.enroll_btn.setText("START ENROLLMENT")
        self.enroll_btn.setStyleSheet(f"background-color: {ACCENT_BLUE}; color: white; border-radius: 8px; font-weight: bold;")
        self.preview_lbl.clear()
        self.save_btn.setEnabled(False)
        self.status_lbl.setText("POSITION YOUR FACE IN THE CENTER")
        self.status_lbl.setStyleSheet("color: #9499ff;")

    def ai_worker(self):
        models_dir = "/usr/share/linux-bonjour/models"
        if not self.face_analyzer:
            try:
                self.face_analyzer = FaceAnalysis(name=self.config.get("model_name", "buffalo_s"), 
                                                root=models_dir, providers=['CPUExecutionProvider'])
                self.face_analyzer.prepare(ctx_id=0, det_size=(320, 320))
            except Exception as e:
                print(f"AI Worker failed to load models: {e}")
                return

        while self.ai_thread_running:
            process_frame = None
            with self.ai_frame_lock:
                if self.ai_frame is not None:
                    process_frame = self.ai_frame.copy()
                    self.ai_frame = None
            
            if process_frame is not None:
                faces = self.face_analyzer.get(process_frame)
                if len(faces) > 0:
                    self.current_face_embedding = faces[0].normed_embedding
                    self.latest_bbox = faces[0].bbox.astype(int)
                else:
                    self.current_face_embedding = None
                    self.latest_bbox = None
            else:
                time.sleep(0.01)

    def update_frame(self):
        if self.cam:
            frame = self.cam.get_frame()
            if frame is not None:
                # Dispatch to AI worker
                with self.ai_frame_lock:
                    self.ai_frame = frame.copy()
                
                # Draw Overlay
                display_frame = frame.copy()
                if self.latest_bbox is not None:
                    bbox = self.latest_bbox
                    cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                    self.save_btn.setEnabled(True)
                    self.status_lbl.setText("FACE SIGNATURE READY ✅")
                    self.status_lbl.setStyleSheet("color: #00ff88;")
                    
                    # Auto-capture
                    if self.auto_capture_cb.isChecked() and self.username_input.text().strip():
                        self.save_identity()
                        return
                else:
                    self.save_btn.setEnabled(False)
                    self.status_lbl.setText("SEARCHING FOR FACE...")
                    self.status_lbl.setStyleSheet("color: #9499ff;")

                # Convert to QImage
                rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_frame.shape
                qt_img = QImage(rgb_frame.data, w, h, ch * w, QImage.Format_RGB888)
                
                # Scale Pixmap to label size keeping aspect ratio
                pixmap = QPixmap.fromImage(qt_img)
                scaled_pixmap = pixmap.scaled(self.preview_lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview_lbl.setPixmap(scaled_pixmap)

    def save_identity(self):
        username = self.username_input.text().strip()
        if not username:
            QMessageBox.warning(self, "Error", "Username is required")
            return
            
        if self.current_face_embedding is None:
            QMessageBox.warning(self, "Error", "No face signature detected!")
            return

        # Stop scanner immediately to prevent looping error dialogs if auto-capture is on
        was_running = self.video_running
        if was_running:
            self.stop_enrollment()

        # System User Validation
        try:
            subprocess.run(["getent", "passwd", username], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            QMessageBox.critical(self, "Error", f"User '{username}' does not exist on this system.")
            return

        # Save Encryption - Use user home to avoid permission errors
        try:
            model_name = self.config.get("model_name", "buffalo_s")
            users_dir = os.path.expanduser(f"~/.linux-bonjour/users/{model_name}")
            os.makedirs(users_dir, exist_ok=True)
            
            buffer = io.BytesIO()
            np.save(buffer, self.current_face_embedding)
            encrypted_data = encrypt_data(buffer.getvalue())
            
            with open(os.path.join(users_dir, f"{username}.enc"), 'wb') as f:
                f.write(encrypted_data)
                
            self.username_input.clear()
            self.refresh_identities()
            QMessageBox.information(self, "Success", f"Successfully enrolled '{username}' locally! 🎉")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save identity: {e}")

    def delete_identity(self):
        item = self.user_list.currentItem()
        if not item: return
        
        username = item.text()
        reply = QMessageBox.question(self, "Confirm Delete", f"Delete identity for '{username}'?", QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            try:
                model_name = self.config.get("model_name", "buffalo_s")
                
                # Search across all directories to delete
                search_dirs = [
                    os.path.expanduser(f"~/.linux-bonjour/users/{model_name}"),
                    os.path.join(PROJECT_ROOT, "config", "users", model_name),
                    f"/usr/share/linux-bonjour/config/users/{model_name}"
                ]
                
                deleted = False
                for users_dir in search_dirs:
                    for ext in [".enc", ".npy"]:
                        path = os.path.join(users_dir, f"{username}{ext}")
                        if os.path.exists(path):
                            try:
                                os.remove(path)
                                deleted = True
                            except PermissionError:
                                QMessageBox.critical(self, "Permission Denied", f"Cannot delete '{username}' from system directory. Requires root.")
                
                if deleted:
                    self.refresh_identities()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete: {e}")
