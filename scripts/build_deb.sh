#!/bin/bash
set -e

# Linux Bonjour Debian Package Builder
# Automates the creation of a professional .deb package.

# v1.1.10: Make script robust to execution directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VERSION="2.2.7"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"
cd "$PROJECT_ROOT"

PKG_ROOT="$PROJECT_ROOT/pkg"

echo "Building Linux Bonjour v$VERSION..."
echo "Project Root: $PROJECT_ROOT"

# 1. Build Rust Components
echo "🦀 Compiling Rust components..."

# 1.1 Build PAM Module
echo "Building PAM module..."
cd "$PROJECT_ROOT/src/pam_rs"
cargo build --release

# 1.2 Build AI Daemon
echo "Building AI Daemon..."
cd "$PROJECT_ROOT/src/bonjour-daemon"
cargo build --release

# 1.3 Build Tauri GUI
echo "Building Tauri GUI..."
cd "$PROJECT_ROOT/src/bonjour-gui"
npm install
npm run tauri build -- --bundles deb

cd "$PROJECT_ROOT"

# 2. Stage Files
echo "Staging files..."
rm -rf pkg
mkdir -p pkg/DEBIAN
mkdir -p pkg/usr/bin
mkdir -p pkg/usr/share/linux-bonjour/models
mkdir -p pkg/lib/x86_64-linux-gnu/security
mkdir -p pkg/usr/share/linux-bonjour/src
mkdir -p pkg/usr/share/polkit-1/actions
mkdir -p pkg/usr/share/pixmaps
mkdir -p pkg/usr/share/applications
mkdir -p pkg/lib/systemd/system

# Generate DEB Metadata
cat <<EOF > pkg/DEBIAN/control
Package: linux-bonjour
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Maintainer: HewageNKM <[EMAIL_ADDRESS]>
Depends: libpam0g, libxcb-cursor0, libgl1, libglib2.0-0, libnotify-bin, tpm2-tools, libtss2-dev, libdbus-1-3, libwebkit2gtk-4.1-0, v4l-utils, curl, unzip
Description:
  Linux Bonjour - Professional biometric face-recognition authentication.
  A secure, light-weight face-recognition authentication system for Linux.
  Includes a Rust-based PAM module and a high-performance Rust AI daemon.
EOF

cat <<EOF > pkg/DEBIAN/postinst
#!/bin/bash
set -e
BASE_DIR="/usr/share/linux-bonjour"
MODELS_DIR="\$BASE_DIR/models"
echo "Configuring Linux Bonjour v$VERSION Rust Core..."

# 0. Download Core AI Models
echo "Downloading core AI models (buffalo_l)..."
mkdir -p \$MODELS_DIR
if [ ! -f "\$MODELS_DIR/det_10g.onnx" ] || [ ! -f "\$MODELS_DIR/arcface_w600k.onnx" ]; then
    curl -L -s "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip" -o "/tmp/buffalo_l.zip"
    unzip -j -o -q "/tmp/buffalo_l.zip" -d "\$MODELS_DIR/"
    if [ -f "\$MODELS_DIR/w600k_r50.onnx" ]; then
        mv "\$MODELS_DIR/w600k_r50.onnx" "\$MODELS_DIR/arcface_w600k.onnx"
    fi
    rm -f "/tmp/buffalo_l.zip"
    echo "AI Models downloaded and installed."
else
    echo "AI Models already exist. Skipping download."
fi

# 1. Setup Persistent Infrastructure
echo "Configuring system paths..."
mkdir -p /var/log/linux-bonjour
chown root:root /var/log/linux-bonjour
chmod 755 /var/log/linux-bonjour

mkdir -p /var/lib/linux-bonjour/users
chown root:root /var/lib/linux-bonjour
chmod 777 /var/lib/linux-bonjour/users

# 2. Camera Permission Hardening
echo "Hardening camera permissions..."
groupadd -f video
groupadd -f render
# Add current user to video and render groups
if [ -n "\$SUDO_USER" ]; then
    usermod -a -G video,render "\$SUDO_USER"
    echo "Added user \$SUDO_USER to video/render groups."
fi

# Apply udev rules
if [ -f "/usr/share/linux-bonjour/scripts/99-linux-bonjour-camera.rules" ]; then
    cp "/usr/share/linux-bonjour/scripts/99-linux-bonjour-camera.rules" /etc/udev/rules.d/
    udevadm control --reload-rules && udevadm trigger
fi

# 3. Final Permissions Setup
chown -R root:root /usr/share/linux-bonjour
chmod -R 755 /usr/share/linux-bonjour
chmod -R 777 /var/lib/linux-bonjour/users

# 6. PAM Module Setup (CRITICAL)
chown root:root /lib/x86_64-linux-gnu/security/pam_bonjour.so
chmod 644 /lib/x86_64-linux-gnu/security/pam_bonjour.so

# 7. Systemd Service Activation
echo "Setting up background service..."
systemctl daemon-reload
systemctl enable linux-bonjour
systemctl restart linux-bonjour

# 8. Hardware Auto-Configuration (TPM & Camera)
echo "Detecting hardware for optimal performance..."

# 8.1 TPM Permissions & Secure Hardware Enclave Access
# Different versions of Ubuntu map TPM ownership to 'tss' or 'vtpm'
groupadd -f tss
groupadd -f vtpm

# Ensure the Daemon socket directory has secure execution inheritance
chown root:tss /var/lib/linux-bonjour
chmod 755 /var/lib/linux-bonjour

