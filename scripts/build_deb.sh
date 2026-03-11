#!/bin/bash
set -e

# Linux Bonjour Debian Package Builder
# Automates the creation of a professional .deb package.

# v1.1.10: Make script robust to execution directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"
cd "$PROJECT_ROOT"

PKG_ROOT="$PROJECT_ROOT/pkg"

echo "Building Linux Bonjour..."
echo "Project Root: $PROJECT_ROOT"

# 1. Build Rust PAM Module
echo "Compiling Rust PAM module..."
cd "$PROJECT_ROOT/src/pam_rs"
cargo build --release
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
Version: 1.8.0
Section: utils
Priority: optional
Architecture: amd64
Maintainer: HewageNKM <[EMAIL_ADDRESS]>
Depends: python3, python3-pip, python3-venv, libpam0g, build-essential, cmake, libxcb-cursor0, libgl1, libglib2.0-0, python3-tk, xvfb, python3-gi, gir1.2-appindicator3-0.1, zenity, libnotify-bin, tpm2-tools, upower, libgomp1, libtss2-dev, libgirepository-2.0-dev, libcairo2-dev, python3-dev, pkg-config, libdbus-1-dev
Description:
  Linux Bonjour - Professional biometric face-recognition authentication.
  A secure, light-weight face-recognition authentication system for Linux.
  Includes a Rust-based PAM module and a high-performance Python AI daemon.
EOF

cat <<EOF > pkg/DEBIAN/postinst
#!/bin/bash
set -e
BASE_DIR="/usr/share/linux-bonjour"
VENV="\$BASE_DIR/venv"
MODELS_DIR="\$BASE_DIR/models"
echo "Configuring Linux Bonjour v1.8.0 Nitro Release..."

# 1. Setup Virtual Environment
if [ ! -f "\$VENV/bin/pip" ]; then
    echo "Creating (or repairing) virtual environment..."
    rm -rf "\$VENV"
    python3 -m venv --system-site-packages "\$VENV"
fi

# Ensure system-site-packages is enabled (in case of existing venv)
sed -i 's/include-system-site-packages = false/include-system-site-packages = true/' "\$VENV/pyvenv.cfg"

# 2. Install dependencies
echo "Installing Python dependencies (this may take a minute)..."
"\$VENV/bin/pip" install --upgrade pip > /dev/null 2>&1 || true
"\$VENV/bin/pip" install PyGObject openvino nncf # Nitro Requirements
"\$VENV/bin/pip" install -r "\$BASE_DIR/requirements.txt"

# 2.2 Setup D-Bus System Policy
if [ -f "\$BASE_DIR/org.linuxbonjour.conf" ]; then
    echo "Installing D-Bus System Policy..."
    cp "\$BASE_DIR/org.linuxbonjour.conf" /etc/dbus-1/system.d/
    systemctl reload dbus
fi

# 2.1 Setup Persistent Infrastructure (Fixes Namespace 226 & Read-only errors)
mkdir -p /var/log/linux-bonjour
chown root:root /var/log/linux-bonjour
chmod 755 /var/log/linux-bonjour

mkdir -p /var/lib/linux-bonjour/users
chown root:root /var/lib/linux-bonjour
chmod 777 /var/lib/linux-bonjour/users

# 3. Initialize AI Models
echo "Initializing default AI models (buffalo_l)..."
mkdir -p "\$MODELS_DIR"
chmod 777 "\$MODELS_DIR"
"\$VENV/bin/python" "\$BASE_DIR/scripts/init_models.py" "\$MODELS_DIR" buffalo_l

# 4. Camera Permission Hardening (v1.1.9)
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

# 5. Final Permissions Setup
chown -R root:root \$BASE_DIR
chmod -R 755 \$BASE_DIR
chmod -R 777 \$BASE_DIR/models
chmod -R 777 \$BASE_DIR/config/users
chmod 666 \$BASE_DIR/config/config.json

# 6. PAM Module Setup (CRITICAL)
chown root:root /lib/x86_64-linux-gnu/security/pam_bonjour.so
chmod 644 /lib/x86_64-linux-gnu/security/pam_bonjour.so

# 7. Systemd Service Activation
echo "Setting up background service..."
systemctl daemon-reload
systemctl enable linux-bonjour
systemctl restart linux-bonjour

# 8. Automatic PAM Activation
echo "Activating face recognition system-wide..."
bash \$BASE_DIR/scripts/setup_pam.sh --enable-all

echo "------------------------------------------------"
echo "Linux Bonjour v1.8.0 Installed Successfully! 🎉"
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
mkdir -p pkg/etc/logrotate.d
cp config/linux-bonjour.service pkg/lib/systemd/system/
cp config/linux-bonjour.logrotate pkg/etc/logrotate.d/linux-bonjour
cp org.linuxbonjour.conf pkg/usr/share/linux-bonjour/
cp org.linuxbonjour.policy pkg/usr/share/polkit-1/actions/ 2>/dev/null || true
cp linux-bonjour.desktop pkg/usr/share/applications/ 2>/dev/null || true
cp src/gui/assets/logo.png pkg/usr/share/pixmaps/linux-bonjour.png 2>/dev/null || true

mkdir -p pkg/usr/share/linux-bonjour/src/daemon
cp src/daemon/*.py pkg/usr/share/linux-bonjour/src/daemon/
cp -r src/gui pkg/usr/share/linux-bonjour/src/
cp -r scripts config requirements.txt pkg/usr/share/linux-bonjour/
cp src/gui/assets/logo.png pkg/usr/share/linux-bonjour/logo.png

# 3. Model staging (Removed pre-downloading to reduce .deb size)
# Models will be downloaded during postinst on the target system.
mkdir -p "$PKG_ROOT/usr/share/linux-bonjour/models"

# Create the wrapper script
cat <<EOF > pkg/usr/bin/linux-bonjour
#!/bin/bash
/usr/share/linux-bonjour/venv/bin/python /usr/share/linux-bonjour/src/gui/linux_bonjour_gui.py "\$@"
EOF
chmod +x pkg/usr/bin/linux-bonjour

# 3. Set Permissions
echo "Setting metadata permissions..."
chmod 755 pkg/DEBIAN/postinst
chmod 755 pkg/DEBIAN/prerm


VERSION=$(grep "Version:" pkg/DEBIAN/control | awk '{print $2}')
echo "Staged version: $VERSION"

# 4. Build Package
echo "Building .deb package..."
dpkg-deb --build pkg "linux-bonjour_${VERSION}_amd64.deb"

echo "------------------------------------------------"
echo "Success! Package created: linux-bonjour_${VERSION}_amd64.deb"
echo "Install with: sudo dpkg -i linux-bonjour_${VERSION}_amd64.deb"
echo "------------------------------------------------"
