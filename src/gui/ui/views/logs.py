from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTextEdit, 
                             QPushButton, QLabel, QHBoxLayout)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
import subprocess

# Import styles
from gui.ui.styles import ACCENT_CYAN, TEXT_SECONDARY, GLASS_WHITE

class LogsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
        # Auto-refresh Timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fetch_logs)
        self.timer.start(5000) # Every 5 seconds
        
        self.fetch_logs()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        
        # Header
        header_layout = QHBoxLayout()
        header = QLabel("SYSTEM JOURNAL")
        header.setFont(QFont("Inter", 18, QFont.Bold))
        header.setStyleSheet(f"color: white;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        self.refresh_btn = QPushButton("REFRESH")
        self.refresh_btn.setFixedSize(120, 35)
        self.refresh_btn.setStyleSheet(f"font-size: 11px; font-weight: bold;")
        self.refresh_btn.clicked.connect(self.fetch_logs)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Log Display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: #05060a;
                border: 1px solid {GLASS_WHITE};
                border-radius: 12px;
                color: #8a8fb5;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                padding: 15px;
            }}
        """)
        layout.addWidget(self.log_display)

    def fetch_logs(self):
        try:
            # Fetch last 100 lines of linux-bonjour service logs
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
