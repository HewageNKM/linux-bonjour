from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QListWidget, QListWidgetItem, 
                             QGroupBox, QCheckBox, QMessageBox)
from PySide6.QtCore import Qt, Signal, Slot
import os
import getpass

from gui.ui.styles import ACCENT_CYAN, TEXT_SECONDARY, GLASS_WHITE

class EnrollmentView(QWidget):
    enroll_signal = Signal()
    save_signal = Signal(str)
    delete_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # 1. Identity List
        list_group = QGroupBox("TRUSTED IDENTITIES")
        list_layout = QVBoxLayout()
        
        self.user_list = QListWidget()
        self.user_list.setMinimumHeight(150)
        list_layout.addWidget(self.user_list)
        
        self.del_btn = QPushButton("REMOVE IDENTITY")
        self.del_btn.setObjectName("dangerBtn")
        self.del_btn.setToolTip("Permanently delete the selected face profile from the system.")
        self.del_btn.clicked.connect(self.on_delete)
        list_layout.addWidget(self.del_btn)
        
        list_group.setLayout(list_layout)
        # 1.5 Camera Preview (Small)
        self.image_label = QLabel("STANDBY")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedSize(320, 240)
        self.image_label.setToolTip("Live preview of the biometric scanner.")
        self.image_label.setStyleSheet(f"background-color: #000; border-radius: 10px; border: 1px solid {GLASS_WHITE};")
        
        # 2. Enrollment Form
        enroll_group = QGroupBox("NEW SIGNATURE")
        enroll_layout = QVBoxLayout()
        enroll_layout.setSpacing(15)
        
        self.u_input = QLineEdit()
        self.u_input.setPlaceholderText("System Username")
        self.u_input.setText(getpass.getuser())
        self.u_input.setMinimumHeight(45)
        self.u_input.setToolTip("Enter the system username this face profile belongs to.")
        enroll_layout.addWidget(self.u_input)
        
        self.auto_capture_cb = QCheckBox("SMART AUTO-CAPTURE")
        self.auto_capture_cb.setChecked(True)
        self.auto_capture_cb.setToolTip("Automatically capture the face signature when a stable face is detected.")
        self.auto_capture_cb.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 11px; font-weight: bold;")
        enroll_layout.addWidget(self.auto_capture_cb)

        self.enroll_btn = QPushButton("ACTIVATE SCANNER")
        self.enroll_btn.setMinimumHeight(50)
        self.enroll_btn.setToolTip("Turn on the camera to begin face detection.")
        self.enroll_btn.clicked.connect(self.enroll_signal.emit)
        enroll_layout.addWidget(self.enroll_btn)
        
        self.save_btn = QPushButton("CAPTURE SIGNATURE")
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.setMinimumHeight(55)
        self.save_btn.setEnabled(False)
        self.save_btn.setToolTip("Manually capture and encrypt the current face embedding.")
        self.save_btn.clicked.connect(lambda: self.save_signal.emit(self.u_input.text()))
        enroll_layout.addWidget(self.save_btn)
        
        self.status_label = QLabel("SYSTEM IDLE")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; padding: 10px; font-size: 11px;")
        enroll_layout.addWidget(self.status_label)
        
        enroll_group.setLayout(enroll_layout)

        # Main Layout Assembly
        layout.addWidget(self.image_label, alignment=Qt.AlignCenter)

        bottom_container = QHBoxLayout()
        bottom_container.setSpacing(20)
        bottom_container.addWidget(list_group, 1)
        bottom_container.addWidget(enroll_group, 1)
        
        layout.addLayout(bottom_container)

    def on_delete(self):
        item = self.user_list.currentItem()
        if item:
            self.delete_signal.emit(item.text())

    def update_user_list(self, users):
        self.user_list.clear()
        for user in sorted(users):
            self.user_list.addItem(QListWidgetItem(user))

    def check_system_user(self, username):
        """Verify if the user exists in /etc/passwd"""
        try:
            import pwd
            pwd.getpwnam(username)
            return True
        except KeyError:
            return False
        except ImportError: # Fallback for non-unix or restricted env
            return True

    def set_enrolling(self, active):
        self.enroll_btn.setText("STOP FEED" if active else "ACTIVATE SCANNER")
        if not active:
            self.status_label.setText("STANDBY")
            self.save_btn.setEnabled(False)
        else:
            self.status_label.setText("INITIALIZING...")