if [ -n "\$SUDO_USER" ]; then
    usermod -a -G tss "\$SUDO_USER"
    usermod -a -G vtpm "\$SUDO_USER"
    echo "Added \$SUDO_USER to enterprise 'tss' and 'vtpm' Enclave Hardware groups."
fi

# 8.2 Camera Auto-Selection
mkdir -p /etc/linux-bonjour
CONFIG_FILE="/etc/linux-bonjour/config.json"

if [ ! -f "\$CONFIG_FILE" ]; then
    echo "🔍 Probing for best available camera..."
    # 1. Look for IR/Infrared devices first
    BEST_CAM=\$(v4l2-ctl --list-devices 2>/dev/null | awk '/IR|Infrared/ {getline; print \$1; exit}' | tr -d '[:space:]')
    
    # 2. If no IR, look for high-index Video Capture devices (usually external)
    if [ -z "\$BEST_CAM" ]; then
        BEST_CAM=\$(v4l2-ctl --list-devices 2>/dev/null | grep -o "/dev/video[0-9]*" | head -n 1)
    fi

    if [ -n "\$BEST_CAM" ]; then
        echo "✅ Pre-selected Camera: \$BEST_CAM"
        cat <<EOC > "\$CONFIG_FILE"
{
  "threshold": 0.38,
  "smile_required": false,
  "autocapture": false,
  "liveness_enabled": true,
  "ask_permission": false,
  "retry_limit": 3,
  "camera_path": "\$BEST_CAM"
}
EOC
    else
        echo "⚠️ No camera detected. Creating default config."
        cat <<EOC > "\$CONFIG_FILE"
{
  "threshold": 0.38,
  "smile_required": false,
  "autocapture": false,
  "liveness_enabled": true,
  "ask_permission": false,
  "retry_limit": 3,
  "camera_path": null
}
EOC
    fi
fi

# 9. Automatic PAM Activation
echo "Activating face recognition system-wide..."
bash \$BASE_DIR/scripts/setup_pam.sh --enable-all

echo "------------------------------------------------"
echo "Linux Bonjour v$VERSION Installed Successfully! 🎉"
echo "Let the Face ID era begin."
echo "Hardware permissions and udev rules activated."
echo "------------------------------------------------"
EOF

cat <<EOF > pkg/DEBIAN/prerm
#!/bin/bash
set -e
if [ -f "/usr/share/linux-bonjour/scripts/setup_pam.sh" ]; then
    bash /usr/share/linux-bonjour/scripts/setup_pam.sh --disable-all || true
fi
# Cleanup D-Bus
rm -f /etc/dbus-1/system.d/org.linuxbonjour.conf || true
systemctl reload dbus || true
systemctl stop linux-bonjour || true
systemctl disable linux-bonjour || true
EOF

chmod 755 pkg/DEBIAN/postinst pkg/DEBIAN/prerm

cp src/pam_rs/target/release/libpam_bonjour.so pkg/lib/x86_64-linux-gnu/security/pam_bonjour.so
cp src/bonjour-daemon/target/release/bonjour-daemon pkg/usr/bin/linux-bonjour-daemon
cp src/bonjour-gui/src-tauri/target/release/bonjour-gui pkg/usr/bin/linux-bonjour-gui

mkdir -p pkg/etc/logrotate.d
cp config/linux-bonjour.service pkg/lib/systemd/system/
cp config/linux-bonjour.logrotate pkg/etc/logrotate.d/linux-bonjour
cp org.linuxbonjour.conf pkg/usr/share/linux-bonjour/
cp org.linuxbonjour.policy pkg/usr/share/polkit-1/actions/ 2>/dev/null || true
cp linux-bonjour.desktop pkg/usr/share/applications/
cp src/bonjour-gui/src-tauri/icons/icon.png pkg/usr/share/pixmaps/linux-bonjour.png
cp src/bonjour-gui/src-tauri/icons/icon.png pkg/usr/share/pixmaps/com.kawishika.bonjour-gui.png
cp src/bonjour-gui/src-tauri/icons/icon.png pkg/usr/share/pixmaps/linux-bonjour-gui.png

# 3. Scripts Staging
cp -r scripts pkg/usr/share/linux-bonjour/
cp src/bonjour-gui/src-tauri/icons/icon.png pkg/usr/share/linux-bonjour/logo.png
cp -r src/bonjour-gui/src-tauri/icons pkg/usr/share/linux-bonjour/icons

# 3. Model staging
mkdir -p "$PKG_ROOT/usr/share/linux-bonjour/models"
cp -r src/bonjour-daemon/models/* "$PKG_ROOT/usr/share/linux-bonjour/models/" 2>/dev/null || true

# Create the wrapper script
cat <<EOF > pkg/usr/bin/linux-bonjour
#!/bin/bash
/usr/bin/linux-bonjour-gui "\$@"
EOF
chmod +x pkg/usr/bin/linux-bonjour

# 3. Set Permissions
echo "Setting metadata permissions..."
chmod 755 pkg/DEBIAN/postinst
chmod 755 pkg/DEBIAN/prerm


echo "Staged version: $VERSION"

# 4. Build Package
echo "Building .deb package..."
dpkg-deb --build pkg "linux-bonjour_${VERSION}_amd64.deb"

echo "------------------------------------------------"
echo "Success! Package created: linux-bonjour_${VERSION}_amd64.deb"
echo "Install with: sudo dpkg -i linux-bonjour_${VERSION}_amd64.deb"
echo "------------------------------------------------"
