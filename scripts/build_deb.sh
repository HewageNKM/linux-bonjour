#!/bin/bash
set -e

# Linux Bonjour Debian Package Builder
# Automates the creation of a professional .deb package.

PROJECT_ROOT=$(pwd)
PKG_ROOT="$PROJECT_ROOT/pkg"
VERSION=$(grep "Version:" pkg/DEBIAN/control | awk '{print $2}')

echo "Building Linux Bonjour version $VERSION..."

# 1. Build Rust PAM Module
echo "Compiling Rust PAM module..."
cd src/pam_rs
cargo build --release
cd "$PROJECT_ROOT"

# 2. Stage Files
echo "Staging files..."
# Clean and recreate staging area
rm -rf pkg/usr pkg/etc
mkdir -p pkg/usr/lib/security
mkdir -p pkg/usr/bin
mkdir -p pkg/usr/share/linux-bonjour/src
mkdir -p pkg/usr/share/polkit-1/actions
mkdir -p pkg/usr/share/applications

cp src/pam_rs/target/release/libpam_bonjour.so pkg/usr/lib/security/pam_bonjour.so
cp pkg/usr/share/polkit-1/actions/org.linuxbonjour.policy pkg/usr/share/polkit-1/actions/ 2>/dev/null || cp org.linuxbonjour.policy pkg/usr/share/polkit-1/actions/ 2>/dev/null || true

cp -r src/daemon src/gui pkg/usr/share/linux-bonjour/src/
cp -r scripts config requirements.txt pkg/usr/share/linux-bonjour/
cp src/gui/assets/logo.png pkg/usr/share/linux-bonjour/logo.png
# Note: models will be downloaded by init_models.py during postinst or first run

# Create the wrapper script
cat <<EOF > pkg/usr/bin/linux-bonjour
#!/bin/bash
/usr/share/linux-bonjour/venv/bin/python /usr/share/linux-bonjour/src/gui/gui_app.py "\$@"
EOF
chmod +x pkg/usr/bin/linux-bonjour

# 3. Set Permissions
echo "Setting metadata permissions..."
chmod 755 pkg/DEBIAN/postinst
chmod 755 pkg/DEBIAN/prerm

# 4. Build Package
echo "Building .deb package..."
dpkg-deb --build pkg "linux-bonjour_${VERSION}_amd64.deb"

echo "------------------------------------------------"
echo "Success! Package created: linux-bonjour_${VERSION}_amd64.deb"
echo "Install with: sudo dpkg -i linux-bonjour_${VERSION}_amd64.deb"
echo "------------------------------------------------"
