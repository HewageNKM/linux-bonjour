from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSlider, QSpinBox, QGroupBox, QCheckBox, 
                             QComboBox, QScrollArea, QPushButton, QMessageBox)
from PySide6.QtCore import Qt, Signal, Slot

from gui.ui.styles import ACCENT_CYAN, TEXT_SECONDARY, GLASS_WHITE

class SettingsView(QWidget):
    config_changed = Signal(dict)
    pam_toggle_requested = Signal(bool)
    granular_toggle_requested = Signal(str, bool)
    download_requested = Signal(str)
    reset_requested = Signal()
    probe_requested = Signal()
    fix_perms_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(20)

        # 1. System Security
        sys_group = QGroupBox("SYSTEM SECURITY")
        sys_layout = QVBoxLayout()

        self.system_enabled_toggle = QCheckBox("MASTER SYSTEM SWITCH")
        self.system_enabled_toggle.setStyleSheet(f"font-weight: bold; font-size: 14px; color: #ffffff; background: {ACCENT_CYAN}; padding: 10px; border-radius: 5px;")
        self.system_enabled_toggle.setToolTip("Enable or disable the entire Linux Bonjour biometric system instantly.")
        sys_layout.addWidget(self.system_enabled_toggle)
        sys_layout.addSpacing(10)
        
        self.pam_toggle = QCheckBox("GLOBAL FACE UNLOCK")
        self.pam_toggle.setStyleSheet(f"font-weight: bold; color: {ACCENT_CYAN};")
        self.pam_toggle.setToolTip("Enable or disable face authentication for all system services (Login, Sudo, Polkit).")
        self.pam_toggle.toggled.connect(lambda s: self.pam_toggle_requested.emit(s))
        sys_layout.addWidget(self.pam_toggle)
        
        granular_container = QWidget()
        granular_layout = QVBoxLayout(granular_container)
        granular_layout.setContentsMargins(30, 0, 0, 0)
        
        self.login_toggle = QCheckBox("Lock Screen & Login")
        self.login_toggle.setToolTip("Use face unlock for GDM/SDDM lock screens and login prompts.")
        self.login_toggle.toggled.connect(lambda s: self.granular_toggle_requested.emit("login", s))
        granular_layout.addWidget(self.login_toggle)
        
        self.sudo_toggle = QCheckBox("Sudo / Terminal Access")
        self.sudo_toggle.setToolTip("Authenticate sudo commands in the terminal using your face.")
        self.sudo_toggle.toggled.connect(lambda s: self.granular_toggle_requested.emit("sudo", s))
        granular_layout.addWidget(self.sudo_toggle)
        
        self.polkit_toggle = QCheckBox("GUI Admin Requests (Polkit)")
        self.polkit_toggle.setToolTip("Confirm administrative actions in GUI apps (like Software Center) with face recognition.")
        self.polkit_toggle.toggled.connect(lambda s: self.granular_toggle_requested.emit("polkit", s))
        granular_layout.addWidget(self.polkit_toggle)
        
        sys_layout.addWidget(granular_container)
        sys_group.setLayout(sys_layout)
        container_layout.addWidget(sys_group)

        # 2. Recognition Engine
        engine_group = QGroupBox("RECOGNITION ENGINE")
        engine_layout = QVBoxLayout()
        
        engine_layout.addWidget(QLabel("MATCH THRESHOLD"))
        t_header = QHBoxLayout()
        help_t = QLabel("ⓘ")
        help_t.setToolTip("Lower threshold = easier match (less secure).\n"
                         "Higher threshold = stricter match (more secure).")
        help_t.setStyleSheet(f"color: {ACCENT_CYAN}; cursor: help;")
        t_header.addWidget(QLabel("Match Sensitivity"))
        t_header.addStretch()
        t_header.addWidget(help_t)
        engine_layout.addLayout(t_header)

        t_layout = QHBoxLayout()
        self.t_slider = QSlider(Qt.Horizontal)
        self.t_slider.setRange(10, 95)
        self.t_slider.setToolTip("Adjust how strictly faces must match. Higher is more secure but may fail more often.")
        self.t_label = QLabel("0.45")
        self.t_slider.valueChanged.connect(lambda v: self.t_label.setText(f"{v/100:.2f}"))
        t_layout.addWidget(self.t_slider)
        t_layout.addWidget(self.t_label)
        engine_layout.addLayout(t_layout)
        
        engine_layout.addWidget(QLabel("AI MODEL SELECTION"))
        m_header = QHBoxLayout()
        help_m = QLabel("ⓘ")
        help_m.setToolTip("Buffalo_SC: Super fast, low accuracy.\n"
                         "Buffalo_S: Standard balance.\n"
                         "Buffalo_L: High accuracy, high CPU usage.")
        help_m.setStyleSheet(f"color: {ACCENT_CYAN}; cursor: help;")
        m_header.addWidget(QLabel("AI Model Architecture"))
        m_header.addStretch()
        m_header.addWidget(help_m)
        engine_layout.addLayout(m_header)

        self.m_combo = QComboBox()
        self.m_combo.addItems(["buffalo_sc", "buffalo_s", "buffalo_l", "antelopev2"])
        self.m_combo.setMinimumHeight(40)
        self.m_combo.setToolTip("Select the deep learning model. 'buffalo_l' is most accurate but slower.")
        engine_layout.addWidget(self.m_combo)
        
        self.download_btn = QPushButton("☁️ Download Model")
        self.download_btn.setObjectName("secondaryBtn")
        self.download_btn.hide()
        self.download_btn.setToolTip("Download the selected model architecture to your local system.")
        self.download_btn.clicked.connect(lambda: self.download_requested.emit(self.m_combo.currentText()))
        engine_layout.addWidget(self.download_btn)
        
        engine_group.setLayout(engine_layout)
        container_layout.addWidget(engine_group)

        # 3. Hardware
        hw_group = QGroupBox("HARDWARE INTERFACE")
        hw_layout = QVBoxLayout()
        self.cam_type_combo = QComboBox()
        self.cam_type_combo.addItems(["AUTO", "IR", "RGB"])
        self.cam_type_combo.setMinimumHeight(40)
        self.cam_type_combo.setToolTip("Force a specific camera sensor type if 'AUTO' detection fails.")
        hw_layout.addWidget(QLabel("CAMERA MODE"))
        hw_layout.addWidget(self.cam_type_combo)
        hw_group.setLayout(hw_layout)
        container_layout.addWidget(hw_group)

        # 4. Advanced & Debug
        adv_group = QGroupBox("ADVANCED & DEBUG")
        adv_layout = QVBoxLayout()
        
        # Notification & Approval Toggles
        self.auth_approval_toggle = QCheckBox("ENABLE AUTHORIZATION POPUP")
        self.auth_approval_toggle.setToolTip("Show a Zenity popup for you to approve before the face scan begins (recommended for Sudo).")
        adv_layout.addWidget(self.auth_approval_toggle)

        self.notifications_toggle = QCheckBox("ENABLE DESKTOP NOTIFICATIONS")
        self.notifications_toggle.setToolTip("Show desktop alerts when authentication succeeds, fails, or scanning starts.")
        adv_layout.addWidget(self.notifications_toggle)
        
        # Logging Toggles
        
        # Auth Throttling
        throttle_layout = QHBoxLayout()
        throttle_layout.addWidget(QLabel("MAX FAILURES"))
        self.max_fail_spin = QSpinBox()
        self.max_fail_spin.setRange(1, 10)
        self.max_fail_spin.setToolTip("Number of failed attempts before temporary lockout.")
        throttle_layout.addWidget(self.max_fail_spin)
        
        throttle_layout.addSpacing(20)
        throttle_layout.addWidget(QLabel("GRACE PERIOD (sec)"))
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(10, 300)
        self.cooldown_spin.setSingleStep(10)
        self.cooldown_spin.setToolTip("Duration of the lockout cooling period after max failures.")
        throttle_layout.addWidget(self.cooldown_spin)
        adv_layout.addLayout(throttle_layout)
        
        adv_group.setLayout(adv_layout)
        container_layout.addWidget(adv_group)

        # 5. Troubleshooting & Support
        ts_group = QGroupBox("TROUBLESHOOTING & SUPPORT")
        ts_layout = QVBoxLayout()
        ts_layout.addWidget(QLabel("If the camera preview is black or the system isn't unlocking, try these tools:"))
        
        ts_btn_layout = QHBoxLayout()
        self.probe_btn = QPushButton("🔍 PROBE CAMERA")
        self.probe_btn.setToolTip("Test camera availability and permissions.")
        self.probe_btn.clicked.connect(self.probe_requested.emit)
        
        self.fix_btn = QPushButton("🛠️ FIX PERMISSIONS")
        self.fix_btn.setToolTip("Re-apply hardware access rules (requires sudo).")
        self.fix_btn.clicked.connect(self.fix_perms_requested.emit)
        
        ts_btn_layout.addWidget(self.probe_btn)
        ts_btn_layout.addWidget(self.fix_btn)
        ts_layout.addLayout(ts_btn_layout)
        
        self.log_area = QLabel("System Status: Idle")
        self.log_area.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; padding-top: 10px;")
        ts_layout.addWidget(self.log_area)
        
        ts_group.setLayout(ts_layout)
        container_layout.addWidget(ts_group)

        # Save Actions
        actions = QHBoxLayout()
        self.reset_btn = QPushButton("RESTORE DEFAULTS")
        self.reset_btn.setToolTip("Reset all settings to their factory default values.")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        self.save_btn = QPushButton("SAVE CHANGES")
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.setToolTip("Save and apply the current configuration to the system.")
        self.save_btn.clicked.connect(self.emit_config)
        actions.addWidget(self.reset_btn)
        actions.addWidget(self.save_btn)
        container_layout.addLayout(actions)

        scroll.setWidget(container)
        layout.addWidget(scroll)

    def emit_config(self):
        config = {
            "system_enabled": self.system_enabled_toggle.isChecked(),
            "threshold": self.t_slider.value() / 100,
            "model_name": self.m_combo.currentText(),
            "camera_type": self.cam_type_combo.currentText(),
            "logging_enabled": self.log_toggle.isChecked(),
            "pam_logging": self.pam_log_toggle.isChecked(),
            "auth_approval": self.auth_approval_toggle.isChecked(),
            "notifications_enabled": self.notifications_toggle.isChecked(),
            "max_failures": self.max_fail_spin.value(),
            "cooldown_time": self.cooldown_spin.value()
        }
        self.config_changed.emit(config)

    def update_ui_from_config(self, config):
        self.system_enabled_toggle.setChecked(config.get("system_enabled", True))
        self.t_slider.setValue(int(config.get("threshold", 0.45) * 100))
        self.m_combo.setCurrentText(config.get("model_name", "buffalo_l"))
        self.cam_type_combo.setCurrentText(config.get("camera_type", "AUTO"))
        self.log_toggle.setChecked(config.get("logging_enabled", True))
        self.pam_log_toggle.setChecked(config.get("pam_logging", True))
        self.auth_approval_toggle.setChecked(config.get("auth_approval", True))
        self.notifications_toggle.setChecked(config.get("notifications_enabled", True))
        self.max_fail_spin.setValue(config.get("max_failures", 3))
        self.cooldown_spin.setValue(config.get("cooldown_time", 60))
