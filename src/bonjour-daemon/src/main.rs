mod onnx_utils;
mod signature_utils;
mod ipc_utils;
mod security_utils;

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::sync::Mutex;
use nokhwa::utils::{RequestedFormat, RequestedFormatType};
use nokhwa::pixel_format::RgbFormat;
use nokhwa::Camera;
use serde::{Serialize, Deserialize};
use anyhow::Result;
use image::DynamicImage;
use onnx_utils::InferenceEngine;
use signature_utils::SignatureStore;
use ipc_utils::{UdsServer, DaemonRequest, DaemonResponse, CameraInfo};
use security_utils::{EncryptionProvider, PlainProvider, SoftwareProvider, TpmProvider};

#[derive(Serialize, Deserialize, Clone)]
struct DaemonConfig {
    threshold: f32,
    smile_required: bool,
    autocapture: bool,
    liveness_enabled: bool,
    liveness_threshold: f32,
    ask_permission: bool,
    retry_limit: u32,
    camera_path: Option<String>,
}

impl DaemonConfig {
    fn default() -> Self {
        Self {
            threshold: 0.38,
            smile_required: false,
            autocapture: false,
            liveness_enabled: true,
            liveness_threshold: 0.50,
            ask_permission: false,
            retry_limit: 3,
            camera_path: None,
        }
    }

    fn load() -> Self {
        let path = "/etc/linux-bonjour/config.json";
        if let Ok(data) = std::fs::read_to_string(path) {
            if let Ok(config) = serde_json::from_str(&data) {
                return config;
            }
        }
        Self::default()
    }

    fn save(&self) -> Result<()> {
        let path = "/etc/linux-bonjour/config.json";
        let data = serde_json::to_string_pretty(self)?;
        std::fs::create_dir_all("/etc/linux-bonjour")?;
        std::fs::write(path, data)?;
        Ok(())
    }
}

