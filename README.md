# Linux Hello: Windows Hello for Linux 🛡️🤳

`Linux Hello` is a secure, light-weight, and professional face-recognition authentication system for Linux. It provides a seamless login and `sudo` experience using IR or RGB cameras, powered by a memory-safe Rust PAM module and a high-performance Python AI daemon with a premium PySide6 management console.

---

## 🌟 Key Features

- **Memory Safe Security**: Core PAM module written in **Rust** for maximum safety and zero-latency performance.
- **Unified Management Console**: A premium **PySide6 (Qt)** desktop app with a Discord-inspired dark theme for configuration and identity management.
- **Live AI Feedback**: Real-time camera feed with face detection bounding boxes, landmark overlays, and instant "ready-to-save" status.
- **Hardware Sovereignty**: Full control over camera selection (Index and Type: IR/RGB/AUTO) directly from the GUI.
- **Zero-Setup Deployment**: One-click toggle in the GUI or a single terminal command to enable/disable security for Login, Sudo, and Lock Screen.
- **Hot-Reloading Support**: Switch between AI models (Lite vs Precision) or update security thresholds instantly without restarting services.
- **Identity Management**: Professional CRUD operations for user face profiles with high-fidelity visual feedback.

---

## 🏗️ Architecture

1.  **Rust PAM Module** (`src/pam_rs/`): Lightweight, safe-by-design shared object connecting to the daemon via a secure Unix socket.
2.  **Recognition Daemon** (`src/daemon/main.py`): Persistent background service for AI processing (InsightFace) and high-speed camera capture.
3.  **Management Console** (`src/gui/gui_app.py`): Professional desktop GUI for settings, hardware selection, and enrollment.
4.  **System Integration**: First-class systemd services for automated lifecycle management and background persistence.

---

## ⚡ Installation

### Prerequisites

- Python 3.10+
- Rust Toolchain (`cargo`, `rustc`)
- System libraries: `libpam0g-dev`, `build-essential`, `cmake`, `libxcb-cursor0`, `libgl1-mesa-glx`

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

Use the **"Dashboard"** to monitor daemon status and system security. The **"New Enrollment"** section allows you to capture your identity with live AI feedback.

### 2. Enable System-wide Face Unlock (Zero-Setup)

You can enable/disable biometric security for your **Login, Sudo, and Lock Screen** directly in the GUI settings or via the terminal:

```bash
sudo ./scripts/setup_pam.sh --enable-all
```

Check configuration status anytime: `sudo ./scripts/setup_pam.sh --status`.

---

## 📦 Professional Packaging (Debian/Ubuntu)

Distribute Linux Hello professionally using the built-in packaging tool:

```bash
chmod +x scripts/build_deb.sh
./scripts/build_deb.sh
```

This generates a `.deb` package that handles system-wide installation to `/usr/share/linux-hello` and automatic service registration. Install it with:

```bash
sudo dpkg -i linux-hello_1.0.0_amd64.deb
```

---

## 🛡️ Security & Settings

- **Match Threshold**: Adjust AI strictness (0.45 default, Higher = More Secure).
- **Max Failures**: Number of attempts allowed before a security cooldown period.
- **Cooldown (s)**: Duration of the lockout after maximum failures are reached.
- **Hardware Isolation**: The AI processing stack runs in an isolated process away from the critical PAM login flow for maximum stability.

---

## 📂 Project Structure

```text
linux-hello/
├── pkg/                # Debian packaging metadata and root
├── scripts/            # Install, Packaging, and PAM management tools
├── src/
│   ├── gui/            # Native PySide6 Management App
│   ├── daemon/         # AI Recognition & Hardware Service
│   └── pam_rs/         # Memory-safe Rust PAM Module
├── config/             # System-wide configuration & Face identities
└── requirements.txt    # Python dependencies
```

---

## ⚖️ License

MIT License. See [LICENSE](LICENSE) for details.
