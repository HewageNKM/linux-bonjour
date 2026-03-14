#!/bin/bash

# linux-bonjour Installer Script (v2.1.0 Rust Core)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Starting linux-bonjour installation..."

# 1. Install System Dependencies
echo "Installing system dependencies..."
sudo apt-get install -y libpam0g-dev build-essential cmake tpm2-tools libtss2-dev pkg-config libdbus-1-dev libwebkit2gtk-4.1-0 libsqlite3-dev libv4l-dev

# 2. Build Components
echo "Building Rust components..."
cd "$PROJECT_DIR/src/pam_rs" && cargo build --release
cd "$PROJECT_DIR/src/bonjour-daemon" && cargo build --release

echo "Building Tauri GUI..."
cd "$PROJECT_DIR/src/bonjour-gui"
if [ ! -d "node_modules" ]; then
    npm install
fi
npm run tauri build

# 3. Install PAM Module
echo "Installing PAM module..."
if [ -d "/usr/lib/x86_64-linux-gnu/security" ]; then
    PAM_DIR="/usr/lib/x86_64-linux-gnu/security"
else
    PAM_DIR="/lib/security"
    sudo mkdir -p "$PAM_DIR"
fi
sudo install -m 644 "$PROJECT_DIR/src/pam_rs/target/release/libpam_bonjour.so" "$PAM_DIR/pam_bonjour.so"

# 4. Install Binaries
sudo install -m 755 "$PROJECT_DIR/src/bonjour-daemon/target/release/bonjour-daemon" "/usr/bin/linux-bonjour-daemon"
sudo install -m 755 "$PROJECT_DIR/src/bonjour-gui/src-tauri/target/release/bonjour-gui" "/usr/bin/linux-bonjour-gui"

# 5. Configure Systemd
echo "Configuring systemd..."
sudo cp "$PROJECT_DIR/config/linux-bonjour.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable linux-bonjour
sudo systemctl restart linux-bonjour

# 6. Desktop Integration
echo "Installing desktop integration..."
sudo cp "$PROJECT_DIR/linux-bonjour.desktop" /usr/share/applications/
sudo cp "$PROJECT_DIR/src/bonjour-gui/src-tauri/icons/icon.png" "/usr/share/pixmaps/linux-bonjour.png" || true

# 7. Polkit Policy
echo "Installing polkit policy..."
if [ -f "$PROJECT_DIR/org.linuxbonjour.policy" ]; then
    sudo cp "$PROJECT_DIR/org.linuxbonjour.policy" /usr/share/polkit-1/actions/
fi

# 8. Activation
echo "Activating PAM module..."
sudo bash "$PROJECT_DIR/scripts/setup_pam.sh" --enable-all

echo "------------------------------------------------"
echo "Linux Bonjour v2.1.0 Installed Successfully! 🎉"
echo "------------------------------------------------"
