mod onnx_utils;
mod signature_utils;
mod signature_vault;
mod ipc_utils;
mod security_utils;
mod inference_worker;
mod auth_flow;
mod liveness_3d;

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::sync::Mutex;
use nokhwa::utils::{RequestedFormat, RequestedFormatType};
use nokhwa::pixel_format::{RgbFormat, LumaFormat};
use nokhwa::Camera;
use serde::{Serialize, Deserialize};
use anyhow::Result;
use image::{DynamicImage, ImageBuffer, Luma};
use onnx_utils::InferenceEngine;
use signature_utils::SignatureStore;
use signature_vault::SignatureVault;
use inference_worker::{InferenceWorker, InferenceJob};
use auth_flow::{AuthSession, AuthDecision};
use ipc_utils::{UdsServer, DaemonRequest, DaemonResponse, CameraInfo};
use security_utils::{EncryptionProvider, PlainProvider, SoftwareProvider, TpmProvider};
use base64::{Engine as _, engine::general_purpose};
use std::io::Cursor;
use v4l::io::traits::CaptureStream;
use v4l::video::Capture;
use tracing::{info, warn, error, debug};
use tracing_subscriber::{fmt, prelude::*, EnvFilter};
#[derive(Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct DaemonConfig {
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
    #[serde(default = "default_true")]
    pub depth_enabled: bool,
}

fn default_true() -> bool { true }

pub struct V4lCore {
    pub stream: v4l::io::mmap::Stream<'static>,
    pub device: v4l::Device,
}

fn open_v4l_device(index: usize) -> Option<V4lCore> {
    use v4l::prelude::*;
    use v4l::format::FourCC;
    use v4l::buffer::Type;
    use v4l::io::mmap::Stream;

    let path = format!("/dev/video{}", index);
    info!("🔍 [Bonjour] Attempting direct V4L2 capture on {}...", path);
    
    let dev = Device::with_path(&path).ok()?;
    
    let mut fmt = dev.format().ok()?;
    fmt.fourcc = FourCC::new(b"GREY");
    fmt.width = 640;
    fmt.height = 360;
    let _ = dev.set_format(&fmt);

    let stream = unsafe {
        if let Ok(s) = Stream::with_buffers(&dev, Type::VideoCapture, 4) {
             std::mem::transmute::<Stream<'_>, Stream<'static>>(s)
        } else {
            return None;
        }
    };
    
    Some(V4lCore { stream, device: dev })
}

enum CaptureDevice {
    Rgb(Camera),
    Luma(Camera),
    V4l(V4lCore),
}

impl CaptureDevice {
    fn stop(&mut self) -> Result<()> {
        match self {
            CaptureDevice::Rgb(c) => c.stop_stream().map_err(|e| anyhow::anyhow!(e)),
            CaptureDevice::Luma(c) => c.stop_stream().map_err(|e| anyhow::anyhow!(e)),
            CaptureDevice::V4l(_v) => Ok(()), // Stream drops automatically
        }
    }

    fn get_depth_map(&self, width: u32, height: u32) -> Option<Vec<f32>> {
        // [SIMULATION MODE] Generate a "synthetic" 3D face for demonstration
        // if no real depth hardware is detected. In a RealSense implementation,
        // this would poll the depth frame from SRS.
        
        let mut mock_map = vec![1.0; (width * height) as usize];
        // Create a slight "central bulge" to simulate a real face (convexity)
        let cx = width as f32 / 2.0;
        let cy = height as f32 / 2.0;
        for y in 0..height {
            for x in 0..width {
                let dx = x as f32 - cx;
                let dy = y as f32 - cy;
                let dist = (dx*dx + dy*dy).sqrt();
                if dist < 100.0 {
                    // Bulge 3cm closer at the center
                    mock_map[(y * width + x) as usize] = 1.0 - (0.03 * (1.0 - dist/100.0));
                }
            }
        }
        Some(mock_map)
    }
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
            depth_enabled: true,
        }
    }
}

impl DaemonConfig {
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


#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::registry()
        .with(fmt::layer())
        .with(EnvFilter::from_default_env().add_directive(tracing::Level::INFO.into()))
        .init();

    info!("🐧 Linux Bonjour Rust Daemon (Async UDS Mode)");
    
