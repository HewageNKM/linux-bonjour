# 🛡️ Linux Bonjour v1.1.0
**Professional Biometric Face-Recognition Authentication for Linux**

Linux Bonjour brings seamless, secure, and premium face-unlock to your Ubuntu/GNOME desktop. Built with a memory-safe **Rust PAM module** and a high-performance **Python AI daemon**, it offers a first-class native experience for logins, `sudo`, and administrative prompts.

---

## 🌟 Key Features (v1.1.0)

- 🎨 **Ubuntu Yaru Redesign**: Native GTK-style dark theme with official Ubuntu branding, fonts (Ubuntu Family), and aesthetics.
- 🔐 **Hardware-Bound Encryption**: Biometric signatures are protected with **AES-GCM (256-bit)** using keys derived from your system's **TPM 2.0** or `machine-id`.
- 🤳 **Hybrid Face Capture**: 
    - **Auto-Capture**: Intelligent 1.6s countdown for hands-free enrollment with tracking overlays.
    - **Grace Period**: 0.6s tracking tolerance to ensure stability during movements.
- ⚙️ **Granular Face ID Toggling**: Independent control for **Login (GDM/SDDM/LightDM)**, **Sudo (Terminal)**, and **Polkit (GUI Admin Prompts)**.
- 🛡️ **Terminal Feedback**: Real-time "Scanning...", "Matched!", and "Failed" messages directly in your terminal via **PAM Conversations**.
- 🔄 **Intelligent Verification Loop**: A robust 3.5s (adjustable) "searching" experience that handles blurry frames and brief occlusions.
- 🕵️ **Privacy & Performance**:
    - **Logging Toggle**: Enable or disable detailed authentication logs via the GUI.
    - **Connection Peek**: Daemon automatically stops scanning if you start typing your password or cancel the session.

---

## 🚀 Quick Start (Debian/Ubuntu)

1. **Download and Install**:
   ```bash
   sudo dpkg -i linux-bonjour_1.1.0_amd64.deb
   ```
   *Note: Dependencies like `python3-venv` and `libpam0g` will be handled automatically.*

2. **Enroll Your Face**:
   Open **"Linux Bonjour"** from your application menu (or run `linux-bonjour`). Click **"Capture Signature"** and follow the holographic scanner countdown.

3. **Secure Your System**:
   Navigate to the **Security** tab. Toggle **"Global Face ID"** to enable protection system-wide, or use the **Partwise** options for granular control.

---

## 🛠️ Advanced Settings

- **Match Threshold**: Adjust AI strictness (0.45 default). Higher = More Secure.
- **Search Duration**: Control how long the scanner looks for your face before falling back to password (1s - 10s).
- **AI Model Mode**: Hot-reload between `buffalo_s` (Fastest) and `antelopev2` (Most Precise) instantly.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
