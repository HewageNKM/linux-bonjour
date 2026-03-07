#!/bin/bash
set -e

# Linux Hello Debian Package Builder
# Automates the creation of a professional .deb package.

PROJECT_ROOT=$(pwd)
PKG_ROOT="$PROJECT_ROOT/pkg"
VERSION=$(grep "Version:" pkg/DEBIAN/control | awk '{print $2}')

echo "Building Linux Hello version $VERSION..."

# 1. Build Rust PAM Module
echo "Compiling Rust PAM module..."
cd src/pam_rs
cargo build --release
cd "$PROJECT_ROOT"

# 2. Stage Files
echo "Staging files..."
cp src/pam_rs/target/release/libpam_hello.so pkg/usr/lib/security/pam_hello.so

# Clean and sync app files
# We exclude venv, git, and other build artifacts
rm -rf pkg/usr/share/linux-hello/*
mkdir -p pkg/usr/share/linux-hello/src
cp -r src/daemon src/gui pkg/usr/share/linux-hello/src/
cp -r scripts config requirements.txt pkg/usr/share/linux-hello/
# Note: models will be downloaded by init_models.py during postinst or first run

# Create the wrapper script
cat <<EOF > pkg/usr/bin/linux-hello
#!/bin/bash
/usr/share/linux-hello/venv/bin/python /usr/share/linux-hello/src/gui/gui_app.py "\$@"
EOF
chmod +x pkg/usr/bin/linux-hello

# 3. Set Permissions
echo "Setting metadata permissions..."
chmod 755 pkg/DEBIAN/postinst
chmod 755 pkg/DEBIAN/prerm

# 4. Build Package
echo "Building .deb package..."
dpkg-deb --build pkg "linux-hello_${VERSION}_amd64.deb"

echo "------------------------------------------------"
echo "Success! Package created: linux-hello_${VERSION}_amd64.deb"
echo "Install with: sudo dpkg -i linux-hello_${VERSION}_amd64.deb"
echo "------------------------------------------------"
