from PySide6.QtGui import QColor

# Premium Color Palette
BACKGROUND_COLOR = "#0C0E14"
SIDEBAR_COLOR = "#151921"
ACCENT_CYAN = "#00B0F4"
ACCENT_TEAL = "#03DAC6"
GLASS_WHITE = "rgba(255, 255, 255, 0.05)"
TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "rgba(255, 255, 255, 0.6)"
ERROR_RED = "#F04747"
WARNING_GOLD = "#FFA000"

# Premium QSS
GLOBAL_STYLE = f"""
    QMainWindow {{
        background-color: {BACKGROUND_COLOR};
    }}
    
    QWidget {{
        color: {TEXT_PRIMARY};
        font-family: 'Inter', 'Ubuntu', sans-serif;
    }}
    
    QGroupBox {{
        border: 1px solid {GLASS_WHITE};
        border-radius: 12px;
        margin-top: 25px;
        background-color: transparent;
        padding: 20px;
    }}
    
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 15px;
        padding: 0 10px;
        color: {ACCENT_CYAN};
        font-weight: bold;
        font-size: 14px;
    }}
    
    QPushButton {{
        background-color: {SIDEBAR_COLOR};
        border: 1px solid {GLASS_WHITE};
        border-radius: 10px;
        padding: 12px 20px;
        font-weight: 500;
        transition: all 0.3s ease;
    }}
    
    QPushButton:hover {{
        background-color: rgba(255, 255, 255, 0.08);
        border: 1px solid {ACCENT_CYAN};
    }}
    
    QPushButton#primaryBtn {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_CYAN}, stop:1 {ACCENT_TEAL});
        color: white;
        border: none;
        font-weight: bold;
    }}
    
    QPushButton#primaryBtn:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00C4FF, stop:1 #05EACD);
    }}
    
    QPushButton#dangerBtn {{
        background-color: rgba(240, 71, 71, 0.1);
        border: 1px solid rgba(240, 71, 71, 0.3);
        color: {ERROR_RED};
    }}
    
    QPushButton#dangerBtn:hover {{
        background-color: {ERROR_RED};
        color: white;
    }}
    
    QLineEdit, QSpinBox, QComboBox {{
        background-color: {SIDEBAR_COLOR};
        border: 1px solid {GLASS_WHITE};
        border-radius: 8px;
        padding: 10px;
        selection-background-color: {ACCENT_CYAN};
    }}
    
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 1px solid {ACCENT_CYAN};
    }}
    
    QListWidget {{
        background-color: transparent;
        border: 1px solid {GLASS_WHITE};
        border-radius: 12px;
        outline: none;
    }}
    
    QListWidget::item {{
        padding: 15px;
        border-bottom: 1px solid {GLASS_WHITE};
        margin: 0px;
    }}
    
    QListWidget::item:selected {{
        background-color: rgba(0, 176, 244, 0.1);
        color: {ACCENT_CYAN};
        border-left: 3px solid {ACCENT_CYAN};
    }}
    
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
    }}
    
    QScrollBar::handle:vertical {{
        background: {GLASS_WHITE};
        min-height: 30px;
        border-radius: 4px;
    }}
    
    QSlider::groove:horizontal {{
        border: none;
        height: 6px;
        background: {GLASS_WHITE};
        border-radius: 3px;
    }}
    
    QSlider::handle:horizontal {{
        background: {ACCENT_CYAN};
        border: none;
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    
    QCheckBox {{
        spacing: 12px;
    }}
    
    QCheckBox::indicator {{
        width: 20px;
        height: 20px;
        border-radius: 6px;
        border: 1.5px solid {GLASS_WHITE};
        background-color: {SIDEBAR_COLOR};
    }}
    
    QCheckBox::indicator:checked {{
        background-color: {ACCENT_CYAN};
        border: 1.5px solid {ACCENT_CYAN};
        image: url(none); /* Custom checkmark could be added */
    }}
"""
