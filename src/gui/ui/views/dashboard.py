from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QPushButton
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QPixmap
import os

# Import styles
from gui.ui.styles import ACCENT_CYAN, TEXT_SECONDARY, GLASS_WHITE

class DashboardView(QWidget):
    start_daemon_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # 1. System Status Card
        status_group = QGroupBox("SYSTEM MONITOR")
        status_layout = QVBoxLayout()
        
        self.image_label = QLabel("SYSTEM STANDBY")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(450, 350)
        self.image_label.setToolTip("Security monitor showing live biometric scanning status.")
        self.image_label.setStyleSheet(f"""
            background-color: #000; 
            border: 1px solid {GLASS_WHITE}; 
            border-radius: 20px;
            color: {TEXT_SECONDARY};
            font-weight: bold;
            letter-spacing: 2px;
        """)
        status_layout.addWidget(self.image_label)
        
        # We'll need to handle the ScannerOverlay differently 
        # (It will be managed by the main window and placed over this label)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group, 5)

        # 2. Performance & Daemon Quick Actions
        actions_group = QGroupBox("DAEMON CONTROL")
        actions_layout = QHBoxLayout()
        
        self.status_text = QLabel("● DAEMON: UNKNOWN")
        self.status_text.setToolTip("Current operational status of the Linux Bonjour background service.")
        self.status_text.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: bold;")
        actions_layout.addWidget(self.status_text)
        
        self.uptime_text = QLabel("")
        self.uptime_text.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px; margin-left: 10px;")
        actions_layout.addWidget(self.uptime_text)
        
        actions_layout.addStretch()
        
        self.toggle_btn = QPushButton("WAKE DAEMON")
        self.toggle_btn.setObjectName("primaryBtn")
        self.toggle_btn.setMinimumHeight(40)
        self.toggle_btn.setMinimumWidth(150)
        self.toggle_btn.setToolTip("Start and enable the background daemon for automatic authentication.")
        self.toggle_btn.clicked.connect(self.start_daemon_requested.emit)
        self.toggle_btn.hide()
        actions_layout.addWidget(self.toggle_btn)
        
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group, 1)

    def update_status(self, active):
        self.status_text.setText(f"● DAEMON: {'ACTIVE' if active else 'STOPPED'}")
        color = "#03dac6" if active else "#f04747"
        self.status_text.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.toggle_btn.setVisible(not active)
