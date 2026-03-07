#!/bin/bash

# Linux Hello PAM Manager
# Safely toggle face recognition for system authentication.

PAM_MODULE="pam_hello.so"
COMMON_AUTH="/etc/pam.d/common-auth"
GDM_AUTH="/etc/pam.d/gdm-password"
SDDM_AUTH="/etc/pam.d/sddm"

show_help() {
    echo "Usage: sudo ./setup_pam.sh [command]"
    echo ""
    echo "Commands:"
    echo "  --enable-all     Enable face recognition for all supported services"
    echo "  --disable-all    Disable face recognition system-wide"
    echo "  --status         Show current PAM configuration status"
    echo "  --help           Show this help message"
}

enable_service() {
    local file=$1
    if [ ! -f "$file" ]; then return; fi
    
    if grep -q "$PAM_MODULE" "$file"; then
        echo "Already enabled in $(basename "$file")"
    else
        echo "Enabling in $(basename "$file")..."
        # Insert at the top
        sudo sed -i "1i auth sufficient $PAM_MODULE" "$file"
    fi
}

disable_service() {
    local file=$1
    if [ ! -f "$file" ]; then return; fi
    
    if grep -q "$PAM_MODULE" "$file"; then
        echo "Disabling in $(basename "$file")..."
        sudo sed -i "/$PAM_MODULE/d" "$file"
    else
        echo "Already disabled in $(basename "$file")"
    fi
}

check_status() {
    echo "--- Linux Hello PAM Status ---"
    for f in "$COMMON_AUTH" "$GDM_AUTH" "$SDDM_AUTH"; do
        if [ -f "$f" ]; then
            if grep -q "$PAM_MODULE" "$f"; then
                echo "[ENABLED]  $(basename "$f")"
            else
                echo "[DISABLED] $(basename "$f")"
            fi
        fi
    done
}

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo)"
  exit 1
fi

case "$1" in
    --enable-all)
        enable_service "$COMMON_AUTH"
        enable_service "$GDM_AUTH"
        enable_service "$SDDM_AUTH"
        echo "Face recognition enabled for all services!"
        ;;
    --disable-all)
        disable_service "$COMMON_AUTH"
        disable_service "$GDM_AUTH"
        disable_service "$SDDM_AUTH"
        echo "Face recognition disabled system-wide."
        ;;
    --status)
        check_status
        ;;
    *)
        show_help
        ;;
esac
