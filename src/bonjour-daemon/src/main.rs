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
use anyhow::Result;
use image::DynamicImage;
use onnx_utils::InferenceEngine;
use signature_utils::SignatureStore;
use ipc_utils::{UdsServer, DaemonRequest, DaemonResponse};
use security_utils::{EncryptionProvider, TpmProvider, PlainProvider};
use ort::ep::ExecutionProvider;

struct DaemonConfig {
    threshold: f32,
    smile_required: bool,
    autocapture: bool,
    liveness_enabled: bool,
    ask_permission: bool,
    retry_limit: u32,
}

#[tokio::main]
async fn main() -> Result<()> {
    println!("🐧 Linux Bonjour Rust Daemon (Async UDS Mode)");
    
    // 1. Initialize AI Engine
    println!("🤖 Initializing AI Engine...");
    let det_model = "/usr/share/linux-bonjour/models/models/buffalo_l/det_10g.onnx";
    let rec_model = "/usr/share/linux-bonjour/models/models/buffalo_l/w600k_r50.onnx";
    let engine = Arc::new(Mutex::new(InferenceEngine::new(det_model, rec_model)?));
    
    // 2. Initialize Security & Signature Store
    println!("🔐 Initializing Security Provider...");
    let security_provider: Arc<dyn EncryptionProvider> = match TpmProvider::new() {
        Ok(tpm) => {
            println!("🔒 TPM 2.0 Identity Hardware detected and ready.");
            Arc::new(tpm)
        },
        Err(e) => {
            println!("⚠️ TPM Initialization failed: {}. Falling back to Plain storage.", e);
            Arc::new(PlainProvider)
        }
    };

    let signature_store = Arc::new(SignatureStore::new("buffalo_l", Arc::clone(&security_provider))?);
    let system_enabled = Arc::new(AtomicBool::new(true));
    let config = Arc::new(Mutex::new(DaemonConfig {
        threshold: 0.45,
        smile_required: true,
        autocapture: false,
        liveness_enabled: true,
        ask_permission: false,
        retry_limit: 3,
    }));
    
    // Detect Acceleration
    let acceleration = if ort::execution_providers::CUDAExecutionProvider::default().is_available().unwrap_or(false) {
        "GPU (CUDA)".to_string()
    } else if ort::execution_providers::TensorRTExecutionProvider::default().is_available().unwrap_or(false) {
        "GPU (TensorRT)".to_string()
    } else {
        "CPU (Standard)".to_string()
    };
    let tpm_status = match TpmProvider::new() {
        Ok(_) => "TPM 2.0 (Active)".to_string(),
        Err(_) => "Software Fallback".to_string(),
    };
    
    println!("✅ AI Models and Secure Storage ready.");

    // 3. Start UDS Server
    let server = UdsServer::new("/run/linux-bonjour/daemon.sock");
    
    let engine_cloned = Arc::clone(&engine);
    let store_cloned = Arc::clone(&signature_store);
    let enabled_cloned = Arc::clone(&system_enabled);
    let config_cloned = Arc::clone(&config);

    server.start(move |req| {
        let engine = Arc::clone(&engine_cloned);
        let store = Arc::clone(&store_cloned);
        let enabled = Arc::clone(&enabled_cloned);
        let config = Arc::clone(&config_cloned);
        let tpm_locked = tpm_status.clone();
        let accel_locked = acceleration.clone();
        
        async move {
            match req {
                DaemonRequest::SetEnabled { enabled: val } => {
                    enabled.store(val, Ordering::SeqCst);
                    println!("⚙️ System {}", if val { "ENABLED" } else { "DISABLED" });
                    vec![DaemonResponse::Status { enabled: val }]
                },
                DaemonRequest::GetStatus => {
                    let is_enabled = enabled.load(Ordering::SeqCst);
                    vec![DaemonResponse::Status { enabled: is_enabled }]
                },
                DaemonRequest::ListIdentities => {
                    match store.list_identities() {
                        Ok(users) => vec![DaemonResponse::IdentityList { users }],
                        Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                    }
                },
                DaemonRequest::DeleteIdentity { user } => {
                    match store.delete_identity(&user) {
                        Ok(_) => vec![DaemonResponse::ActionSuccess { msg: format!("Identity '{}' deleted", user) }],
                        Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                    }
                },
                DaemonRequest::UpdateConfig { threshold, smile_required, autocapture, liveness_enabled, ask_permission, retry_limit } => {
                    let mut cfg = config.lock().await;
                    cfg.threshold = threshold;
                    cfg.smile_required = smile_required;
                    cfg.autocapture = autocapture;
                    cfg.liveness_enabled = liveness_enabled;
                    cfg.ask_permission = ask_permission;
                    cfg.retry_limit = retry_limit;
                    println!("⚙️ Configuration: thr={}, smile={}, auto={}, live={}, ask={}, retry={}", 
                        threshold, smile_required, autocapture, liveness_enabled, ask_permission, retry_limit);
                    vec![DaemonResponse::ActionSuccess { msg: "Configuration updated".to_string() }]
                },
                DaemonRequest::GetHardwareStatus => {
                    let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux).unwrap_or_default();
                    let camera_type = if devices.iter().any(|d| d.human_name().to_lowercase().contains("ir") || d.human_name().to_lowercase().contains("infrared")) {
                        "IR Camera (Detected)".to_string()
                    } else {
                        "RGB Camera (Standard)".to_string()
                    };
                    vec![DaemonResponse::HardwareStatus {
                        tpm: tpm_locked,
                        acceleration: accel_locked,
                        camera: camera_type,
                    }]
                },
                DaemonRequest::DownloadModel { name } => {
                    println!("📥 IPC: Download requested for model: {}", name);
                    // Use curl to download model weights on demand (Placeholder URL pattern)
                    // In a production scenario, these would point to the project's CDN or GitHub releases.
                    let model_url = match name.as_str() {
                        "buffalo_s" => "https://github.com/HewageNKM/linux-hello/releases/download/models/buffalo_s.zip",
                        "antelope" => "https://github.com/HewageNKM/linux-hello/releases/download/models/antelope.zip",
                        _ => {
                            return vec![DaemonResponse::Failure { reason: format!("Unknown model: {}", name) }];
                        }
                    };

                    let name_cloned = name.clone();
                    tokio::spawn(async move {
                        let target_path = format!("/usr/share/linux-bonjour/models/models/{}", name_cloned);
                        let _ = std::fs::create_dir_all(&target_path);
                        
                        println!("🚀 Starting download of {} to {}...", name_cloned, target_path);
                        // Simulate progress for UI feedback
                        // In reality, one would wrap a download stream to report percentage.
                        
                        let status = std::process::Command::new("curl")
                            .arg("-L")
                            .arg(model_url)
                            .arg("-o")
                            .arg(format!("{}/weights.zip", target_path))
                            .status();

                        if let Ok(s) = status {
                            if s.success() {
                                println!("✅ Model {} downloaded successfully.", name_cloned);
                            } else {
                                eprintln!("❌ Failed to download model {}.", name_cloned);
                            }
                        }
                    });

                    vec![DaemonResponse::ActionSuccess { msg: format!("Model {} download started in background.", name) }]
                },
                DaemonRequest::Verify { user } => {
                    let cfg = config.lock().await;
                    if !enabled.load(Ordering::SeqCst) {
                        return vec![DaemonResponse::Failure { reason: "System is globally disabled".to_string() }];
                    }

                    if cfg.ask_permission {
                        println!("💬 Authorization requested for user: {}", user);
                        // In a real scenario, this would trigger a Zenity prompt or OS notification
                        // For now, we signal back to PAM/GUI that confirmation is needed.
                        return vec![DaemonResponse::Info { msg: "CONSENT_REQUIRED".to_string() }];
                    }

                    println!("🔍 IPC: Verification request for user: {}", user);
                    
                    // Capture image with IR priority
                    let capture_result: Result<DynamicImage> = (|| {
                        let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux)?;
                        if devices.is_empty() { anyhow::bail!("No camera found"); }
                        
                        // Prioritize IR camera if available
                        let target_index = devices.iter().find(|d| {
                            let name = d.human_name().to_lowercase();
                            name.contains("ir") || name.contains("infrared")
                        }).map(|d| d.index().clone()).unwrap_or(devices[0].index().clone());
                        
                        let mut camera = Camera::new(target_index, RequestedFormat::new::<RgbFormat>(RequestedFormatType::Closest))?;
                        camera.open_stream()?;
                        std::thread::sleep(std::time::Duration::from_millis(500));
                        Ok(DynamicImage::ImageRgb8(camera.frame()?.decode_image::<RgbFormat>()?))
                    })();

                    match capture_result {
                        Ok(dyn_img) => {
                            let mut engine_lock = engine.lock().await;
                            let cfg = config.lock().await;
                            
                            match engine_lock.detect_faces(&dyn_img) {
                                Ok(detections) => {
                                    if detections.is_empty() {
                                        vec![DaemonResponse::Failure { reason: "No face detected".to_string() }]
                                    } else {
                                        let face = &detections[0];
                                        let aligned = engine_lock.align_face(&dyn_img, &face.landmarks);
                                        match engine_lock.get_face_embedding(&aligned) {
                                            Ok(embedding) => {
                                                match store.load_signature(&user) {
                                                    Ok(saved_embedding) => {
                                                        let score = SignatureStore::cosine_similarity(&embedding, &saved_embedding);
                                                        let liveness_threshold = 0.58; 
                                                        
                                                        if score > cfg.threshold {
                                                            if !cfg.smile_required || face.liveness_score > liveness_threshold {
                                                                vec![DaemonResponse::Success { user: user.clone() }]
                                                            } else {
                                                                vec![DaemonResponse::Failure { reason: format!("Match OK ({:.2}), but liveness failed ({:.2}) - Please smile/blink!", score, face.liveness_score) }]
                                                            }
                                                        } else {
                                                            vec![DaemonResponse::Failure { reason: format!("Match failed (score: {:.2})", score) }]
                                                        }
                                                    },
                                                    Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                                                }
                                            },
                                            Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                                        }
                                    }
                                },
                                Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                            }
                        },
                        Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                    }
                },
                DaemonRequest::Enroll { user } => {
                    println!("💾 IPC: Enrollment request for user: {}", user);
                    
                    let capture_result: Result<DynamicImage> = (|| {
                        let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux)?;
                        if devices.is_empty() { anyhow::bail!("No camera found"); }
                        let target_device = if devices.len() > 1 { &devices[1] } else { &devices[0] };
                        let mut camera = Camera::new(target_device.index().clone(), RequestedFormat::new::<RgbFormat>(RequestedFormatType::None))?;
                        camera.open_stream()?;
                        std::thread::sleep(std::time::Duration::from_millis(1000));
                        Ok(DynamicImage::ImageRgb8(camera.frame()?.decode_image::<RgbFormat>()?))
                    })();

                    match capture_result {
                        Ok(dyn_img) => {
                            let mut engine_lock = engine.lock().await;
                            match engine_lock.detect_faces(&dyn_img) {
                                Ok(detections) => {
                                    if detections.is_empty() {
                                        vec![DaemonResponse::Failure { reason: "No face detected for enrollment".to_string() }]
                                    } else {
                                        let aligned = engine_lock.align_face(&dyn_img, &detections[0].landmarks);
                                        match engine_lock.get_face_embedding(&aligned) {
                                            Ok(embedding) => {
                                                match store.save_signature(&user, &embedding) {
                                                    Ok(_) => vec![DaemonResponse::Success { user: user.clone() }],
                                                    Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                                                }
                                            },
                                            Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                                        }
                                    }
                                },
                                Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                            }
                        },
                        Err(e) => vec![DaemonResponse::Failure { reason: e.to_string() }],
                    }
                },
            }
        }
    }).await?;

    Ok(())
}
