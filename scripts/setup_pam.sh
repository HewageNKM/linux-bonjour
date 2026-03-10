#!/bin/bash

# Linux Bonjour PAM Manager
# Safely toggle face recognition for system authentication.

PAM_MODULE="pam_bonjour.so"
COMMON_AUTH="/etc/pam.d/common-auth"
GDM_AUTH="/etc/pam.d/gdm-password"
SDDM_AUTH="/etc/pam.d/sddm"

show_help() {
    echo "Usage: [sudo] ./setup_pam.sh [command]"
    echo ""
    echo "Commands:"
    echo "  --enable-all     Enable face recognition for all supported services (requires root)"
    echo "  --disable-all    Disable face recognition system-wide (requires root)"
    echo "  --status         Show current PAM configuration status"
    echo "  --help           Show this help message"
}

require_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "Error: This command requires root privileges (sudo)."
        exit 1
    fi
}

enable_service() {
    local file=$1
    if [ ! -f "$file" ]; then return; fi
    
    # Aggressive Legacy Purge (v1.6.2 Stability)
    if grep -q "pam_hello.so" "$file"; then
        echo "Purging legacy pam_hello.so from $(basename "$file")..."
        sed -i "/pam_hello.so/d" "$file"
    fi

    if grep -q "$PAM_MODULE" "$file"; then
        echo "Already enabled in $(basename "$file")"
    else
        echo "Enabling in $(basename "$file")..."
        # Insert at the top as sufficient
        sed -i "1i auth sufficient $PAM_MODULE" "$file"
    fi
}

disable_service() {
    local file=$1
    if [ ! -f "$file" ]; then return; fi
    
    if grep -q "$PAM_MODULE" "$file"; then
        echo "Disabling in $(basename "$file")..."
        sed -i "/$PAM_MODULE/d" "$file"
    else
        echo "Already disabled in $(basename "$file")"
    fi
}

check_status() {
    # This script is idempotent: it can be run multiple times safely.
    SERVICES=("$COMMON_AUTH" "$GDM_AUTH" "$SDDM_AUTH" "/etc/pam.d/lightdm" "/etc/pam.d/sudo" "/etc/pam.d/polkit-1" "/etc/pam.d/su")
    for f in "${SERVICES[@]}"; do
        if [ -f "$f" ]; then
            if grep -q "$PAM_MODULE" "$f" 2>/dev/null; then
                echo "[ENABLED]  $(basename "$f")"
            else
                echo "[DISABLED] $(basename "$f")"
            fi
        fi
    done
}

case "$1" in
    --enable-all)
        require_root
        enable_service "$COMMON_AUTH"
        enable_service "$GDM_AUTH"
        enable_service "$SDDM_AUTH"
        enable_service "/etc/pam.d/lightdm"
        enable_service "/etc/pam.d/sudo"
        enable_service "/etc/pam.d/polkit-1"
        echo "Face recognition enabled system-wide!"
        ;;
    --disable-all)
        require_root
        disable_service "$COMMON_AUTH"
        disable_service "$GDM_AUTH"
        disable_service "$SDDM_AUTH"
        disable_service "/etc/pam.d/lightdm"
        disable_service "/etc/pam.d/sudo"
        disable_service "/etc/pam.d/polkit-1"
        echo "Face recognition disabled system-wide."
        ;;
    --enable-login)
        require_root
        enable_service "$GDM_AUTH"
        enable_service "$SDDM_AUTH"
        enable_service "/etc/pam.d/lightdm"
        ;;
    --disable-login)
        require_root
        disable_service "$GDM_AUTH"
        disable_service "$SDDM_AUTH"
        disable_service "/etc/pam.d/lightdm"
        ;;
    --enable-sudo)
        require_root
        enable_service "/etc/pam.d/sudo"
        ;;
    --disable-sudo)
        require_root
        disable_service "/etc/pam.d/sudo"
        ;;
    --enable-polkit)
        require_root
        enable_service "/etc/pam.d/polkit-1"
        ;;
    --disable-polkit)
        require_root
        disable_service "/etc/pam.d/polkit-1"
        ;;
    --status)
        check_status
        ;;
    *)
        show_help
        ;;
esac
