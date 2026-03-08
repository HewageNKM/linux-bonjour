#!/bin/bash
set -e

# Linux Bonjour Purge Script
# Removes all traces of the application for a clean reinstall.

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo bash scripts/purge.sh)"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "--- Purging Linux Bonjour ---"

# 1. Disable PAM Integration
if [ -f "$PROJECT_DIR/scripts/setup_pam.sh" ]; then
    echo "Disabling PAM integration..."
    bash "$PROJECT_DIR/scripts/setup_pam.sh" --disable-all || true
fi

# 2. Stop and Disable Service
echo "Stopping and removing systemd service..."
systemctl stop linux-bonjour || true
systemctl disable linux-bonjour || true
rm -f /etc/systemd/system/linux-bonjour.service
systemctl daemon-reload

# 3. Remove Debian Package (if installed)
if dpkg -s linux-bonjour >/dev/null 2>&1; then
    echo "Removing debian package..."
    dpkg -P linux-bonjour || true
fi

# 4. Remove System Files
echo "Cleaning up system directories..."
rm -rf /usr/share/linux-bonjour
rm -f /usr/bin/linux-bonjour
rm -f /usr/share/applications/linux-bonjour*
rm -f /usr/share/polkit-1/actions/org.linuxbonjour.policy

# 5. Remove PAM Modules
echo "Removing PAM modules..."
rm -f /lib/security/pam_bonjour.so
rm -f /lib/x86_64-linux-gnu/security/pam_bonjour.so
rm -f /usr/lib/x86_64-linux-gnu/security/pam_bonjour.so

# 6. Clean Local Project Artifacts
echo "Cleaning local virtual environment and build artifacts..."
rm -rf "$PROJECT_DIR/venv"
rm -rf "$PROJECT_DIR/pkg/usr"
rm -rf "$PROJECT_DIR/src/pam_rs/target"

echo "------------------------------------------------"
echo "Purge complete! Everything has been removed. 🧹"
echo "You can now run 'sudo bash scripts/install.sh' for a fresh install."
echo "------------------------------------------------"