fn run_zenity_approval(user: &str) -> bool {
    println!("🖥️ Attempting graphical authorization for user: {}", user);
    let xauth = format!("/home/{}/.Xauthority", user);
    let status = std::process::Command::new("sudo")
        .args([
            "-u", user,
            "DISPLAY=:0",
            &format!("XAUTHORITY={}", xauth),
            "zenity",
            "--question",
            "--title=Linux Bonjour",
            "--text=🐧 Allow face recognition authentication?",
            "--timeout=15",
            "--ok-label=Allow",
            "--cancel-label=Deny"
        ])
        .status();
    
    match status {
        Ok(s) => s.success(),
        Err(_) => {
            println!("⚠️ Zenity dialog failed to launch (No X11 context?)");
            false
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    println!("🐧 Linux Bonjour Rust Daemon (Async UDS Mode)");
    
    // 1. Load Configuration
    let config = Arc::new(Mutex::new(DaemonConfig::load()));

    // 2. Initialize Engine & Security
    println!("🤖 Initializing AI Engine...");
    let det_path = "/usr/share/linux-bonjour/models/det_10g.onnx";
    let rec_path = "/usr/share/linux-bonjour/models/arcface_w600k.onnx";
    
    let engine_res = InferenceEngine::new(det_path, rec_path);
    let engine = match engine_res {
        Ok(e) => Arc::new(Mutex::new(e)),
        Err(e) => {
            eprintln!("⚠️ AI Models not found: {}. Waiting for GUI download.", e);
            return Err(anyhow::anyhow!("Critical AI models missing. Please ensure /usr/share/linux-bonjour/models exists."));
        }
    };
    
    println!("🔐 Initializing Security Provider...");
    let tpm_active = Arc::new(AtomicBool::new(false));
    let tpm_active_clone = Arc::clone(&tpm_active);
    
    let provider: Arc<dyn EncryptionProvider + Send + Sync> = match TpmProvider::new() {
        Ok(tpm) => {
            println!("🔒 Biometric TPM Active: Using Endorsement Hardware Sealing");
            tpm_active.store(true, Ordering::SeqCst);
            Arc::new(tpm)
        },
        Err(e) => {
            println!("⚠️ TPM Initialization Failed: {} - Defaulting to Software Fallback", e);
            tpm_active.store(false, Ordering::SeqCst);
            match SoftwareProvider::new() {
                Ok(sw) => Arc::new(sw),
                Err(_) => Arc::new(PlainProvider),
            }
        }
    };

    let signature_store = Arc::new(SignatureStore::new("/var/lib/linux-bonjour/signatures", provider)?);
    let system_enabled = Arc::new(AtomicBool::new(true));
    
    let acceleration = if engine.lock().await.has_gpu() { "Active (GPU Accelerator)" } else { "Active (CPU/OpenVINO)" }.to_string();

    println!("✅ AI Models and Secure Storage ready.");

    // 3. Start UDS Server
    let server = UdsServer::new("/run/linux-bonjour/daemon.sock");
    
    let engine_cloned = Arc::clone(&engine);
    let store_cloned = Arc::clone(&signature_store);
    let enabled_cloned = Arc::clone(&system_enabled);
    let config_cloned = Arc::clone(&config);
    let accel_cloned = acceleration.clone();
    let tpm_state_cloned = Arc::clone(&tpm_active_clone);

    server.start(move |req, tx| {
        let engine = Arc::clone(&engine_cloned);
        let store = Arc::clone(&store_cloned);
        let enabled = Arc::clone(&enabled_cloned);
        let config = Arc::clone(&config_cloned);
        let accel_locked = accel_cloned.clone();
        let tpm_state = Arc::clone(&tpm_state_cloned);
        
        async move {
            match req {
                DaemonRequest::SetEnabled { enabled: val } => {
                    enabled.store(val, Ordering::SeqCst);
                    println!("⚙️ System {}", if val { "ENABLED" } else { "DISABLED" });
                    let _ = tx.send(DaemonResponse::Status { enabled: val }).await;
                },
                DaemonRequest::GetStatus => {
                    let is_enabled = enabled.load(Ordering::SeqCst);
                    let _ = tx.send(DaemonResponse::Status { enabled: is_enabled }).await;
                },
                DaemonRequest::ListIdentities => {
                    match store.list_identities() {
                        Ok(users) => { let _ = tx.send(DaemonResponse::IdentityList { users }).await; },
                        Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                    }
                },
                DaemonRequest::DeleteIdentity { user } => {
                    match store.delete_identity(&user) {
                        Ok(_) => { let _ = tx.send(DaemonResponse::ActionSuccess { msg: format!("Identity '{}' deleted", user) }).await; },
                        Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                    }
                },
                DaemonRequest::UpdateConfig { threshold, smile_required, autocapture, liveness_enabled, liveness_threshold, ask_permission, retry_limit, camera_path } => {
                    let mut cfg = config.lock().await;
                    cfg.threshold = threshold;
                    cfg.smile_required = smile_required;
                    cfg.autocapture = autocapture;
                    cfg.liveness_enabled = liveness_enabled;
                    cfg.liveness_threshold = liveness_threshold;
                    cfg.ask_permission = ask_permission;
                    cfg.retry_limit = retry_limit;
                    cfg.camera_path = camera_path;
                    
                    if let Err(e) = cfg.save() {
                        eprintln!("❌ Failed to save configuration: {}", e);
                    }
                    
                    println!("⚙️ Configuration updated and persisted.");
                    let _ = tx.send(DaemonResponse::ActionSuccess { msg: "Configuration updated".to_string() }).await;
                },
                DaemonRequest::GetHardwareStatus => {
                    let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux).unwrap_or_default();
                    let camera_type = if devices.iter().any(|d| d.human_name().to_lowercase().contains("ir") || d.human_name().to_lowercase().contains("infrared")) {
                        "IR Camera (Detected)".to_string()
                    } else {
                        "RGB Camera (Standard)".to_string()
                    };
                    
                    let tpm_string = if tpm_state.load(Ordering::SeqCst) {
                        "Active (Device Secured)".to_string()
                    } else {
                        "Software Fallback (Active)".to_string()
                    };
                    
                    let _ = tx.send(DaemonResponse::HardwareStatus {
                        tpm: tpm_string,
                        acceleration: accel_locked,
                        camera: camera_type,
                        enabled: enabled.load(Ordering::SeqCst),
                    }).await;
                },
                DaemonRequest::DownloadModel { name } => {
                    let model_url = match name.as_str() {
                        "buffalo_l" => "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
                        "buffalo_s" => "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip",
                        "antelope" => "https://github.com/deepinsight/insightface/releases/download/v0.7/antelopev2.zip",
                        _ => {
                            let _ = tx.send(DaemonResponse::Failure { reason: format!("Unknown model: {}", name) }).await;
                            return;
                        }
                    };

                    let name_cloned = name.clone();
                    tokio::spawn(async move {
                        let target_path = format!("/usr/share/linux-bonjour/models/{}", name_cloned);
                        let _ = std::fs::create_dir_all(&target_path);
                        
                        let _ = std::process::Command::new("curl")
                            .arg("-L")
                            .arg(model_url)
                            .arg("-o")
                            .arg(format!("{}/weights.zip", target_path))
                            .status();
                            
                        let _ = std::process::Command::new("unzip")
                            .arg("-j")
                            .arg("-o")
                            .arg("-q")
                            .arg(format!("{}/weights.zip", target_path))
                            .arg("-d")
                            .arg(&target_path)
                            .status();
                            
                        let _ = std::fs::remove_file(format!("{}/weights.zip", target_path));

                        if std::path::Path::new(&format!("{}/w600k_r50.onnx", target_path)).exists() {
                            let _ = std::fs::rename(
                                format!("{}/w600k_r50.onnx", target_path),
                                format!("{}/arcface_w600k.onnx", target_path),
                            );
                        }
                    });

                    let _ = tx.send(DaemonResponse::ActionSuccess { msg: format!("Model {} download started in background.", name) }).await;
                },
                DaemonRequest::GetCameraList => {
                    let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux).unwrap_or_default();
                    let list: Vec<CameraInfo> = devices.iter().map(|d| CameraInfo {
                        name: d.human_name(),
                        path: d.index().to_string(),
                    }).collect();
                    let _ = tx.send(DaemonResponse::CameraList { devices: list }).await;
                },
                DaemonRequest::GetConfig => {
                    let cfg = config.lock().await;
                    let _ = tx.send(DaemonResponse::Config {
                        threshold: cfg.threshold,
                        smile_required: cfg.smile_required,
                        autocapture: cfg.autocapture,
                        liveness_enabled: cfg.liveness_enabled,
                        liveness_threshold: cfg.liveness_threshold,
                        ask_permission: cfg.ask_permission,
                        retry_limit: cfg.retry_limit,
                        camera_path: cfg.camera_path.clone(),
                    }).await;
                },
                DaemonRequest::Verify { user, bypass_consent } => {
                    let cfg = config.lock().await;
                    
                    if !enabled.load(Ordering::SeqCst) {
                        println!("🚫 [Bonjour] System is globally DISABLED. Skipping verification.");
                        let _ = tx.send(DaemonResponse::Failure { reason: "System is globally disabled".to_string() }).await;
                        return;
                    }

                    if !bypass_consent && cfg.ask_permission {
                        if !run_zenity_approval(&user) {
                            println!("🚫 Authorization denied or Zenity failed for user: {}", user);
                            let _ = tx.send(DaemonResponse::Info { msg: "CONSENT_REQUIRED".to_string() }).await;
                            return;
                        }
                    }

                    println!("🔍 IPC: Verification request for user: {}", user);
                    
                    let camera_path_override = cfg.camera_path.clone();
                    let threshold = cfg.threshold;
                    let liveness_threshold = cfg.liveness_threshold;
                    let smile_required = cfg.smile_required;

                    // Search Loop: Try to recognize for up to 3 seconds
                    let start_time = std::time::Instant::now();
                    let timeout = std::time::Duration::from_secs(3);
                    let mut last_error = "No face detected".to_string();

                    while start_time.elapsed() < timeout {
                        // Send real-time scanning feedback
                        let _ = tx.send(DaemonResponse::Scanning { 
                            msg: "Scanning...".to_string() 
                        }).await;

                        let capture_result: Result<DynamicImage> = (|| {
                            let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux)?;
                            if devices.is_empty() { anyhow::bail!("No camera found"); }
                            
                            let mut sorted_devices = devices.clone();
                            sorted_devices.sort_by_key(|d| {
                                if let Some(ref path) = camera_path_override {
                                    if d.human_name() == *path || d.index().to_string() == *path {
                                        return 0;
                                    }
                                }
                                let name = d.human_name().to_lowercase();
                                if name.contains("ir") || name.contains("infrared") { 1 } else { 2 }
                            });

                            for dev in sorted_devices {
                                let format_strategies = vec![RequestedFormatType::AbsoluteHighestResolution, RequestedFormatType::None];
                                for strategy in format_strategies {
                                    let format = RequestedFormat::new::<RgbFormat>(strategy);
                                    if let Ok(mut camera) = Camera::with_backend(dev.index().clone(), format, nokhwa::utils::ApiBackend::Video4Linux) {
                                        if camera.open_stream().is_ok() {
                                            for _ in 0..2 { let _ = camera.frame(); }
                                            if let Ok(frame) = camera.frame() {
                                                let dyn_img = frame.decode_image::<RgbFormat>()?;
                                                let _ = camera.stop_stream();
                                                return Ok(DynamicImage::ImageRgb8(dyn_img));
                                            }
                                        }
                                    }
                                }
                            }
                            Err(anyhow::anyhow!("Capture failed"))
                        })();

                        match capture_result {
                            Ok(dyn_img) => {
                                let mut engine_lock = engine.lock().await;
                                if let Ok(detections) = engine_lock.detect_faces(&dyn_img) {
                                    if detections.is_empty() {
                                        last_error = "No face detected".to_string();
                                    } else {
                                        let aligned = engine_lock.align_face(&dyn_img, &detections[0].landmarks);
                                        if let Ok(embedding) = engine_lock.get_face_embedding(&aligned) {
                                            if let Ok(saved_embedding) = store.load_signature(&user) {
                                                let score = SignatureStore::cosine_similarity(&embedding, &saved_embedding);
                                                let liveness_score = detections[0].liveness_score;
                                                
                                                if score > threshold {
                                                    if !smile_required || liveness_score > liveness_threshold {
                                                        println!("✅ [Bonjour] Success: {}", user);
                                                        let _ = tx.send(DaemonResponse::Success { user: user.clone() }).await;
                                                        return;
                                                    } else {
                                                        last_error = format!("Liveness failed ({:.2})", liveness_score);
                                                    }
                                                } else {
                                                    last_error = format!("Match failed (score: {:.2})", score);
                                                }
                                            } else {
                                                println!("⚠️ [Bonjour] No signature for {}", user);
                                                let _ = tx.send(DaemonResponse::Failure { reason: format!("User '{}' not found", user) }).await;
                                                return;
                                            }
                                        }
                                    }
                                }
                            },
                            Err(e) => last_error = e.to_string(),
                        }
                        tokio::time::sleep(tokio::time::Duration::from_millis(200)).await;
                    }

                    println!("❌ [Bonjour] Verification timeout");
                    let _ = tx.send(DaemonResponse::Failure { reason: format!("Timeout: {}", last_error) }).await;
                },
                DaemonRequest::Enroll { user } => {
                    let camera_path_override = {
                        let cfg = config.lock().await;
                        cfg.camera_path.clone()
                    };
                    
                    let capture_result: Result<DynamicImage> = (|| {
                        let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux)?;
                        if devices.is_empty() { anyhow::bail!("No camera found"); }
                        
                        let mut sorted_devices = devices.clone();
                        sorted_devices.sort_by_key(|d| {
                            if let Some(ref path) = camera_path_override {
                                if d.human_name() == *path || d.index().to_string() == *path {
                                    return 0;
                                }
                            }
                            let name = d.human_name().to_lowercase();
                            if name.contains("ir") || name.contains("infrared") { 1 } else { 2 }
                        });

                        for dev in sorted_devices {
                            let format_strategies = vec![RequestedFormatType::AbsoluteHighestResolution, RequestedFormatType::None];
                            for strategy in format_strategies {
                                let format = RequestedFormat::new::<RgbFormat>(strategy);
                                if let Ok(mut camera) = Camera::with_backend(dev.index().clone(), format, nokhwa::utils::ApiBackend::Video4Linux) {
                                    if camera.open_stream().is_ok() {
                                        for _ in 0..5 { let _ = camera.frame(); std::thread::sleep(std::time::Duration::from_millis(100)); }
                                        if let Ok(frame) = camera.frame() {
                                            let dyn_img = frame.decode_image::<RgbFormat>()?;
                                            let _ = camera.stop_stream();
                                            return Ok(DynamicImage::ImageRgb8(dyn_img));
                                        }
                                    }
                                }
                            }
                        }
                        Err(anyhow::anyhow!("Capture failed"))
                    })();

                    match capture_result {
                        Ok(dyn_img) => {
                            let mut engine_lock = engine.lock().await;
                            match engine_lock.detect_faces(&dyn_img) {
                                Ok(detections) => {
                                    if detections.is_empty() {
                                        let _ = tx.send(DaemonResponse::Failure { reason: "No face detected".to_string() }).await;
                                    } else {
                                        let aligned = engine_lock.align_face(&dyn_img, &detections[0].landmarks);
                                        match engine_lock.get_face_embedding(&aligned) {
                                            Ok(embedding) => {
                                                match store.save_signature(&user, &embedding) {
                                                    Ok(_) => { let _ = tx.send(DaemonResponse::Success { user: user.clone() }).await; },
                                                    Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                                                }
                                            },
                                            Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                                        }
                                    }
                                },
                                Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                            }
                        },
                        Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                    }
                },
            }
        }
    }).await?;

    Ok(())
}
