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
# Clean and recreate staging area (except models to save time)
find pkg -maxdepth 1 -not -name 'DEBIAN' -not -name 'pkg' -not -name 'usr' -exec rm -rf {} + 2>/dev/null || true
mkdir -p pkg/usr/bin
# Preserve existing models if they were already staged
if [ -d "pkg/usr/share/linux-bonjour/models" ]; then
    echo "Staging models from existing cache..."
    mv pkg/usr/share/linux-bonjour/models ./models_tmp
fi
rm -rf pkg/usr pkg/etc
mkdir -p pkg/usr/share/linux-bonjour
if [ -d "./models_tmp" ]; then
    mv ./models_tmp pkg/usr/share/linux-bonjour/models
fi
mkdir -p pkg/lib/x86_64-linux-gnu/security
mkdir -p pkg/usr/bin
mkdir -p pkg/usr/share/linux-bonjour/src
mkdir -p pkg/usr/share/polkit-1/actions
mkdir -p pkg/usr/share/pixmaps
mkdir -p pkg/usr/share/applications

cp src/pam_rs/target/release/libpam_bonjour.so pkg/lib/x86_64-linux-gnu/security/pam_bonjour.so
cp org.linuxbonjour.policy pkg/usr/share/polkit-1/actions/ 2>/dev/null || true
cp linux-bonjour.desktop pkg/usr/share/applications/ 2>/dev/null || true
cp src/gui/assets/logo.png pkg/usr/share/pixmaps/linux-bonjour.png 2>/dev/null || true

mkdir -p pkg/usr/share/linux-bonjour/src/daemon
cp src/daemon/*.py pkg/usr/share/linux-bonjour/src/daemon/
cp -r src/gui pkg/usr/share/linux-bonjour/src/
cp -r scripts config requirements.txt pkg/usr/share/linux-bonjour/
cp src/gui/assets/logo.png pkg/usr/share/linux-bonjour/logo.png

# 3. Pre-download AI Models into Package
echo "Pre-downloading AI models into package (this will take a while but speed up installation)..."
MODELS_STAGING="$PKG_ROOT/usr/share/linux-bonjour/models"
mkdir -p "$MODELS_STAGING"

# Ensure we have a working environment for downloading
if [ ! -d "venv_build" ]; then
    echo "Creating temporary build environment..."
    python3 -m venv venv_build
    ./venv_build/bin/pip install --upgrade pip
    ./venv_build/bin/pip install -r requirements.txt
fi

./venv_build/bin/python src/daemon/init_models.py "$MODELS_STAGING"

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
