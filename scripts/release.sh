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

# 7. Generate Release Notes
RELEASE_NOTES_FILE="release_notes_v${NEW_VERSION}.md"
cat <<EOF > "$RELEASE_NOTES_FILE"
# Release v$NEW_VERSION

## ✨ Major Architectural Milestone
- **Unlocking the Monolith:** Specialized logic into \`InferenceWorker\` for high-concurrency processing.
- **AuthSession State Machine:** Robust handling of biometric flows (Enroll/Verify) with clear state transitions.
- **Signature Vault:** Transitioned from flat files to **SQLite** with Hardware-bound **TPM 2.0** encryption.

## 📸 Biometric & AI Enhancements
- **3D Depth sensing:** Native hardware-backed geometric scanning for elite anti-spoofing ([geometry scanning]).
- **Passive Liveness:** New LBP-based texture analysis engine.
- **AntelopeV2 Standard:** Switched to the high-accuracy Antelope recognition engine as the system default.
- **Dual-Engine Pre-loading:** Both \`Buffalo_L\` and \`AntelopeV2\` are now pre-downloaded during installation.

## 🛡️ Security & Reliability
- **Boot Sync:** Integrated \`sd-notify\` to ensure the daemon is ready before GDM/Login prompt appears.
- **Kernel-Level Hardening:** Implemented \`SO_PEERCRED\` checks and root-only gating for system configuration.
- **PAM Resilience:** Added connection retry loops and specialized service checks for \`sudo\`, \`polkit\`, and \`login\`.
- **Identity Security:** Enabled secure user enrollment and self-deletion without requiring root privileges.

## 🖥️ Modernized GUI (Tauri)
- **Real-time Dashboard:** Live monitoring of camera status, health scores, and active security layers.
- **Model Intelligence:** Dropdown now shows model availability status with status icons (✅ Downloaded / 📥 Missing).
- **Identity Management:** Full lifecycle management of face signatures directly from the desktop.

## ⚡ Performance
- **Vectorized Preprocessing:** Optimized image-to-tensor normalization using vectorized math.
- **Signature Caching:** Instant authentication via in-memory signature caching.

---
**Checksum (SHA256):** \`$(cat ${DEB_FILE}.sha256 | awk '{print $1}')\`
EOF

echo "📝 Release notes generated: $RELEASE_NOTES_FILE"
echo "Next steps:"
echo "1. Push changes:    git push origin $CURRENT_BRANCH --tags"
echo "2. Create GitHub Release v$NEW_VERSION using the generated notes."
echo "3. Upload Assets:"
echo "   - $DEB_FILE"
echo "   - ${DEB_FILE}.sha256"
echo "------------------------------------------------"
