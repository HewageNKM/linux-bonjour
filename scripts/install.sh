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

# 7. Create Native GUI Desktop Entry
echo "Creating desktop entry for Native Management GUI..."
DESKTOP_FILE="/usr/share/applications/linux-hello-gui.desktop"
cat <<EOF | sudo tee $DESKTOP_FILE > /dev/null
[Desktop Entry]
Name=Linux Hello
Comment=Manage face recognition settings and users
Exec=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/src/gui/gui_app.py
Icon=$PROJECT_DIR/src/gui/assets/logo.png
Terminal=false
Type=Application
Categories=Settings;Security;
EOF
sudo chmod +x $DESKTOP_FILE

echo "Enabling services..."
sudo systemctl enable linux-hello || true

echo "Starting services..."
sudo systemctl restart linux-hello || true

echo "------------------------------------------------"
echo "Installation complete! 🎉"
echo ""
echo "Next Steps to Zero-Setup:"
echo "1. Enroll your face in the GUI: 'Linux Hello' in your menu"
echo "2. Enable System-wide Face Recognition (Login & Lock Screen):"
echo "   sudo ./scripts/setup_pam.sh --enable-all"
echo ""
echo "Enjoy your native face-unlock experience! 🛡️🤳"
echo "------------------------------------------------"
