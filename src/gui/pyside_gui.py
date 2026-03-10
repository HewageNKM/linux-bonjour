import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QStackedWidget,
                             QFrame, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QIcon, QFont

# Add project root to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(os.path.join(PROJECT_ROOT, "src"))

from gui.ui.views.dashboard import DashboardView
from gui.ui.views.enrollment import EnrollmentView
from gui.ui.views.settings import SettingsView
import json

ACCENT_CYAN = "#00b0f4"
ACCENT_BLUE = "#1E90FF"
BG_DARK = "#0f111a"
CARD_BG = "#1A1C2E"

class LinuxBonjourGUI(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self.config = config or {}
        self.setWindowTitle("Linux Bonjour - Advanced Face Security")
        
        # Make the window responsive
        self.setMinimumSize(1000, 700)
        # Allow maximization and resizing
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint | Qt.Window)
        
        self.setStyleSheet(f"background-color: {BG_DARK}; color: white; font-family: 'Segoe UI', sans-serif;")
        
        # Load Config - Prioritize user local, then fallback to project/system
        self.config = {}
        user_config = os.path.expanduser("~/.linux-bonjour/config.json")
        system_config = os.path.normpath(os.path.join(PROJECT_ROOT, "config", "config.json"))
        
        config_path = user_config if os.path.exists(user_config) else system_config
        
        try:
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    self.config = json.load(f)
                    print(f"Loaded config from {config_path}")
        except Exception as e:
            print(f"Error loading config: {e}")
        self.setup_ui()
        
    def setup_ui(self):
        # Main Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.setup_sidebar()
        self.setup_content_area()
        
    def setup_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(260)
        self.sidebar.setStyleSheet(f"background-color: #0d0f17; border-right: 1px solid #15ffffff;")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(25, 50, 25, 40)
        sidebar_layout.setSpacing(12)
        
        # App Title
        title_top = QLabel("LINUX")
        title_top.setStyleSheet("color: white; font-size: 14px; font-weight: bold; letter-spacing: 5px;")
        sidebar_layout.addWidget(title_top, alignment=Qt.AlignCenter)
        
        title_main = QLabel("BONJOUR")
        title_main.setFont(QFont("Segoe UI", 26, QFont.Bold))
        title_main.setStyleSheet(f"color: {ACCENT_CYAN}; margin-bottom: 40px;")
        sidebar_layout.addWidget(title_main, alignment=Qt.AlignCenter)
        
        # Nav Buttons
        self.nav_btns = []
        self.add_nav_button("DASHBOARD", 0, sidebar_layout)
        self.add_nav_button("ENROLLMENT", 1, sidebar_layout)
        self.add_nav_button("SETTINGS", 2, sidebar_layout)
        self.add_nav_button("SYSTEM LOGS", 3, sidebar_layout)
        
        sidebar_layout.addStretch()
        
        # Version Info
        version = QLabel("v1.3.0 Stable")
        version.setStyleSheet("color: #4a4d6d; font-size: 11px; font-weight: 500;")
        sidebar_layout.addWidget(version, alignment=Qt.AlignCenter)
        
        self.main_layout.addWidget(self.sidebar)
        
    def add_nav_button(self, text, index, layout):
        btn = QPushButton(text)
        btn.setFixedHeight(54)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 12px;
                text-align: left;
                padding-left: 20px;
                color: #8a8fb5;
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background-color: #1a1e2e;
                color: white;
            }}
            QPushButton[active="true"] {{
                background-color: {ACCENT_BLUE}20;
                color: {ACCENT_CYAN};
                border-left: 5px solid {ACCENT_CYAN};
            }}
        """)
        btn.clicked.connect(lambda: self.switch_tab(index))
        layout.addWidget(btn)
        self.nav_btns.append(btn)
        if index == 0:
            btn.setProperty("active", "true")
            
    def setup_content_area(self):
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {BG_DARK};")
        
        # Real Widgets (Unified UI)
        self.dashboard_view = DashboardView()
        self.enrollment_view = EnrollmentView()
        self.settings_view = SettingsView()
        
        # Initial config sync
        self.settings_view.update_ui_from_config(self.config)
        
        # Connect settings signals
        self.settings_view.config_changed.connect(self.apply_config)
        
        self.stack.addWidget(self.dashboard_view)
        self.stack.addWidget(self.enrollment_view)
        self.stack.addWidget(self.settings_view)
            
        self.main_layout.addWidget(self.stack)
        
    def apply_config(self, config):
        self.config = config
        user_config = os.path.expanduser("~/.linux-bonjour/config.json")
        try:
            with open(user_config, "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_btns):
            btn.setProperty("active", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LinuxBonjourGUI()
    window.show()
    sys.exit(app.exec())
