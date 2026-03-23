# Release v2.3.15

## ✨ Major Architectural Milestone
- **Unlocking the Monolith:** Specialized logic into `InferenceWorker` for high-concurrency processing.
- **AuthSession State Machine:** Robust handling of biometric flows (Enroll/Verify) with clear state transitions.
- **Signature Vault:** Transitioned from flat files to **SQLite** with Hardware-bound **TPM 2.0** encryption.

## 📸 Biometric & AI Enhancements
- **3D Depth sensing:** Native hardware-backed geometric scanning for elite anti-spoofing ([geometry scanning]).
- **Passive Liveness:** New LBP-based texture analysis engine.
- **AntelopeV2 Standard:** Switched to the high-accuracy Antelope recognition engine as the system default.
- **Dual-Engine Pre-loading:** Both `Buffalo_L` and `AntelopeV2` are now pre-downloaded during installation.

## 🛡️ Security & Reliability
- **Boot Sync:** Integrated `sd-notify` to ensure the daemon is ready before GDM/Login prompt appears.
- **Kernel-Level Hardening:** Implemented `SO_PEERCRED` checks and root-only gating for system configuration.
- **PAM Resilience:** Added connection retry loops and specialized service checks for `sudo`, `polkit`, and `login`.
- **Identity Security:** Enabled secure user enrollment and self-deletion without requiring root privileges.

## 🖥️ Modernized GUI (Tauri)
- **Real-time Dashboard:** Live monitoring of camera status, health scores, and active security layers.
- **Model Intelligence:** Dropdown now shows model availability status with status icons (✅ Downloaded / 📥 Missing).
- **Identity Management:** Full lifecycle management of face signatures directly from the desktop.

## ⚡ Performance
- **Vectorized Preprocessing:** Optimized image-to-tensor normalization using vectorized math.
- **Signature Caching:** Instant authentication via in-memory signature caching.

---
**Checksum (SHA256):** `1b37adae3820700f9097a71fdd318892b9d771b97a842e7580d46b9fd7bdca55`
