#!/bin/bash

# linux-hello Installer Script
set -e

# Auto-detect project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PAM_CONFIG="/etc/pam.d/common-auth"

echo "Starting linux-hello installation from $PROJECT_DIR..."

# 1. Install System Dependencies
echo "Installing system dependencies..."
sudo apt-get install -y python3-venv python3-pip libpam0g-dev build-essential cmake
# Ensure the user who owns the project has camera access
REAL_USER=$(stat -c '%U' "$PROJECT_DIR")
sudo usermod -aG video $REAL_USER || true 

# 2. Setup Virtual Environment
echo "Setting up virtual environment..."
if [ ! -d "$PROJECT_DIR/venv" ]; then
    python3 -m venv "$PROJECT_DIR/venv"
fi
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 3. Compile PAM Module (Rust)
echo "Compiling Rust PAM module..."
cargo build --release --manifest-path "$PROJECT_DIR/src/pam_rs/Cargo.toml"

# 4. Install PAM Module
echo "Installing PAM module..."
if [ -d "/usr/lib/x86_64-linux-gnu/security" ]; then
    PAM_DIR="/usr/lib/x86_64-linux-gnu/security"
else
    PAM_DIR="/lib/security"
    sudo mkdir -p "$PAM_DIR"
fi

# Use 'install' command for better handling of binaries and permissions
sudo install -m 644 "$PROJECT_DIR/src/pam_rs/target/release/libpam_hello.so" "$PAM_DIR/pam_hello.so"

# 5. Initialize Models
echo "Initializing models..."
"$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/scripts/init_models.py"

# 6. Configure Systemd Services
echo "Configuring systemd services..."
sudo cp "$PROJECT_DIR/config/linux-hello.service" /etc/systemd/system/
sudo systemctl daemon-reload

# Fix permissions for the config directory so the user can enroll faces
echo "Fixing configuration permissions..."
sudo chown -R $REAL_USER:$REAL_USER "$PROJECT_DIR/config"

echo "Enabling services..."
sudo systemctl enable linux-hello || true
sudo systemctl enable linux-hello-ui || true

echo "Starting services..."
sudo systemctl restart linux-hello || true
sudo systemctl restart linux-hello-ui || true

echo "------------------------------------------------"
echo "Installation complete! 🎉"
echo "1. Enroll your face: ./venv/bin/python src/cli/enroll.py"
echo "2. Management UI: http://127.0.0.1:8080"
echo "3. Final Step: Add 'auth sufficient pam_hello.so' to $PAM_CONFIG"
echo "------------------------------------------------"
