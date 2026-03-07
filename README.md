# linux-hello: Windows Hello for Linux

`linux-hello` is a secure, light-weight, and professional face-recognition authentication system for Linux using IR cameras. It follows a memory-safe and distributed architecture to provide seamless login and `sudo` experiences.

---

## 🌟 Key Features

- **Memory Safe**: The core PAM (Pluggable Authentication Module) is written in **Rust** using `pam-sys` for maximum security in critical authentication processes.
- **AI Engine**: Powered by **InsightFace** (`buffalo_s` model), optimized for performance on systems with 8GB+ RAM.
- **Hardware Integration**: High-reliability recognition using **IR cameras** to work in total darkness and improve security against printed photos.
- **Multi-User Support**: Individual face-profiles stored as mathematical vectors in `config/users/<username>.npy`.
- **Auto-Detection**: Automatic discovery of IR camera devices (`/dev/video*`).
- **Fail-safes**: 
  - **Auth Throttling**: Cooldown period after consecutive failed attempts.
  - **PAM Timeout**: Non-blocking authentication with a 2-second socket timeout.

---

## 🏗️ Architecture

1.  **Rust PAM Module** (`src/pam_rs/`): A lightweight shared object (`.so`) that acts as a client. It connects to the daemon via a Unix socket (`/run/linux-hello.sock`).
2.  **Recognition Daemon** (`src/daemon/main.py`): A persistent background service that handles the AI processing, camera capture, and vector matching.
3.  **Enrollment CLI** (`src/cli/enroll.py`): An interactive tool to map physical faces to mathematical identities.
4.  **Systemd Service**: Manages the daemon lifecycle, ensuring it starts on boot and auto-restarts.

---

## ⚡ Installation

### Prerequisites
- Python 3.8+
- Rust Toolchain (`cargo`, `rustc`)
- System libraries: `libpam0g-dev`, `build-essential`, `cmake`

### Automatic Setup
Run the included installer script:
```bash
chmod +x scripts/install.sh
./scripts/install.sh
```
This script handles dependency installation, virtual environment setup, Rust compilation, and service configuration.

---

## 🚀 Usage

### 1. Enroll your face
```bash
./venv/bin/python src/cli/enroll.py
```
Follow the prompts to capture your face identity.

### 2. Configure PAM
To enable face-recognition for `sudo` or login, edit your PAM configuration (e.g., `/etc/pam.d/common-auth`):
```text
auth sufficient pam_hello.so
```
Add this above other authentication factors to make face-recognition the primary (sufficient) method.

### 3. Manage the Service
```bash
sudo systemctl status linux-hello
sudo systemctl restart linux-hello
```

---

## 📂 Project Structure
```text
linux-hello/
├── config/             # Identity data (users/*.npy)
├── scripts/            # Automation & setup
│   ├── install.sh      # One-click installer
│   └── init_models.py  # Model downloader
├── src/
│   ├── cli/            # Enrollment tools
│   ├── daemon/         # Python background service
│   └── pam_rs/         # Rust-based PAM source
└── requirements.txt    # Python dependencies
```

---

## 🛡️ Security
- **Throttling**: After 5 failed attempts, the user is locked out from face-recognition for 60 seconds (passwords still work).
- **Socket Isolation**: The heavy AI stack is isolated from the desktop login processes, reducing the attack surface.
- **IR Focus**: Requires an infrared emitters/camera, which is significantly harder to spoof than traditional RGB webcams.

---

## 🤝 Contributing
Contributions are welcome! Whether it's adding liveness detection, improving camera index heuristics, or hardening the Rust bindings.

---

## ⚖️ License
MIT License. See [LICENSE](LICENSE) for details. (Coming soon)
