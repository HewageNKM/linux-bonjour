# 🛡️ Linux Bonjour

## Professional Biometric Face-Recognition for the Modern Linux Desktop

Linux Bonjour is a high-performance, enterprise-grade biometric authentication suite built exclusively for Ubuntu/GNOME. Transitioning from legacy Python to a full **Rust Core**, it offers a memory-safe, hardware-bound security layer for your login screen, terminal, and GUI administrative prompts.

![Linux Bonjour Branding](https://github.com/HewageNKM/linux-bonjour/blob/main/src/bonjour-gui/src/assets/logo.png)

---

## 🌟 Modern Architecture (v2.1.3)

- 🦀 **All-Rust Core**: The traditional Python daemon has been replaced with a high-concurrency Rust engine, utilizing `tokio` for async UDS (Unix Domain Socket) communication and `onnxruntime` for lightning-fast facial inference.
- 🔐 **TPM 2.0 Hardware Sealing**: Your biometric signatures are irreversibly bound to True-Hardware Entropy via the `tss-esapi` Endorsement framework. Signatures are fused with unique silicon identifiers, making them uncopyable even if the storage is compromised.
- 🐚 **Gnome Shell Native**: Seamlessly integrated into GDM for a "Hello"-style login experience.
- 🛡️ **PAM Module Efficiency**: A custom Rust PAM module ensures that face recognition is triggered only when needed, with zero overhead on traditional password fallback.

## 🔐 Hardware Security & Fallback

Linux Bonjour prioritizes hardware-backed security.

- **Active Device Binding**: Facial signatures are cryptographically "sealed" inside an AES XChaCha20-Poly1305 envelope using keys derived from the TPM 2.0 Endorsement Hierarchy (`/dev/tpmrm0`).
- **Resilient Fallback**: If no TPM 2.0 device is detected, the system automatically engages a secure software cipher using the system's unique `/etc/machine-id`. This ensures universal compatibility across all Ubuntu hardware.

---

## 🚀 Installation & Universal Support

Our `.deb` package is standardized for universal Ubuntu compatibility (22.04 LTS through 24.10).

### 1. Simple Deployment

```bash
sudo dpkg -i linux-bonjour_2.2.9_amd64.deb
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
