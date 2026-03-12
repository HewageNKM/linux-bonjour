#!/bin/bash
set -e

# Linux Bonjour Release Automator
# Usage: ./scripts/release.sh <version>

if [ -z "$1" ]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 2.1.4"
    exit 1
fi

NEW_VERSION=$1
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"
cd "$PROJECT_ROOT"

# 1. Branch Safety Check
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "main" && "$CURRENT_BRANCH" != "dev" ]]; then
    echo "❌ Error: You must be on 'main' or 'dev' branch to release."
    exit 1
fi

# 2. Working Tree Check
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️ Warning: You have uncommitted changes. Please commit or stash them first."
    exit 1
fi

echo "🚀 Starting release process for v$NEW_VERSION..."

# 3. Update Versions
echo "📝 Updating version numbers..."

# 3.1 scripts/build_deb.sh
sed -i "s/^VERSION=\".*\"/VERSION=\"$NEW_VERSION\"/" scripts/build_deb.sh

# 3.2 src/bonjour-daemon/Cargo.toml
sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" src/bonjour-daemon/Cargo.toml

# 3.3 src/pam_rs/Cargo.toml
sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" src/pam_rs/Cargo.toml

# 3.4 src/bonjour-gui/src-tauri/tauri.conf.json
sed -i "s/\"version\": \".*\"/\"version\": \"$NEW_VERSION\"/" src/bonjour-gui/src-tauri/tauri.conf.json

# 3.5 README.md (Installation snippet)
sed -i "s/linux-bonjour_.*_amd64.deb/linux-bonjour_${NEW_VERSION}_amd64.deb/g" README.md

# 4. Commit and Tag
echo "💾 Committing version bump..."
git add scripts/build_deb.sh src/bonjour-daemon/Cargo.toml src/pam_rs/Cargo.toml src/bonjour-gui/src-tauri/tauri.conf.json README.md
git commit -m "chore: bump version to v$NEW_VERSION"
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"

# 5. Build Package
echo "📦 Building project..."
bash scripts/build_deb.sh

# 6. Generate Checksum
DEB_FILE="linux-bonjour_${NEW_VERSION}_amd64.deb"
if [ -f "$DEB_FILE" ]; then
    echo "🛡️ Generating SHA256 checksum..."
    sha256sum "$DEB_FILE" > "${DEB_FILE}.sha256"
    echo "✅ Checksum generated: $(cat ${DEB_FILE}.sha256)"
else
    echo "❌ Error: .deb package not found after build."
    exit 1
fi

echo "------------------------------------------------"
echo "🎉 Release v$NEW_VERSION prepared successfully!"
echo "------------------------------------------------"
echo "Next steps:"
echo "1. Push changes:    git push origin $CURRENT_BRANCH --tags"
echo "2. Upload Assets to GitHub Release v$NEW_VERSION:"
echo "   - $DEB_FILE"
echo "   - ${DEB_FILE}.sha256"
echo "------------------------------------------------"