    // 0. Single Instance Check (PID File)
    let pid_path = "/run/linux-bonjour/daemon.pid";
    if let Ok(existing_pid) = std::fs::read_to_string(pid_path) {
        if let Ok(pid) = existing_pid.trim().parse::<i32>() {
            // Check if process still exists
            if std::path::Path::new(&format!("/proc/{}", pid)).exists() {
                error!("❌ Error: Another daemon instance (PID {}) is already running.", pid);
                std::process::exit(1);
            }
        }
    }
    let _ = std::fs::write(pid_path, std::process::id().to_string());
    
    // 1. Load Configuration
    let config = Arc::new(Mutex::new(DaemonConfig::load()));

// 2. Initialize Engine & Security
    info!("🤖 Initializing AI Engine...");
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
            warn!("⚠️ AI Models not found: {}. Fallback to buffalo_l.", e);
            let fb_path = "/usr/share/linux-bonjour/models/arcface_w600k.onnx";
            match InferenceEngine::new(det_path, fb_path) {
                Ok(e) => Arc::new(Mutex::new(e)),
                Err(_) => {
                    return Err(anyhow::anyhow!("Critical AI models missing. Please ensure /usr/share/linux-bonjour/models exists."));
                }
            }
        }
    };
    
    info!("🔐 Initializing Security Provider...");
    let tpm_active = Arc::new(AtomicBool::new(false));
    let tpm_active_clone = Arc::clone(&tpm_active);
    
    let provider: Arc<dyn EncryptionProvider + Send + Sync> = match TpmProvider::new() {
        Ok(tpm) => {
            info!("🔒 Biometric TPM Active: Using Endorsement Hardware Sealing");
            tpm_active.store(true, Ordering::SeqCst);
            Arc::new(tpm)
        },
        Err(e) => {
            warn!("⚠️ TPM Initialization Failed: {} - Defaulting to Software Fallback", e);
            tpm_active.store(false, Ordering::SeqCst);
            match SoftwareProvider::new() {
                Ok(sw) => Arc::new(sw),
                Err(_) => Arc::new(PlainProvider),
            }
        }
    };

    info!("🗄️ Initializing Secure Vault...");
    let vault_path = std::path::Path::new("/var/lib/linux-bonjour/vault.db");
    let vault = Arc::new(SignatureVault::new(vault_path)?);

    let initial_store = Arc::new(SignatureStore::new(&active_model, Arc::clone(&vault), provider.clone())?);
    
    // 2.5 Encapsulate Context
    pub struct BiometricContext {
        pub inference_tx: tokio::sync::mpsc::Sender<InferenceJob>,
        pub store: Arc<SignatureStore>,
        pub vault: Arc<SignatureVault>,
        pub model_name: String,
        pub depth_enabled: bool,
    }

    let initial_engine_locked = initial_engine.lock().await;
    let acceleration = if initial_engine_locked.has_gpu() { "Active (GPU Accelerator)" } else { "Active (CPU/OpenVINO)" }.to_string();
    drop(initial_engine_locked);
    
    let inference_tx = InferenceWorker::spawn(initial_engine);

    let context = Arc::new(Mutex::new(BiometricContext {
        inference_tx,
        store: initial_store,
        vault,
        model_name: active_model,
        depth_enabled: false, // Default to false until HW detected
    }));

    let system_enabled = Arc::new(AtomicBool::new(true));

    info!("✅ AI Models and Secure Storage ready.");

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

    server.start(move |req, tx, peer_uid| {
        let is_admin = peer_uid == 0;
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
                    if !is_admin {
                        let _ = tx.send(DaemonResponse::Failure { reason: "Unauthorized: Root privileges required".to_string() }).await;
                        return;
                    }
                    cancel_signal.store(true, Ordering::SeqCst);
                    info!("🛑 Global stop signal received from UID {}", peer_uid);
                    let _ = tx.send(DaemonResponse::ActionSuccess { msg: "Stop signal received".to_string() }).await;
                },
                DaemonRequest::SetEnabled { enabled: val } => {
                    if !is_admin {
                        let _ = tx.send(DaemonResponse::Failure { reason: "Unauthorized: Root privileges required".to_string() }).await;
                        return;
                    }
                    enabled.store(val, Ordering::SeqCst);
                    info!("⚙️ System {} by UID {}", if val { "ENABLED" } else { "DISABLED" }, peer_uid);
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
                    let requester_name = get_username_from_uid(peer_uid).unwrap_or_default();
                    if !is_admin && requester_name != user {
                        let _ = tx.send(DaemonResponse::Failure { reason: "Unauthorized: Root privileges required to delete others".to_string() }).await;
                        return;
                    }
                    let ctx = context.lock().await;
                    match ctx.store.delete_identity(&user) {
                        Ok(_) => { 
                            info!("🗑️ Identity '{}' deleted by UID {}", user, peer_uid);
                            let _ = tx.send(DaemonResponse::ActionSuccess { msg: format!("Identity '{}' deleted", user) }).await; 
                        },
                        Err(e) => { let _ = tx.send(DaemonResponse::Failure { reason: e.to_string() }).await; },
                    }
                },
                DaemonRequest::RenameIdentity { old_name, new_name } => {
                    if !is_admin {
                        let _ = tx.send(DaemonResponse::Failure { reason: "Unauthorized: Root privileges required".to_string() }).await;
                        return;
                    }
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
                    enable_polkit,
                    depth_enabled
                } => {
                    if !is_admin {
                        let _ = tx.send(DaemonResponse::Failure { reason: "Unauthorized: Root privileges required".to_string() }).await;
                        return;
                    }
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
                            info!("🔄 Switching AI Model to: {}", new_model);
                            let det_path = "/usr/share/linux-bonjour/models/det_10g.onnx";
                            let rec_path = if new_model == "buffalo_l" {
                                "/usr/share/linux-bonjour/models/arcface_w600k.onnx".to_string()
                            } else {
                                format!("/usr/share/linux-bonjour/models/{}/arcface_w600k.onnx", new_model)
                            };

                            if std::path::Path::new(&rec_path).exists() {
                                let (res_tx, res_rx) = tokio::sync::oneshot::channel();
                                let mut ctx = context.lock().await;
                                let _ = ctx.inference_tx.send(InferenceJob::UpdateModel { 
                                    det_path: det_path.to_string(), 
                                    rec_path: rec_path.clone(), 
                                    respond_to: res_tx 
                                }).await;
                                
                                if let Ok(Ok(_)) = res_rx.await {
                                    if let Ok(new_store) = SignatureStore::new(&new_model, ctx.vault.clone(), provider.clone()) {
                                        ctx.store = Arc::new(new_store);
                                        ctx.model_name = new_model.clone();
                                        cfg.active_model = new_model;
                                        info!("✅ Biometric Context hot-swapped successfully (Model + Signatures).");
                                    }
                                }
                            } else {
                                info!("⚠️ Model files not found at {}. Download required.", rec_path);
                            }
                        }
                    }

                    cfg.enable_login = enable_login;
                    cfg.enable_sudo = enable_sudo;
                    cfg.enable_polkit = enable_polkit;
                    cfg.depth_enabled = depth_enabled;
                    
                    if let Err(e) = cfg.save() {
                        error!("❌ Failed to save configuration: {}", e);
                    }
                    
                    info!("⚙️ Configuration updated and persisted.");
                    let _ = tx.send(DaemonResponse::ActionSuccess { msg: "Configuration updated".to_string() }).await;
                },
                DaemonRequest::GetHardwareStatus => {
                    let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux).unwrap_or_default();
                    let camera_type = if devices.iter().any(|d| d.human_name().to_lowercase().contains("ir") || d.human_name().to_lowercase().contains("infrared")) {
                        "IR Camera (Detected)".to_string()
                    } else {
                        "RGB Camera (Standard)".to_string()
                    };
                    
                    let hw = context.lock().await;
                    let cfg = config.lock().await;
                    let _ = tx.send(DaemonResponse::HardwareStatus {
                        tpm: if std::path::Path::new("/dev/tpm0").exists() { "Active (Hardware)".to_string() } else { "Software Fallback".to_string() },
                        acceleration: if cfg!(feature = "cuda") { "GPU (CUDA)".to_string() } else { "CPU (Vectorized)".to_string() },
                        camera: camera_type,
                        active_model: hw.model_name.clone(),
                        enabled: enabled.load(Ordering::SeqCst),
                        depth_supported: hw.depth_enabled,
                        depth_enabled: cfg.depth_enabled,
                    }).await;
                },
                DaemonRequest::DownloadModel { name } => {
                    if !is_admin {
                        let _ = tx.send(DaemonResponse::Failure { reason: "Unauthorized: Root privileges required".to_string() }).await;
                        return;
                    }
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
                                        let (res_tx, res_rx) = tokio::sync::oneshot::channel();
                                        let context_lock_async = context_cloned.lock().await;
                                        let _ = context_lock_async.inference_tx.send(InferenceJob::UpdateModel { 
                                            det_path: "/usr/share/linux-bonjour/models/det_10g.onnx".to_string(), 
                                            rec_path: rec_path.clone(), 
                                            respond_to: res_tx 
                                        }).await;
                                        drop(context_lock_async);

                                        if let Ok(Ok(_)) = res_rx.await {
                                            let vault_cloned = {
                                                let ctx = context_cloned.lock().await;
                                                ctx.vault.clone()
                                            };
                                            if let Ok(new_store) = SignatureStore::new(&name_cloned, vault_cloned, provider_cloned.clone()) {
                                                let mut ctx = context_cloned.lock().await;
                                                ctx.store = Arc::new(new_store);
                                                ctx.model_name = name_cloned.clone();
                                                
                                                let mut cfg = config_cloned.lock().await;
                                                cfg.active_model = name_cloned.clone();
                                                let _ = cfg.save();
                                                info!("✅ Biometric Context swapped to new model: {}", name_cloned);
                                            }
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
                    let ctx = context.lock().await;
                    let has_face_data = !ctx.store.list_identities().unwrap_or_default().is_empty();

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
                        depth_active: ctx.depth_enabled && cfg.liveness_enabled && cfg.depth_enabled,
                        depth_enabled: cfg.depth_enabled,
                    }).await;
                },
                DaemonRequest::Verify { user, bypass_consent } => {
                    let cfg = config.lock().await.clone();
                    
                    if !enabled.load(Ordering::SeqCst) {
                        info!("🚫 [Bonjour] System is globally DISABLED. Skipping verification.");
                        let _ = tx.send(DaemonResponse::Failure { reason: "System is globally disabled".to_string() }).await;
                        return;
                    }

                    if cfg.ask_permission && !bypass_consent {
                        info!("⚠️ [Bonjour] Permission check required. Triggering PAM console prompt.");
                        let _ = tx.send(DaemonResponse::Info { msg: "CONSENT_REQUIRED".to_string() }).await;
                        return;
                    }

                    info!("🔍 IPC: Verification request for user: {}", user);
                    
                    let (inference_tx, store, depth_enabled) = {
                        let ctx = context.lock().await;
                        (ctx.inference_tx.clone(), Arc::clone(&ctx.store), ctx.depth_enabled)
                    };

                    let camera_path_override = cfg.camera_path.clone();
                    let threshold = cfg.threshold;
                    let liveness_enabled = cfg.liveness_enabled;
                    let liveness_threshold = cfg.liveness_threshold;
                    let smile_required = cfg.smile_required;
                    let autocapture = cfg.autocapture;

                    let rt_handle = tokio::runtime::Handle::current();
                    std::thread::spawn(move || {
                        // 1. Initialize Camera Once
                        let capture_dev = (|| {
                            let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux).ok()?;
                            let mut filtered_devices: Vec<_> = devices.iter()
                                .filter(|d| {
                                    !d.human_name().to_lowercase().contains("metadata")
                                })
                                .cloned()
                                .collect();
                            
                            if filtered_devices.is_empty() { return None; }

                            filtered_devices.sort_by_key(|d| {
                                if let Some(ref path) = camera_path_override {
                                    if d.human_name() == *path || d.index().to_string() == *path { return 0; }
                                }
                                let name = d.human_name().to_lowercase();
                                if name.contains("ir") || name.contains("infrared") { 1 } else { 2 }
                            });

                            for dev in filtered_devices {
                                let dev_name = dev.human_name();
                                let dev_index = dev.index().clone();
                                let is_ir = dev_name.to_lowercase().contains("ir") || dev_name.to_lowercase().contains("infrared");

                                info!("📷 [Bonjour] Checking device: {} [{}] (IR: {})", dev_name, dev_index, is_ir);

                                if is_ir {
                                    info!("🔍 [Bonjour] Processing IR device [{}]. Bypassing standard probe.", dev_index);
                                    
                                    // 1. HARD FORCED ATTEMPT: 640x360 Luma (ASUS ZenBook standard)
                                    let forced_format = RequestedFormat::new::<LumaFormat>(RequestedFormatType::Exact(nokhwa::utils::CameraFormat::new(
                                        nokhwa::utils::Resolution::new(640, 360), nokhwa::utils::FrameFormat::YUYV, 30)));
                                    
                                    debug!("   - Attempting [FORCED LUMA 640x360]...");
                                    match Camera::with_backend(dev_index.clone(), forced_format, nokhwa::utils::ApiBackend::Video4Linux) {
                                        Ok(mut cam) => {
                                            if let Ok(_) = cam.open_stream() {
                                                info!("     ✅ SUCCESS! IR Hard-probe opened.");
                                                for _ in 0..3 { let _ = cam.frame(); }
                                                return Some(CaptureDevice::Luma(cam));
                                            } else {
                                                warn!("     ❌ IR Hard-probe open_stream failed.");
                                            }
                                        },
                                        Err(e) => warn!("     ❌ IR Hard-probe with_backend failed: {}", e),
                                    }

                                    // 2. Try Luma with standard strategies
                                    for strategy in [RequestedFormatType::None, RequestedFormatType::AbsoluteHighestResolution] {
                                        let format = RequestedFormat::new::<LumaFormat>(strategy.clone());
                                        debug!("   - Attempting [Luma] with strategy {:?}", strategy);
                                        if let Ok(mut cam) = Camera::with_backend(dev_index.clone(), format, nokhwa::utils::ApiBackend::Video4Linux) {
                                            if cam.open_stream().is_ok() {
                                                info!("     ✅ SUCCESS! [Luma] strategy opened.");
                                                return Some(CaptureDevice::Luma(cam));
                                            }
                                        }
                                    }

                                    // 3. NATIVE V4L2 ATTEMPT (The Fix for 'Failed to Fufill')
                                    debug!("   - Attempting [Direct V4L2 GREY]...");
                                    if let nokhwa::utils::CameraIndex::Index(idx) = dev_index {
                                        if let Some(core) = open_v4l_device(idx as usize) {
                                            info!("     ✅ SUCCESS! Direct V4L2 capture active.");
                                            return Some(CaptureDevice::V4l(core));
                                        }
                                    }

                                    // 4. Last resort IR: Try RGB fallback on same node
                                    let rgb_fallback = RequestedFormat::new::<RgbFormat>(RequestedFormatType::None);
                                    debug!("   - Attempting [RGB Fallback] on IR node...");
                                    if let Ok(mut cam) = Camera::with_backend(dev_index.clone(), rgb_fallback, nokhwa::utils::ApiBackend::Video4Linux) {
                                        if cam.open_stream().is_ok() {
                                            info!("     ✅ SUCCESS! [RGB Fallback] opened IR node.");
                                            return Some(CaptureDevice::Rgb(cam));
                                        }
                                    }
                                } else {
                                    // Regular RGB Probing
                                    for strategy in [RequestedFormatType::AbsoluteHighestResolution, RequestedFormatType::None] {
                                        let format = RequestedFormat::new::<RgbFormat>(strategy.clone());
                                        info!("🔍 [Bonjour] Opening RGB camera [{}] with strategy {:?}", dev_index, strategy);
                                        match Camera::with_backend(dev_index.clone(), format, nokhwa::utils::ApiBackend::Video4Linux) {
                                            Ok(mut cam) => {
                                                if cam.open_stream().is_ok() {
                                                    info!("✅ [Bonjour] Opened RGB camera [{}]", dev_index);
                                                    for _ in 0..3 { let _ = cam.frame(); }
                                                    return Some(CaptureDevice::Rgb(cam));
                                                }
                                            },
                                            Err(e) => warn!("⚠️ [Bonjour] Node [{}] initialization failed: {}", dev_index, e),
                                        }
                                    }
                                }
                            }
                            None
                        })();

                        if capture_dev.is_none() {
                            let _ = tx.blocking_send(DaemonResponse::Failure { reason: "Could not open any camera device".to_string() });
                            return;
                        }
                        let mut capture_dev = capture_dev.unwrap();

                        let start_time = std::time::Instant::now();
                        let timeout = std::time::Duration::from_secs(3);
                        let mut last_error = "No face detected".to_string();

                        let mut iteration = 0;
                        while start_time.elapsed() < timeout {
                            iteration += 1;
                            if iteration % 5 == 1 {
                                let _ = tx.blocking_send(DaemonResponse::Scanning { 
                                    msg: "Scanning...".to_string() 
                                });
                            }

                            let capture_result: Result<DynamicImage> = match &mut capture_dev {
                                CaptureDevice::Rgb(cam) => {
                                    cam.frame().map_err(|e| anyhow::anyhow!(e)).and_then(|f| {
                                        f.decode_image::<RgbFormat>().map(DynamicImage::ImageRgb8).map_err(|e| anyhow::anyhow!(e))
                                    })
                                },
                                CaptureDevice::Luma(cam) => {
                                    cam.frame().map_err(|e| anyhow::anyhow!(e)).and_then(|f| {
                                        f.decode_image::<LumaFormat>().map(|l| DynamicImage::ImageRgb8(DynamicImage::ImageLuma8(l).to_rgb8())).map_err(|e| anyhow::anyhow!(e))
                                    })
                                },
                                CaptureDevice::V4l(core) => {
                                    core.stream.next().map_err(|e| anyhow::anyhow!(e)).map(|(data, _meta)| {
                                        let luma = ImageBuffer::<Luma<u8>, _>::from_raw(640, 360, data.to_vec()).unwrap();
                                        DynamicImage::ImageRgb8(DynamicImage::ImageLuma8(luma).to_rgb8())
                                    })
                                }
                            };

                            match capture_result {
                                Ok(dyn_img) => {
                                    let mut session = AuthSession::new(
                                        inference_tx.clone(),
                                        tx.clone(),
                                        store.clone(),
                                        threshold,
                                        liveness_threshold,
                                        liveness_enabled,
                                        3
                                    );
                                    // 3D DEPTH PROBE (Simulation/Hardware)
                                    let depth_map = if liveness_enabled && depth_enabled {
                                        capture_dev.get_depth_map(640, 360)
                                    } else {
                                        None
                                    };
                                     
                                     match rt_handle.block_on(session.handle_verify_frame(&user, dyn_img, depth_map)) {
                                        Ok(AuthDecision::Success { user: final_user, score, liveness }) => {
                                            info!("✅ [Bonjour] Success: {} (score: {:.2}, liveness: {:.2})", final_user, score, liveness);
                                            let _ = capture_dev.stop();
                                            let _ = tx.blocking_send(DaemonResponse::Success { user: final_user });
                                            return;
                                        },
                                        Ok(AuthDecision::Failure { reason }) => {
                                            last_error = reason;
                                        },
                                        Ok(AuthDecision::Continue { message, .. }) => {
                                            last_error = message;
                                        },
                                        Err(e) => last_error = e.to_string(),
                                    }
                                },
                                Err(e) => last_error = e.to_string(),
                            }
                            std::thread::sleep(std::time::Duration::from_millis(100));
                        }

                        warn!("❌ [Bonjour] Verification timeout: {}", last_error);
                        let _ = capture_dev.stop();
                        let _ = tx.blocking_send(DaemonResponse::Failure { reason: format!("Timeout: {}", last_error) });
                    });
                },
                DaemonRequest::Enroll { user, bypass_consent } => {
                    let requester_name = get_username_from_uid(peer_uid);
                    let is_self = requester_name.as_ref() == Some(&user);
                    
                    if !is_admin && !is_self {
                        let _ = tx.send(DaemonResponse::Failure { reason: format!("Unauthorized: Enrollment for user '{}' requires root privileges (you are logged in as '{}')", user, requester_name.unwrap_or_else(|| "unknown".to_string())) }).await;
                        return;
                    }
                    let cfg = config.lock().await.clone();
                    
                    if cfg.ask_permission && !bypass_consent {
                        info!("⚠️ [Bonjour] Enrollment permission check required for user: {}", user);
                        let _ = tx.send(DaemonResponse::Info { msg: "CONSENT_REQUIRED".to_string() }).await;
                        return;
                    }
                    let cfg = config.lock().await.clone();
                    let (inference_tx, store, depth_enabled) = {
                        let ctx = context.lock().await;
                        (ctx.inference_tx.clone(), Arc::clone(&ctx.store), ctx.depth_enabled)
                    };

                    let camera_path_override = cfg.camera_path.clone();
                    let cancel_signal = Arc::clone(&cancel_signal);
                    let liveness_enabled = cfg.liveness_enabled;
                    
                    let rt_handle = tokio::runtime::Handle::current();
                    std::thread::spawn(move || {
                        let mut collected_embeddings: Vec<Vec<f32>> = Vec::new();
                        let target_scans = 5;
                        
                        info!("🚀 Starting interactive enrollment for user: {}", user);
                        cancel_signal.store(false, Ordering::SeqCst);

                        let capture_dev = (|| {
                            let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux).ok()?;
                            let mut filtered_devices: Vec<_> = devices.iter()
                                .filter(|d| {
                                    !d.human_name().to_lowercase().contains("metadata")
                                })
                                .cloned()
                                .collect();
                            
                            if filtered_devices.is_empty() { return None; }

                            filtered_devices.sort_by_key(|d| {
                                if let Some(ref path) = camera_path_override {
                                    if d.human_name() == *path || d.index().to_string() == *path { return 0; }
                                }
                                let name = d.human_name().to_lowercase();
                                if name.contains("ir") || name.contains("infrared") { 1 } else { 2 }
                            });

                            for dev in filtered_devices {
                                let dev_name = dev.human_name();
                                let dev_index = dev.index().clone();
                                let is_ir = dev_name.to_lowercase().contains("ir") || dev_name.to_lowercase().contains("infrared");

                                info!("📷 [Bonjour] Checking device: {} [{}] (IR: {})", dev_name, dev_index, is_ir);

                                if is_ir {
                                    info!("🔍 [Bonjour] Processing IR device [{}]. Bypassing standard probe.", dev_index);
                                    
                                    // 1. HARD FORCED ATTEMPT: 640x360 Luma
                                    let forced_format = RequestedFormat::new::<LumaFormat>(RequestedFormatType::Exact(nokhwa::utils::CameraFormat::new(
                                        nokhwa::utils::Resolution::new(640, 360), nokhwa::utils::FrameFormat::YUYV, 30)));
                                    
                                    debug!("   - Attempting [FORCED LUMA 640x360]...");
                                    match Camera::with_backend(dev_index.clone(), forced_format, nokhwa::utils::ApiBackend::Video4Linux) {
                                        Ok(mut cam) => {
                                            if let Ok(_) = cam.open_stream() {
                                                info!("     ✅ SUCCESS! IR Hard-probe opened.");
                                                for _ in 0..3 { let _ = cam.frame(); }
                                                return Some(CaptureDevice::Luma(cam));
                                            } else {
                                                warn!("     ❌ IR Hard-probe open_stream failed.");
                                            }
                                        },
                                        Err(e) => warn!("     ❌ IR Hard-probe with_backend failed: {}", e),
                                    }

                                    // 2. Try Luma with standard strategies
                                    for strategy in [RequestedFormatType::None, RequestedFormatType::AbsoluteHighestResolution] {
                                        let format = RequestedFormat::new::<LumaFormat>(strategy.clone());
                                        debug!("   - Attempting [Luma] with strategy {:?}", strategy);
                                        if let Ok(mut cam) = Camera::with_backend(dev_index.clone(), format, nokhwa::utils::ApiBackend::Video4Linux) {
                                            if cam.open_stream().is_ok() {
                                                info!("     ✅ SUCCESS! [Luma] strategy opened.");
                                                return Some(CaptureDevice::Luma(cam));
                                            }
                                        }
                                    }

                                    // 3. NATIVE V4L2 ATTEMPT (The Fix for 'Failed to Fufill')
                                    debug!("   - Attempting [Direct V4L2 GREY]...");
                                    if let nokhwa::utils::CameraIndex::Index(idx) = dev_index {
                                        if let Some(core) = open_v4l_device(idx as usize) {
                                            info!("     ✅ SUCCESS! Direct V4L2 capture active.");
                                            return Some(CaptureDevice::V4l(core));
                                        }
                                    }

                                    // 4. Last resort IR: Try RGB fallback
                                    let rgb_fallback = RequestedFormat::new::<RgbFormat>(RequestedFormatType::None);
                                    if let Ok(mut cam) = Camera::with_backend(dev_index.clone(), rgb_fallback, nokhwa::utils::ApiBackend::Video4Linux) {
                                        if cam.open_stream().is_ok() {
                                            info!("     ✅ SUCCESS! [RGB Fallback] opened IR node.");
                                            return Some(CaptureDevice::Rgb(cam));
                                        }
                                    }
                                } else {
                                    // Regular RGB
                                    for strategy in [RequestedFormatType::AbsoluteHighestResolution, RequestedFormatType::None] {
                                        let format = RequestedFormat::new::<RgbFormat>(strategy.clone());
                                        info!("🔍 [Bonjour] Opening RGB camera [{}] with strategy {:?}", dev_index, strategy);
                                        match Camera::with_backend(dev_index.clone(), format, nokhwa::utils::ApiBackend::Video4Linux) {
                                            Ok(mut cam) => {
                                                if cam.open_stream().is_ok() {
                                                    info!("✅ [Bonjour] Opened RGB camera [{}]", dev_index);
                                                    for _ in 0..3 { let _ = cam.frame(); }
                                                    return Some(CaptureDevice::Rgb(cam));
                                                }
                                            },
                                            Err(e) => warn!("⚠️ [Bonjour] Node [{}] initialization failed: {}", dev_index, e),
                                        }
                                    }
                                }
                            }
                            None
                        })();

                        if capture_dev.is_none() {
                            let _ = tx.blocking_send(DaemonResponse::Failure { reason: "Could not open camera device for enrollment".to_string() });
                            return;
                        }
                        let mut capture_dev = capture_dev.unwrap();

                        let mut last_processed_time = std::time::Instant::now();
                        
                        for _attempt in 0..200 {
                            if cancel_signal.load(Ordering::SeqCst) {
                                info!("🛑 Enrollment cancelled via signal");
                                let _ = capture_dev.stop();
                                return;
                            }
                            if collected_embeddings.len() >= target_scans { break; }

                            let capture_result: Result<DynamicImage> = match &mut capture_dev {
                                CaptureDevice::Rgb(cam) => {
                                    cam.frame().map_err(|e| anyhow::anyhow!(e)).and_then(|f| {
                                        f.decode_image::<RgbFormat>().map(DynamicImage::ImageRgb8).map_err(|e| anyhow::anyhow!(e))
                                    })
                                },
                                CaptureDevice::Luma(cam) => {
                                    cam.frame().map_err(|e| anyhow::anyhow!(e)).and_then(|f| {
                                        f.decode_image::<LumaFormat>().map(|l| DynamicImage::ImageRgb8(DynamicImage::ImageLuma8(l).to_rgb8())).map_err(|e| anyhow::anyhow!(e))
                                    })
                                },
                                CaptureDevice::V4l(core) => {
                                    core.stream.next().map_err(|e| anyhow::anyhow!(e)).map(|(data, _meta)| {
                                        let luma = ImageBuffer::<Luma<u8>, _>::from_raw(640, 360, data.to_vec()).unwrap();
                                        DynamicImage::ImageRgb8(DynamicImage::ImageLuma8(luma).to_rgb8())
                                    })
                                }
                            };

                            if let Ok(dyn_img) = capture_result {
                                let mut buf = Vec::new();
                                let mut cursor = Cursor::new(&mut buf);
                                let small_img = dyn_img.thumbnail(320, 240);
                                if small_img.write_to(&mut cursor, image::ImageFormat::Jpeg).is_ok() {
                                    let b64 = general_purpose::STANDARD.encode(&buf);
                                    let progress = collected_embeddings.len() as f32 / target_scans as f32;
                                    let msg = if collected_embeddings.is_empty() {
                                        "Align your face to the center...".to_string()
                                    } else {
                                        format!("Capturing... ({} of {})", collected_embeddings.len() + 1, target_scans)
                                    };

                                    if let Err(_) = tx.blocking_send(DaemonResponse::EnrollmentFrame { 
                                        base64_image: b64, 
                                        message: msg,
                                        progress
                                    }) {
                                        warn!("🔌 Enrollment interrupted (Client disconnected)");
                                        let _ = capture_dev.stop();
                                        return;
                                    }
                                }

                                if last_processed_time.elapsed() > std::time::Duration::from_millis(500) {
                                    let mut session = AuthSession::new(
                                        inference_tx.clone(),
                                        tx.clone(),
                                        store.clone(),
                                        0.0, // threshold not used for raw enrollment
                                        0.0,
                                        false,
                                        30
                                    );

                                                           // 3D DEPTH PROBE (Simulation/Hardware)
                                     let depth_map = if liveness_enabled && depth_enabled {
                                         capture_dev.get_depth_map(640, 360) 
                                     } else {
                                         None
                                     };
 
                                     match rt_handle.block_on(session.handle_enroll_frame(dyn_img, depth_map)) {
                                        Ok(Some(embedding)) => {
                                            collected_embeddings.push(embedding);
                                        },
                                        _ => {}
                                    }
                                    last_processed_time = std::time::Instant::now();
                                }
                            }
                            
                            std::thread::sleep(std::time::Duration::from_millis(50));
                        }

                        if collected_embeddings.len() >= target_scans {
                            let averaged = InferenceEngine::average_embeddings(&collected_embeddings);
                            if store.save_signature(&user, &averaged).is_ok() {
                                info!("✅ Averaged enrollment success for user: {}", user);
                                let _ = capture_dev.stop();
                                let _ = tx.blocking_send(DaemonResponse::Success { user: user.clone() });
                                return;
                            }
                        }
                        
                        let _ = capture_dev.stop();
                        let _ = tx.blocking_send(DaemonResponse::Failure { reason: "Enrollment failed or timed out".to_string() });
                    });
                },
            }
        }
    }).await?;

    Ok(())
}

fn get_username_from_uid(uid: u32) -> Option<String> {
    unsafe {
        let passwd = libc::getpwuid(uid);
        if passwd.is_null() {
            return None;
        }
        let name = std::ffi::CStr::from_ptr((*passwd).pw_name);
        Some(name.to_string_lossy().into_owned())
    }
}
