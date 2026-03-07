# Linux Hello: Windows Hello for Linux

`Linux Hello` is a secure, light-weight, and professional face-recognition authentication system for Linux. It provides a seamless login and `sudo` experience using IR or RGB cameras, powered by a memory-safe Rust PAM module and a high-performance Python AI daemon.

---

## 🌟 Key Features

- **Memory Safe Security**: Core PAM module written in **Rust** for maximum safety and zero-latency.
- **Native Management Console**: A premium **PySide6 (Qt)** desktop app for configuration and identity management.
- **Live AI Feedback**: Real-time camera feed with face detection bounding boxes and "ready-to-save" status.
- **Universal Hardware Support**: Native **IR Camera** support with automatic fallback to **RGB cameras**.
- **Hot-Reloading Support**: Changes take effect instantly across the system.
- **Zero-Setup Deployment**: One command to enable/disable security for Login, Sudo, and Lock Screen.
- **Face CRUD**: Full Create, Read, and Delete operations for user face profiles.

---

## 🏗️ Architecture

1. **Rust PAM Module** (`src/pam_rs/`): Lightweight shared object connecting to the daemon via a Unix socket.
2. **Recognition Daemon** (`src/daemon/main.py`): Persistent background service for AI processing (InsightFace) and camera capture.
3. **Management Console** (`src/gui/gui_app.py`): Professional desktop GUI for settings and enrollment.
4. **Systemd Integration**: Automated lifecycle management for all background components.

---

## ⚡ Installation

### Prerequisites
- Python 3.10+
- Rust Toolchain (`cargo`, `rustc`)
- System libraries: `libpam0g-dev`, `build-essential`, `cmake`, `libxcb-cursor0`

### Automatic Setup
```bash
chmod +x scripts/install.sh
sudo ./scripts/install.sh
```
This script automates dependency installation, virtual environment setup, Rust compilation, service registration, and creates a **Desktop Entry** for the Management Console.

---

## 🚀 Usage

### 1. Launch Management Console
Find **"Linux Hello Management"** in your application menu, or run:
```bash
./venv/bin/python src/gui/gui_app.py
```
Use the **"Dashboard"** to monitor status and the **"New Enrollment"** section to capture your identity with live AI feedback.

### 2. Enable System-wide Face Unlock (Zero-Setup)

To enable face-recognition for your **Login, Sudo, and Lock Screen**, run:

```bash
sudo ./scripts/setup_pam.sh --enable-all
```

Check configuration status anytime: `sudo ./scripts/setup_pam.sh --status`.

### 3. CLI Alternative
You can still use the traditional CLI for enrollment if preferred:
```bash
./venv/bin/python src/cli/enroll.py [username]
```

---

## 📂 Project Structure

```text
linux-hello/
├── config/             # Configuration & Identity storage
├── scripts/            # Install & Initialization scripts
├── src/
│   ├── gui/            # Native PySide6 Management App
│   ├── daemon/         # AI Recognition Service
│   ├── cli/            # Legacy Enrollment Tools
│   └── pam_rs/         # Rust PAM Module Source
└── requirements.txt    # Python dependencies (PySide6, InsightFace, etc.)
```

---

## 🛡️ Security & Settings

- **Match Threshold**: Adjust AI strictness (Higher = More Secure).
- **Max Failures**: Number of attempts allowed before a security cooldown.
- **Hot-Reloading**: Switching AI models (Lite vs Precision) happens instantly across the system when you hit "Apply".
- **Hardware Isolation**: The AI stack runs in an isolated process away from the critical PAM login flow.

---

## ⚖️ License
MIT License. See [LICENSE](LICENSE) for details.
