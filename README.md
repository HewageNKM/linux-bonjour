# 🛡️ Linux Bonjour v1.1.0
**Professional Biometric Face-Recognition Authentication for Linux**

Linux Bonjour brings seamless, secure, and premium face-unlock to your Ubuntu/GNOME desktop. Built with a memory-safe **Rust PAM module** and a high-performance **Python AI daemon**, it offers a first-class native experience for logins, `sudo`, and administrative prompts.

---

## 🌟 Key Features (v1.1.0)

- 🎨 **Premium Glassmorphism Design**: High-end translucent UI with cyber-cyan accents, frosted glass effects, and a modern desktop aesthetic.
- 🔐 **Hardware-Bound Encryption**: Biometric signatures are protected with **AES-GCM (256-bit)** using keys derived from your system's `machine-id`.
- 🤳 **Hybrid Face Capture**: 
    - **Live Scanner**: Real-time tracking and alignment using custom-styled ScannerOverlays.
    - **Auto-Enrollment**: Intelligent countdown for hands-free biometric signature capture.
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
   sudo dpkg -i linux-bonjour_2.1.0_amd64.deb
   ```
   *Note: Native dependencies like `tpm2-tools` and `libpam0g` will be handled automatically.*

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
