# 🛡️ Linux Bonjour

## Professional Biometric Face-Recognition for the Modern Linux Desktop

Linux Bonjour is a high-performance, enterprise-grade biometric authentication suite built exclusively for Ubuntu/GNOME. Transitioning from legacy Python to a full **Rust Core**, it offers a memory-safe, hardware-bound security layer for your login screen, terminal, and GUI administrative prompts.

![Linux Bonjour Branding](https://github.com/HewageNKM/linux-bonjour/blob/main/src/bonjour-gui/src/assets/logo.png)

---

## 🌟 Modern Architecture (v2.3.6)

- 🦀 **All-Rust Core**: A high-concurrency async Rust engine powered by `tokio` and `onnxruntime`, providing sub-100ms facial verification.
- ⚡ **Nitro UI Dashboard**: A premium, "Glassmorphic" management console with real-time hardware diagnostics and a **Dynamic System Health Score** gauge.
- 🔐 **TPM 2.0 Hardware Sealing**: Your biometric signatures are irreversibly bound to True-Hardware Entropy via the `tss-esapi` Endorsement framework. Signatures are fused with unique silicon identifiers, making them uncopyable even if the storage is compromised.
- 🛡️ **Passive Liveness (LBP)**: Real-time texture and depth analysis to prevent photo/video spoofing attacks.
- 🐚 **Deep System Integration**: Unified authentication across GDM (Login), `sudo` (Terminal), and Polkit (GUI Admin prompts).

## 🔐 Hardware Security & Fallback

Linux Bonjour prioritizes hardware-backed security.

- **Active Device Binding**: Facial signatures are cryptographically "sealed" inside an AES XChaCha20-Poly1305 envelope using keys derived from the TPM 2.0 Endorsement Hierarchy (`/dev/tpmrm0`).
- **Resilient Fallback**: If no TPM 2.0 device is detected, the system automatically engages a secure software cipher using the system's unique `/etc/machine-id`. This ensures universal compatibility across all Ubuntu hardware.

---

## 🚀 Installation & Universal Support

Our `.deb` package is standardized for universal Ubuntu compatibility (22.04 LTS through 24.10).

### 1. Simple Deployment

```bash
sudo dpkg -i linux-bonjour_2.3.12_amd64.deb
sudo apt-get install -f  # Resolves hardware library gaps automatically
```

### 2. Zero-Config Permissions

The installer automatically handles:
- Creating hardware Enclave groups (`tss`, `vtpm`).
- Onboarding the local user into `video` and `render` groups.
- Generating secure directory inheritance for biometric storage.

---

## ⚙️ Advanced Customization

Accessible via the **Linux Bonjour Dashboard** (the Blue Penguin in your menu):

- **Match Threshold**: Fine-tune the AI sensitivity (Default: 0.45).
- **Search Loop**: Adjust the verification window (1s to 10s).
- **Global Toggle**: Master switch to enable/disable Face ID system-wide without uninstalling.
- **Log Management**: Comprehensive audit logs for tracking authentication attempts.

---

## 🏢 Enterprise Support

- **Group Policy Friendly**: Inherits standard Linux group permissions.
- **Audit-Ready**: Detailed logging and status reporting via `journalctl -u linux-bonjour`.

## 📄 License

Licensed under the MIT License. Developed with ❤️ for the Linux community.
