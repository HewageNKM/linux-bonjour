from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTextEdit, 
                             QPushButton, QLabel, QHBoxLayout)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
import subprocess

ACCENT_BLUE = "#007bff"
CARD_BG = "#1A1C1E"

class LogsWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        
        # Header
        header_layout = QHBoxLayout()
        header = QLabel("SYSTEM LOGS")
        header.setFont(QFont("Segoe UI", 26, QFont.Bold))
        header.setStyleSheet(f"color: {ACCENT_BLUE};")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        self.refresh_btn = QPushButton("REFRESH")
        self.refresh_btn.setFixedSize(120, 35)
        self.refresh_btn.setStyleSheet(f"background-color: transparent; color: {ACCENT_BLUE}; border: 1px solid {ACCENT_BLUE}; border-radius: 5px; font-weight: bold;")
        self.refresh_btn.clicked.connect(self.fetch_logs)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Log Display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: #05060a;
                border: 1px solid #20ffffff;
                border-radius: 10px;
                color: #a0a0ff;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                padding: 15px;
            }}
        """)
        layout.addWidget(self.log_display)
        
        # Auto-refresh Timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fetch_logs)
        self.timer.start(5000) # Every 5 seconds
        
        self.fetch_logs()
        
    def fetch_logs(self):
        try:
            # Fetch last 50 lines of linux-bonjour service logs
            res = subprocess.run(
                ["journalctl", "-u", "linux-bonjour", "-n", "100", "--no-pager"],
                capture_output=True, text=True
            )
            logs = res.stdout.strip()
            if not logs:
                logs = "--- No logs found for linux-bonjour service ---"
            
            # Keep scroll position if at bottom
            scrollbar = self.log_display.verticalScrollBar()
            at_bottom = scrollbar.value() == scrollbar.maximum()
            
            self.log_display.setPlainText(logs)
            
            if at_bottom:
                scrollbar.setValue(scrollbar.maximum())
                
        except Exception as e:
            self.log_display.setPlainText(f"Error fetching logs: {e}")
