import os
import sys
import subprocess
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QFrame, QGridLayout, QSizePolicy, QScrollArea)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

# Resolve Project Root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

ACCENT_BLUE = "#007bff"
ACCENT_GREEN = "#00ff88"
ERROR_RED = "#ff4444"
BG_DARK = "#0f111a"
CARD_BG = "#1A1C1E"
TEXT_SECONDARY = "#8a8fb5"

class DashboardWidget(QWidget):
    def __init__(self, config=None):
        super().__init__()
        self.config = config or {}
        
        # Main layout for the scroll area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet(f"background-color: {BG_DARK};")
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(30)
        
        # Header
        header = QLabel("DASHBOARD")
        header.setFont(QFont("Segoe UI", 26, QFont.Bold))
        header.setStyleSheet(f"color: {ACCENT_BLUE};")
        layout.addWidget(header)
        
        # Stats Grid
        self.stats_layout = QGridLayout()
        self.stats_layout.setSpacing(20)
        
        # Security Health Score (Large Card)
        self.health_score_lbl = QLabel("100")
        self.health_score_lbl.setStyleSheet("color: white; font-size: 32px; font-weight: 900;")
        self.health_card = self.create_stats_card("SECURITY HEALTH", self.health_score_lbl, ACCENT_BLUE)
        self.stats_layout.addWidget(self.health_card, 0, 0, 1, 2)
        
        self.status_lbl = QLabel("CHECKING...")
        self.status_lbl.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        self.stats_layout.addWidget(self.create_stats_card("SYSTEM STATUS", self.status_lbl, ACCENT_BLUE), 1, 0)
        
        self.identities_lbl = QLabel("0 ENROLLED")
        self.identities_lbl.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        self.stats_layout.addWidget(self.create_stats_card("IDENTITIES", self.identities_lbl, ACCENT_GREEN), 1, 1)
        
        self.camera_lbl = QLabel("SCANNING...")
        self.camera_lbl.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        self.stats_layout.addWidget(self.create_stats_card("CAMERAS", self.camera_lbl, "#ffcc00"), 2, 0)
        
        self.last_auth_lbl = QLabel("N/A")
        self.last_auth_lbl.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        self.stats_layout.addWidget(self.create_stats_card("LAST AUTH", self.last_auth_lbl, "#9d50bb"), 2, 1)
        
        # Phase 10: Safe Zone Status
        self.safe_zone_lbl = QLabel("DETECTING...")
        self.safe_zone_lbl.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        self.stats_layout.addWidget(self.create_stats_card("SAFE ZONE", self.safe_zone_lbl, "#00d2ff"), 3, 0, 1, 2)

        layout.addLayout(self.stats_layout)
        layout.addStretch()
        
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)
        
        # Timer for live updates
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_dashboard)
        self.refresh_timer.start(5000) # Every 5s
        self.refresh_dashboard()
        
    def create_stats_card(self, title, value_lbl, color):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {CARD_BG};
                border-radius: 20px;
                border: 2px solid {color}40;
            }}
        """)
        # Remove fixed size to allow scaling
        card.setMinimumSize(280, 160)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: bold; font-size: 13px; letter-spacing: 1px;")
        layout.addWidget(title_lbl)
        
        layout.addStretch()
        layout.addWidget(value_lbl, alignment=Qt.AlignCenter)
        layout.addStretch()
        
        return card

    def refresh_dashboard(self):
        # 1. Check Service Status
        try:
            res = subprocess.run(["systemctl", "is-active", "linux-bonjour"], capture_output=True, text=True)
            status = res.stdout.strip()
            self.status_lbl.setText(status.upper())
            color = "#00ff88" if status == "active" else "#ff4b4b"
            self.status_lbl.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
        except:
            self.status_lbl.setText("UNKNOWN")

        # 2. Count Identities from multiple locations
        try:
            model_name = self.config.get("model_name", "buffalo_s")
            
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
            
            count = len(unique_users)
            self.identities_lbl.setText(f"{count} ACTIVE")
        except:
            self.identities_lbl.setText("0 ACTIVE")

        # 3. Camera Status
        try:
            import glob
            vids = glob.glob("/dev/video*")
            if vids:
                self.camera_lbl.setText(f"{len(vids)} DETECTED")
                self.camera_lbl.setStyleSheet("color: #00ff88; font-size: 20px; font-weight: bold;")
            else:
                self.camera_lbl.setText("NOT FOUND")
                self.camera_lbl.setStyleSheet("color: #ff4b4b; font-size: 20px; font-weight: bold;")
        except:
            self.camera_lbl.setText("UNKNOWN")

        # 4. Last Auth Detection (from journalctl)
        try:
            res = subprocess.run(
                ["journalctl", "-u", "linux-bonjour", "-n", "20", "--no-pager"],
                capture_output=True, text=True
            )
            for line in reversed(res.stdout.splitlines()):
                if "AUTH SUCCESS" in line:
                    # [Fri Oct 20 12:00:00 2023] AUTH SUCCESS: User 'kawishika' ...
                    user_part = line.split("User '")[1].split("'")[0]
                    self.last_auth_lbl.setText(user_part.upper())
                    self.last_auth_lbl.setStyleSheet("color: #9d50bb; font-size: 20px; font-weight: bold;")
                    break
        except:
            pass

        # 5. Check Safe Zone
        try:
            # Re-use logic from main.py
            cmd = "nmcli -t -f active,ssid dev wifi | grep '^yes' | cut -d':' -f2"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            ssid = res.stdout.strip()
            safe_ssids = self.config.get("safe_ssids", [])
            if ssid and ssid in safe_ssids:
                self.safe_zone_lbl.setText(f"ACTIVE ({ssid})")
                self.safe_zone_lbl.setStyleSheet("color: #00ff88; font-size: 16px; font-weight: bold;")
            else:
                self.safe_zone_lbl.setText(ssid if ssid else "OFF (PUBLIC)")
                self.safe_zone_lbl.setStyleSheet("color: #8a8fb5; font-size: 16px; font-weight: bold;")
        except:
            self.safe_zone_lbl.setText("UNKNOWN")
            
        # 6. Calculate Security Health Score
        self.update_health_score()

    def update_health_score(self):
        """Calculates and updates the security health score based on active features."""
        score = 0
        
        # 1. TPM Support (30%)
        tpm_active = False
        if os.path.exists("/sys/class/tpm/tpm0/tpm_version_major"):
            try:
                with open("/sys/class/tpm/tpm0/tpm_version_major", "r") as f:
                    if f.read().strip() == "2":
                        tpm_active = True
                        score += 30
            except: pass
        
        # 1.5. Model Quality Bonus (10%)
        if self.config.get("model_name") == "buffalo_l":
            score += 10
            
        # 2. Liveness & Gestures (30%)
        liveness_score = 0
        if self.config.get("liveness_required", False): liveness_score += 15
        if self.config.get("secret_gesture_enabled", False): liveness_score += 15
        score += liveness_score
            
        # 3. Hardened Core (Seccomp/Isolation) (20%)
        # Check if seccomp is active in the service file
        try:
            service_path = "/lib/systemd/system/linux-bonjour.service"
            if os.path.exists(service_path):
                with open(service_path, "r") as f:
                    content = f.read()
                    if "SystemCallFilter" in content:
                        score += 20
        except: pass
            
        # 4. Contextual & Local Security (20%)
        context_score = 0
        if self.config.get("safe_ssids"): context_score += 10
        if self.config.get("auth_approval", True): context_score += 10
        score += context_score
            
        # Update UI
        self.health_score_lbl.setText(f"{score}%")
        
        # Color based on score
        if score >= 80:
            color = ACCENT_GREEN
            status_text = "HARDENED"
        elif score >= 50:
            color = "#ffcc00" # Yellow
            status_text = "STANDARD"
        else:
            color = ERROR_RED
            status_text = "UNPROTECTED"
            
        self.health_score_lbl.setStyleSheet(f"color: {color}; font-size: 40px; font-weight: 900;")
        self.health_card.setStyleSheet(f"""
            QFrame {{
                background-color: {CARD_BG};
                border-radius: 20px;
                border: 2px solid {color}40;
            }}
        """)
