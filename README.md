# <img src="src/gui/assets/logo.png" width="48" height="48"> Linux Hello: Windows Hello for Linux 🛡️🤳

`Linux Hello` is a secure, light-weight, and professional face-recognition authentication system for Linux. It provides a seamless login and `sudo` experience using IR or RGB cameras, powered by a memory-safe Rust PAM module and a high-performance Python AI daemon with a premium PySide6 management console.

---

## 🌟 Key Features

- **Memory Safe Security**: Core PAM module written in **Rust** for maximum safety and zero-latency performance.
- **Unified Management Console**: A premium **PySide6 (Qt)** desktop app with a Discord-inspired dark theme for configuration and identity management.
- **Live AI Feedback**: Real-time camera feed with face detection bounding boxes, landmark overlays, and instant "ready-to-save" status.
- **Hardware Sovereignty**: Full control over camera selection (Index and Type: IR/RGB/AUTO) directly from the GUI.
- **Zero-Setup Deployment**: One-click toggle in the GUI or a single terminal command to enable/disable security for Login, Sudo, and Lock Screen.
- **Hot-Reloading Support**: Switch between **four AI models** (from lightweight `buffalo_s` to ultra-precise `antelopev2`) instantly without restarting services.
- **Identity Management**: Professional CRUD operations for user face profiles with high-fidelity visual feedback.

---

## 🏗️ Architecture

1.  **Rust PAM Module** (`src/pam_rs/`): Lightweight, safe-by-design shared object connecting to the daemon via a secure Unix socket.
2.  **Recognition Daemon** (`src/daemon/main.py`): Persistent background service for AI processing (InsightFace) and high-speed camera capture.
3.  **Management Console** (`src/gui/gui_app.py`): Professional desktop GUI for settings, hardware selection, and enrollment.
4.  **System Integration**: First-class systemd services for automated lifecycle management and background persistence.

---

## ⚡ Installation (Recommended)

### 📦 Professional Package (.deb)

The fastest and most common way to install Linux Hello on Debian-based systems (Ubuntu, Zorin, etc).

1.  **Build or Download the package**:
    ```bash
    ./scripts/build_deb.sh
    ```
2.  **Install with automatic dependency handling**:
    ```bash
    sudo apt update
    sudo apt install ./linux-hello_1.0.0_amd64.deb
    ```
    *Note: If you have a previous broken version, run `sudo dpkg --purge linux-hello` first.*

---

## 🚀 Usage

### 1. Launch Management Console

Find **"Linux Hello"** in your application menu, or run the global command:

```bash
linux-hello
```

Use the **"Dashboard"** to monitor daemon status and system security. The **"New Enrollment"** section allows you to capture your identity with live AI feedback.

### 2. Enable System-wide Face Unlock

Enable/disable biometric security for your **Login, Sudo, and Lock Screen** directly in the GUI settings or via the terminal:

```bash
# GUI Method: Toggle the "Enable Face Unlock" checkbox (requires password)
# Terminal Method:
sudo /usr/share/linux-hello/scripts/setup_pam.sh --enable-all
```

---

## 🛠️ Development & Manual Setup

If you prefer to run from source:

```bash
# Install system deps
sudo apt install -y libpam0g-dev build-essential cmake libxcb-cursor0 libgl1

# Run installer
chmod +x scripts/install.sh
sudo ./scripts/install.sh
```

---

## 🛡️ Security & Settings

- **Match Threshold**: Adjust AI strictness (0.45 default, Higher = More Secure).
- **Max Failures**: Number of attempts allowed before a security cooldown period.
- **Polkit Integration**: System-wide changes trigger a professional graphical authentication prompt.
- **Hardware Isolation**: The AI stack runs in an isolated process away from the critical PAM login flow.

---

## ⚖️ License

MIT License. See [LICENSE](LICENSE) for details.
