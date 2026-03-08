# <img src="src/gui/assets/logo.png" width="48" height="48"> Linux Bonjour: Windows Hello for Linux 🛡️🤳

`Linux Bonjour` is a secure, light-weight, and professional face-recognition authentication system for Linux. It provides a seamless login and `sudo` experience using IR or RGB cameras, powered by a memory-safe Rust PAM module and a high-performance Python AI daemon with a native-style PySide6 management console.

---

## 🌟 Key Features

- **Military-Grade Encryption**: Face embeddings are encrypted using **AES-GCM (256-bit)**. Keys are derived from hardware-bound secrets (TPM 2.0 or Machine-ID), ensuring your biometric data never leaves your device in an unencrypted state.
- **Hybrid Capture Mode**: 
    - **Auto-Capture**: Intelligent 1.6s countdown for hands-free enrollment.
    - **Grace Period**: 0.6s tracking tolerance to prevent progress resets during brief head movements or lighting flickers.
    - **Manual Override**: Immediate "point-and-click" capture for users who want total control.
- **Memory Safe Security**: Core PAM module written in **Rust** for maximum safety and zero-latency performance.
- **Unified Management Console**: A professional **PySide6 (Qt)** desktop app with a native Ubuntu-inspired theme for configuration and identity management.
- **Live AI Feedback**: Real-time camera feed with persistent connection for instant startup, featuring holographic scanning overlays and landmark tracking.
- **Hardware Sovereignty**: Full control over camera selection (Index and Type: IR/RGB/AUTO) directly from the GUI.
- **Graphical Daemon Control**: Built-in "Start/Restart" service management with automatic persistence (Systemd enforcement).
- **Hot-Reloading Support**: Switch between **four AI models** (from lightweight `buffalo_s` to ultra-precise `antelopev2`) instantly without restarting services.
- **Professional Packaging**: Distributed as a standard `.deb` package for easy deployment and clean uninstallation.

---

## 🏗️ Architecture

1.  **Rust PAM Module** (`src/pam_rs/`): Lightweight, safe-by-design shared object connecting to the daemon via a secure Unix socket.
2.  **Recognition Daemon** (`src/daemon/main.py`): Persistent background service for AI processing (InsightFace) and high-speed camera capture.
3.  **Management Console** (`src/gui/gui_app.py`): Professional desktop GUI for settings, hardware selection, and enrollment.
4.  **Security Layer**: AES-GCM encryption with machine-bound key derivation for biometric data protection.

---

## ⚡ Installation (Recommended)

### 📦 Professional Package (.deb)

The fastest way to install Linux Bonjour on Debian-based systems (Ubuntu, Zorin, etc).

1.  **Build or Download the package**:
    ```bash
    ./scripts/build_deb.sh
    ```
2.  **Install the package**:
    ```bash
    sudo dpkg -i linux-bonjour_1.1.0_amd64.deb
    ```
    *Note: If dependencies are missing, run `sudo apt-get install -f`.*

---

## 🚀 Usage

### 1. Launch Management Console

Find **"Linux Bonjour"** in your application menu, or run:

```bash
linux-bonjour
```

Use the **"New Enrollment"** section to capture your identity. The system will auto-fill your username and start locking onto your face immediately.

### 2. Enable System-wide Face Unlock

Enable biometric security for your **Login, Sudo, and Lock Screen** directly in the GUI Dashboard.

- **Standard Mode**: Matches your camera feed against your specific system username.
- **Global Unlock**: Allow *any* person in your encrypted database to authenticate for *any* user.

```bash
# Terminal Method (Alternative):
sudo /usr/share/linux-bonjour/scripts/setup_pam.sh --enable-all
```

---

## 🛠️ Debugging & Logs

If enrollment or authentication fails, check the detailed diagnostic logs:
- **Daemon Logs**: `/usr/share/linux-bonjour/daemon.log`
- **GUI Debug**: Run `linux-bonjour` from a terminal to see real-time [DEBUG] traces.

---

## 🛡️ Security & Settings

- **Hardware-Bound Keys**: Secrets derived from `/etc/machine-id` or TPM to prevent cloning of face data to other machines.
- **Match Threshold**: Adjust AI strictness (0.50 default, Higher = More Secure).
- **Polkit Integration**: System-wide changes trigger professional graphical authentication prompts.

---

## ⚖️ License

MIT License. See [LICENSE](LICENSE) for details.
