#!/bin/bash

# linux-hello Installer Script

set -e

PROJECT_DIR="/home/kawishika/Documents/Projects/linux-hello"
SERVICE_NAME="linux-hello.service"
PAM_CONFIG="/etc/pam.d/common-auth"

echo "Starting linux-hello installation..."

# 1. Install System Dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip libpam0g-dev build-essential cmake

# 2. Setup Virtual Environment
echo "Setting up virtual environment..."
if [ ! -d "$PROJECT_DIR/venv" ]; then
    python3 -m venv "$PROJECT_DIR/venv"
fi
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" || echo "Note: requirements.txt not found, skipping pip install."

# 3. Compile PAM Module (Rust)
echo "Compiling Rust PAM module..."
cargo build --release --manifest-path "$PROJECT_DIR/src/pam_rs/Cargo.toml"

# 4. Install PAM Module
echo "Installing PAM module..."
sudo cp "$PROJECT_DIR/src/pam_rs/target/release/libpam_hello.so" /lib/security/pam_hello.so

# 5. Initialize Models
echo "Initializing models..."
"$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/scripts/init_models.py"

# 6. Configure Systemd Services
echo "Configuring systemd services..."
sudo cp "$PROJECT_DIR/config/linux-hello.service" /etc/systemd/system/
sudo cp "$PROJECT_DIR/config/linux-hello-ui.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable linux-hello
sudo systemctl start linux-hello
sudo systemctl enable linux-hello-ui
sudo systemctl start linux-hello-ui

echo "Installation complete!"
echo "To finish setup, run: ./venv/bin/python src/cli/enroll.py"
echo "Then add 'auth sufficient pam_hello.so' to $PAM_CONFIG"
