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
use base64::{Engine as _, engine::general_purpose};
use std::io::Cursor;
#[derive(Serialize, Deserialize, Clone)]
#[serde(default)]
struct DaemonConfig {
    threshold: f32,
    smile_required: bool,
    autocapture: bool,
    liveness_enabled: bool,
    liveness_threshold: f32,
    ask_permission: bool,
    retry_limit: u32,
    camera_path: Option<String>,
    active_model: String,
    enable_login: bool,
    enable_sudo: bool,
    enable_polkit: bool,
}

impl Default for DaemonConfig {
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
            active_model: "buffalo_l".to_string(),
            enable_login: true,
            enable_sudo: true,
            enable_polkit: true,
        }
    }
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
            active_model: "buffalo_l".to_string(),
            enable_login: true,
            enable_sudo: true,
            enable_polkit: true,
        }
    }

    fn load() -> Self {
        let path = "/etc/linux-bonjour/config.json";
        if let Ok(data) = std::fs::read_to_string(path) {
            if let Ok(mut config) = serde_json::from_str::<DaemonConfig>(&data) {
                if config.active_model.is_empty() {
                    config.active_model = "buffalo_l".to_string();
                }
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
    
    // 0. Single Instance Check (PID File)
    let pid_path = "/run/linux-bonjour/daemon.pid";
    if let Ok(existing_pid) = std::fs::read_to_string(pid_path) {
        if let Ok(pid) = existing_pid.trim().parse::<i32>() {
            // Check if process still exists
            if std::path::Path::new(&format!("/proc/{}", pid)).exists() {
                eprintln!("❌ Error: Another daemon instance (PID {}) is already running.", pid);
                std::process::exit(1);
            }
        }
    }
    let _ = std::fs::write(pid_path, std::process::id().to_string());
    
    // 1. Load Configuration
    let config = Arc::new(Mutex::new(DaemonConfig::load()));

// 2. Initialize Engine & Security
    println!("🤖 Initializing AI Engine...");
    let det_path = "/usr/share/linux-bonjour/models/det_10g.onnx";
    let active_model = config.lock().await.active_model.clone();
    
    let rec_path = if active_model == "buffalo_l" {
        "/usr/share/linux-bonjour/models/arcface_w600k.onnx".to_string()
    } else {
        format!("/usr/share/linux-bonjour/models/{}/arcface_w600k.onnx", active_model)
    };
    
    let engine_res = InferenceEngine::new(det_path, &rec_path);
    let initial_engine = match engine_res {
        Ok(e) => Arc::new(Mutex::new(e)),
        Err(e) => {
            eprintln!("⚠️ AI Models not found: {}. Fallback to buffalo_l.", e);
            let fb_path = "/usr/share/linux-bonjour/models/arcface_w600k.onnx";
            match InferenceEngine::new(det_path, fb_path) {
                Ok(e) => Arc::new(Mutex::new(e)),
                Err(_) => {
                    return Err(anyhow::anyhow!("Critical AI models missing. Please ensure /usr/share/linux-bonjour/models exists."));
                }
            }
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

    let initial_store = Arc::new(SignatureStore::new(&active_model, provider.clone())?);
    
    // 2.5 Encapsulate Context
    pub struct BiometricContext {
        pub engine: Arc<Mutex<InferenceEngine>>,
        pub store: Arc<SignatureStore>,
        pub model_name: String,
    }

    let context = Arc::new(Mutex::new(BiometricContext {
        engine: initial_engine,
        store: initial_store,
        model_name: active_model,
    }));

    let system_enabled = Arc::new(AtomicBool::new(true));
    
    let initial_engine = {
        let ctx = context.lock().await;
        Arc::clone(&ctx.engine)
    };
    let initial_engine_locked = initial_engine.lock().await;
    let acceleration = if initial_engine_locked.has_gpu() { "Active (GPU Accelerator)" } else { "Active (CPU/OpenVINO)" }.to_string();
    drop(initial_engine_locked);

    println!("✅ AI Models and Secure Storage ready.");

    // 3. Start UDS Server
    let server = UdsServer::new("/run/linux-bonjour/daemon.sock");
    
    let context_cloned = Arc::clone(&context);
    let provider_cloned = Arc::clone(&provider);
    let enabled_cloned = Arc::clone(&system_enabled);
    let config_cloned = Arc::clone(&config);
    let accel_cloned = acceleration.clone();
    let tpm_state_cloned = Arc::clone(&tpm_active_clone);
    let cancel_signal = Arc::new(AtomicBool::new(false));
    let cancel_signal_cloned = Arc::clone(&cancel_signal);

    server.start(move |req, tx| {
        let context = Arc::clone(&context_cloned);
        let provider = Arc::clone(&provider_cloned);
        let enabled = Arc::clone(&enabled_cloned);
        let config = Arc::clone(&config_cloned);
        let accel_locked = accel_cloned.clone();
        let tpm_state = Arc::clone(&tpm_state_cloned);
        let cancel_signal = Arc::clone(&cancel_signal_cloned);
        
        async move {
            match req {
                DaemonRequest::STOP => {
                    cancel_signal.store(true, Ordering::SeqCst);
                    println!("🛑 Global stop signal received");
                    let _ = tx.send(DaemonResponse::ActionSuccess { msg: "Stop signal received".to_string() }).await;
                },
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
                    let ctx = context.lock().await;
                    match ctx.store.list_identities() {
                        Ok(users) => { let _ = tx.send(DaemonResponse::IdentityList { users }).await; },
                        Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                    }
                },
                DaemonRequest::DeleteIdentity { user } => {
                    let ctx = context.lock().await;
                    match ctx.store.delete_identity(&user) {
                        Ok(_) => { let _ = tx.send(DaemonResponse::ActionSuccess { msg: format!("Identity '{}' deleted", user) }).await; },
                        Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                    }
                },
                DaemonRequest::RenameIdentity { old_name, new_name } => {
                    let ctx = context.lock().await;
                    match ctx.store.rename_identity(&old_name, &new_name) {
                        Ok(_) => { let _ = tx.send(DaemonResponse::ActionSuccess { msg: format!("Identity '{}' renamed to '{}'", old_name, new_name) }).await; },
                        Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                    }
                },
                DaemonRequest::UpdateConfig { 
                    threshold, 
                    smile_required, 
                    autocapture, 
                    liveness_enabled, 
                    liveness_threshold, 
                    ask_permission, 
                    retry_limit: limit, 
                    camera_path: cam,
                    active_model,
                    enable_login,
                    enable_sudo,
                    enable_polkit
                } => {
                    let mut cfg = config.lock().await;
                    cfg.threshold = threshold;
                    cfg.smile_required = smile_required;
                    cfg.autocapture = autocapture;
                    cfg.liveness_enabled = liveness_enabled;
                    cfg.liveness_threshold = liveness_threshold;
                    cfg.ask_permission = ask_permission;
                    cfg.retry_limit = limit;
                    cfg.camera_path = cam;
                    
                    if let Some(new_model) = active_model {
                        if new_model != cfg.active_model {
                            println!("🔄 Switching AI Model to: {}", new_model);
                            let det_path = "/usr/share/linux-bonjour/models/det_10g.onnx";
                            let rec_path = if new_model == "buffalo_l" {
                                "/usr/share/linux-bonjour/models/arcface_w600k.onnx".to_string()
                            } else {
                                format!("/usr/share/linux-bonjour/models/{}/arcface_w600k.onnx", new_model)
                            };

                            if std::path::Path::new(&rec_path).exists() {
                                if let Ok(new_engine) = InferenceEngine::new(det_path, &rec_path) {
                                    if let Ok(new_store) = SignatureStore::new(&new_model, provider.clone()) {
                                        let mut ctx = context.lock().await;
                                        ctx.engine = Arc::new(Mutex::new(new_engine));
                                        ctx.store = Arc::new(new_store);
                                        ctx.model_name = new_model.clone();
                                        cfg.active_model = new_model;
                                        println!("✅ Biometric Context hot-swapped successfully (Model + Signatures).");
                                    }
                                } else {
                                    eprintln!("❌ Failed to initialize new model engine.");
                                }
                            } else {
                                println!("⚠️ Model files not found at {}. Download required.", rec_path);
                            }
                        }
                    }

                    cfg.enable_login = enable_login;
                    cfg.enable_sudo = enable_sudo;
                    cfg.enable_polkit = enable_polkit;
                    
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
                    
                    let active_model = config.lock().await.active_model.clone();
                    let _ = tx.send(DaemonResponse::HardwareStatus {
                        tpm: tpm_string,
                        acceleration: accel_locked,
                        camera: camera_type,
                        active_model,
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
                    let tx_cloned = tx.clone();
                    let context_cloned = Arc::clone(&context);
                    let provider_cloned = Arc::clone(&provider);
                    let config_cloned = Arc::clone(&config);
                    
                    tokio::spawn(async move {
                        let target_path = format!("/usr/share/linux-bonjour/models/{}", name_cloned);
                        let _ = std::fs::create_dir_all(&target_path);
                        
                        let _ = tx_cloned.send(DaemonResponse::Info { msg: format!("Downloading {}...", name_cloned) }).await;

                        let status = std::process::Command::new("curl")
                            .arg("-L")
                            .arg("-s") // Silent mode
                            .arg(model_url)
                            .arg("-o")
                            .arg(format!("{}/weights.zip", target_path))
                            .status();

                        if let Ok(s) = status {
                            if s.success() {
                                let _ = tx_cloned.send(DaemonResponse::Info { msg: format!("Extracting {}...", name_cloned) }).await;
                                let unzip_status = std::process::Command::new("unzip")
                                    .arg("-j")
                                    .arg("-o")
                                    .arg("-q")
                                    .arg(format!("{}/weights.zip", target_path))
                                    .arg("-x")
                                    .arg("*.txt")
                                    .arg("-d")
                                    .arg(&target_path)
                                    .status();

                                if let Ok(us) = unzip_status {
                                    if us.success() {
                                        let _ = std::fs::remove_file(format!("{}/weights.zip", target_path));
                                        // Some models use w600k_r50.onnx, others use different names. 
                                        // Buffalo S uses 'w600k_mbf.onnx' or similar. 
                                        // Antelope uses 'antelopev2.onnx'
                                        // We will look for *.onnx and rename to arcface_w600k.onnx if it exists
                                        
                                        let onnx_files = std::fs::read_dir(&target_path).unwrap().filter_map(|e| e.ok()).filter(|e| e.path().extension().map_or(false, |ex| ex == "onnx")).collect::<Vec<_>>();
                                        for entry in onnx_files {
                                            let fname = entry.file_name().to_string_lossy().to_string();
                                            if fname != "det_10g.onnx" && (fname.contains("w600k") || fname.contains("antelope") || fname.contains(".onnx")) {
                                                 let _ = std::fs::rename(entry.path(), format!("{}/arcface_w600k.onnx", target_path));
                                                 break;
                                            }
                                        }

                                        let _ = tx_cloned.send(DaemonResponse::ActionSuccess { msg: format!("Model {} ready", name_cloned) }).await;
                                        
                                        // SWAP CONTEXT ATOMICALLY
                                        let rec_path = format!("{}/arcface_w600k.onnx", target_path);
                                        if let Ok(new_engine) = InferenceEngine::new("/usr/share/linux-bonjour/models/det_10g.onnx", &rec_path) {
                                            if let Ok(new_store) = SignatureStore::new(&name_cloned, provider_cloned.clone()) {
                                                let mut ctx = context_cloned.lock().await;
                                                ctx.engine = Arc::new(Mutex::new(new_engine));
                                                ctx.store = Arc::new(new_store);
                                                ctx.model_name = name_cloned.clone();
                                                
                                                let mut cfg = config_cloned.lock().await;
                                                cfg.active_model = name_cloned.clone();
                                                let _ = cfg.save();
                                                println!("✅ Biometric Context swapped to new model: {}", name_cloned);
                                            }
                                        } else {
                                            eprintln!("❌ Failed to initialize newly downloaded model: {}", rec_path);
                                        }

                                        // Final absolute cleanup: remove anything not .onnx
                                        if let Ok(entries) = std::fs::read_dir(&target_path) {
                                            for entry in entries.flatten() {
                                                let path = entry.path();
                                                if path.is_file() {
                                                    if let Some(ext) = path.extension() {
                                                        let ext_str = ext.to_string_lossy().to_lowercase();
                                                        if ext_str != "onnx" && ext_str != "engine" {
                                                            let _ = std::fs::remove_file(&path);
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        return;
                                    }
                                }
                            }
                        }
                        let _ = tx_cloned.send(DaemonResponse::Failure { reason: format!("Failed to download model {}", name_cloned) }).await;
                    });
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
                    let has_face_data = !context.lock().await.store.list_identities().unwrap_or_default().is_empty();

                    let _ = tx.send(DaemonResponse::Config {
                        threshold: cfg.threshold,
                        smile_required: cfg.smile_required,
                        autocapture: cfg.autocapture,
                        liveness_enabled: cfg.liveness_enabled,
                        liveness_threshold: cfg.liveness_threshold,
                        ask_permission: cfg.ask_permission,
                        retry_limit: cfg.retry_limit,
                        camera_path: cfg.camera_path.clone(),
                        active_model: cfg.active_model.clone(),
                        enabled: enabled.load(Ordering::SeqCst),
                        has_face_data,
                        enable_login: cfg.enable_login,
                        enable_sudo: cfg.enable_sudo,
                        enable_polkit: cfg.enable_polkit,
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
                    
                    let (engine, store) = {
                        let ctx = context.lock().await;
                        (Arc::clone(&ctx.engine), Arc::clone(&ctx.store))
                    };

                    let camera_path_override = cfg.camera_path.clone();
                    let threshold = cfg.threshold;
                    let liveness_threshold = cfg.liveness_threshold;
                    let smile_required = cfg.smile_required;

                    // Search Loop: Try to recognize for up to 3 seconds
                    let start_time = std::time::Instant::now();
                    let timeout = std::time::Duration::from_secs(3);
                    let mut last_error = "No face detected".to_string();

                    let mut iteration = 0;
                    while start_time.elapsed() < timeout {
                        iteration += 1;
                        // Send real-time scanning feedback less frequently
                        if iteration % 5 == 1 {
                            let _ = tx.send(DaemonResponse::Scanning { 
                                msg: "Scanning...".to_string() 
                            }).await;
                        }

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
                                            // 1. Try 1:1 match with requested user
                                            let mut matched_user = None;
                                            if let Ok(saved_embedding) = store.load_signature(&user) {
                                                let score = SignatureStore::cosine_similarity(&embedding, &saved_embedding);
                                                if score > threshold {
                                                    matched_user = Some((user.clone(), score));
                                                }
                                            }

                                            // 2. Fallback to 1:N Identification if requested user didn't match
                                            if matched_user.is_none() {
                                                if let Ok(Some((identified_user, score))) = store.identify_user(&embedding, threshold) {
                                                    println!("🔍 [Bonjour] Identified as: {} (score: {:.2})", identified_user, score);
                                                    matched_user = Some((identified_user, score));
                                                }
                                            }

                                            if let Some((final_user, score)) = matched_user {
                                                let liveness_score = detections[0].liveness_score;
                                                if !smile_required || liveness_score > liveness_threshold {
                                                    println!("✅ [Bonjour] Success: {} (score: {:.2})", final_user, score);
                                                    let _ = tx.send(DaemonResponse::Success { user: final_user }).await;
                                                    return;
                                                } else {
                                                    last_error = format!("Liveness failed ({:.2})", liveness_score);
                                                }
                                            } else {
                                                last_error = "No matching identity found".to_string();
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
                    let (engine, store) = {
                        let ctx = context.lock().await;
                        (Arc::clone(&ctx.engine), Arc::clone(&ctx.store))
                    };

                    let camera_path_override = {
                        let cfg = config.lock().await;
                        cfg.camera_path.clone()
                    };
                    
                    let mut collected_embeddings: Vec<Vec<f32>> = Vec::new();
                    let target_scans = 5;
                    
                    println!("🚀 Starting interactive enrollment for user: {}", user);
                    cancel_signal.store(false, Ordering::SeqCst);

                    let mut last_processed_time = std::time::Instant::now();
                    
                    // Main scanning loop
                    for _attempt in 0..100 { // Max attempts to prevent infinite loop
                        if cancel_signal.load(Ordering::SeqCst) {
                            println!("🛑 Enrollment cancelled via signal");
                            return;
                        }
                        if collected_embeddings.len() >= target_scans { break; }

                        let capture_result: Result<DynamicImage> = (|| {
                            let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux)?;
                            if devices.is_empty() { anyhow::bail!("No camera found"); }
                            
                            let mut sorted_devices = devices.clone();
                            sorted_devices.sort_by_key(|d| {
                                if let Some(ref path) = camera_path_override {
                                    if d.human_name() == *path || d.index().to_string() == *path { return 0; }
                                }
                                let name = d.human_name().to_lowercase();
                                if name.contains("ir") || name.contains("infrared") { 1 } else { 2 }
                            });

                            for dev in sorted_devices {
                                let format = RequestedFormat::new::<RgbFormat>(RequestedFormatType::AbsoluteHighestResolution);
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
                            Err(anyhow::anyhow!("Capture failed"))
                        })();

                        if let Ok(dyn_img) = capture_result {
                            // 1. Encode frame for GUI
                            let mut buf = Vec::new();
                            let mut cursor = Cursor::new(&mut buf);
                            // Resize for faster transfer if needed, but let's try raw first or modestly resized
                            let small_img = dyn_img.thumbnail(320, 240);
                            if let Ok(_) = small_img.write_to(&mut cursor, image::ImageFormat::Jpeg) {
                                let b64 = general_purpose::STANDARD.encode(&buf);
                                let progress = collected_embeddings.len() as f32 / target_scans as f32;
                                let msg = if collected_embeddings.is_empty() {
                                    "Align your face to the center...".to_string()
                                } else {
                                    format!("Capturing... ({} of {})", collected_embeddings.len() + 1, target_scans)
                                };

                                if let Err(_) = tx.send(DaemonResponse::EnrollmentFrame { 
                                    base64_image: b64, 
                                    message: msg,
                                    progress
                                }).await {
                                    println!("🔌 Enrollment interrupted (Client disconnected)");
                                    return;
                                }
                            }

                            // 2. Process face
                            if last_processed_time.elapsed() > std::time::Duration::from_millis(500) {
                                let mut engine_lock = engine.lock().await;
                                if let Ok(detections) = engine_lock.detect_faces(&dyn_img) {
                                    if !detections.is_empty() {
                                        let aligned = engine_lock.align_face(&dyn_img, &detections[0].landmarks);
                                        if let Ok(embedding) = engine_lock.get_face_embedding(&aligned) {
                                            collected_embeddings.push(embedding);
                                            println!("📍 Collected scan {}/{}", collected_embeddings.len(), target_scans);
                                        }
                                    }
                                }
                                last_processed_time = std::time::Instant::now();
                            }
                        }
                        tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
                    }

                    if collected_embeddings.len() >= target_scans {
                        // AVERAGE EMBEDDINGS
                        let dim = collected_embeddings[0].len();
                        let mut avg_embedding = vec![0.0f32; dim];
                        for emb in &collected_embeddings {
                            for i in 0..dim {
                                avg_embedding[i] += emb[i];
                            }
                        }
                        for i in 0..dim {
                            avg_embedding[i] /= collected_embeddings.len() as f32;
                        }

                        // Save the averaged signature
                        match store.save_signature(&user, &avg_embedding) {
                            Ok(_) => { 
                                println!("✅ Averaged enrollment success for user: {}", user);
                                let _ = tx.send(DaemonResponse::Success { user: user.clone() }).await; 
                            },
                            Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                        }
                    } else {
                        let _ = tx.send(DaemonResponse::Failure { reason: "Enrollment timed out or incomplete".to_string() }).await;
                    }
                },
            }
        }
    }).await?;

    Ok(())
}
