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
use security_utils::{EncryptionProvider, PlainProvider};
use ort::ep::ExecutionProvider;

struct DaemonConfig {
    threshold: f32,
    smile_required: bool,
    autocapture: bool,
    liveness_enabled: bool,
    ask_permission: bool,
    retry_limit: u32,
    camera_path: Option<String>,
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
    let security_provider: Arc<dyn EncryptionProvider> = match security_utils::SoftwareProvider::new() {
        Ok(soft) => {
            println!("🔒 Hardware-bound Software Encryption active (Machine-ID binding).");
            Arc::new(soft)
        },
        Err(e) => {
            println!("⚠️ Software encryption initialization failed: {}. Falling back to Plain storage.", e);
            Arc::new(PlainProvider)
        }
    };

    let signature_store = Arc::new(SignatureStore::new("buffalo_l", Arc::clone(&security_provider))?);
    let system_enabled = Arc::new(AtomicBool::new(true));
    let config = Arc::new(Mutex::new(DaemonConfig {
        threshold: 0.38, // Lowered slightly for better reliability on first try
        smile_required: false, // Changed default to false to reduce verification friction
        autocapture: false,
        liveness_enabled: true,
        ask_permission: false,
        retry_limit: 3,
        camera_path: None,
    }));
    
    // Detect Acceleration
    let acceleration = if ort::execution_providers::CUDAExecutionProvider::default().is_available().unwrap_or(false) {
        "GPU (CUDA)".to_string()
    } else if ort::execution_providers::TensorRTExecutionProvider::default().is_available().unwrap_or(false) {
        "GPU (TensorRT)".to_string()
    } else {
        "CPU (Standard)".to_string()
    };
    let tpm_status = match security_utils::SoftwareProvider::new() {
        Ok(_) => "Hardware-bound (Active)".to_string(),
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
                DaemonRequest::UpdateConfig { threshold, smile_required, autocapture, liveness_enabled, ask_permission, retry_limit, camera_path } => {
                    let mut cfg = config.lock().await;
                    cfg.threshold = threshold;
                    cfg.smile_required = smile_required;
                    cfg.autocapture = autocapture;
                    cfg.liveness_enabled = liveness_enabled;
                    cfg.ask_permission = ask_permission;
                    cfg.retry_limit = retry_limit;
                    cfg.camera_path = camera_path;
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
                DaemonRequest::GetCameraList => {
                    let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux).unwrap_or_default();
                    let list: Vec<String> = devices.iter().map(|d| d.human_name()).collect();
                    vec![DaemonResponse::CameraList { devices: list }]
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
                    
                    // Capture image with failover logic
                    let camera_path_override = cfg.camera_path.clone();
                    let capture_result: Result<DynamicImage> = (|| {
                        let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux)?;
                        if devices.is_empty() { anyhow::bail!("No camera found"); }
                        
                        let sorted_devices = if let Some(ref path) = camera_path_override {
                            // User selected a specific camera
                            devices.iter().filter(|d| d.human_name() == *path || d.index().to_string() == *path).cloned().collect::<Vec<_>>()
                        } else {
                            // Default: prioritize IR, then try everything in order
                            let mut d = devices.clone();
                            d.sort_by_key(|a| {
                                let name = a.human_name().to_lowercase();
                                if name.contains("ir") || name.contains("infrared") { 0 } else { 1 }
                            });
                            d
                        };

                        println!("📸 Found {} cameras. Probing in order...", sorted_devices.len());

                        let mut last_err = anyhow::anyhow!("No working camera found");
                        for dev in sorted_devices {
                            println!("🔍 Probing camera: {} (Index: {})", dev.human_name(), dev.index());
                            
                            // Try multiple formats for each device
                            let format_strategies = vec![
                                RequestedFormatType::AbsoluteHighestResolution,
                                RequestedFormatType::None,
                            ];

                            for strategy in format_strategies {
                                let fmt_name = format!("{:?}", strategy);
                                let format = RequestedFormat::new::<RgbFormat>(strategy);
                                match Camera::with_backend(dev.index().clone(), format, nokhwa::utils::ApiBackend::Video4Linux) {
                                    Ok(mut camera) => {
                                        match camera.open_stream() {
                                            Ok(_) => {
                                                println!("✅ Successfully opened {} with format {}", dev.human_name(), fmt_name);
                                                
                                                // Warm up: capture a few frames and discard them
                                                println!("📸 Warming up camera...");
                                                for _ in 0..5 {
                                                    let _ = camera.frame();
                                                    std::thread::sleep(std::time::Duration::from_millis(100));
                                                }

                                                println!("📸 Capturing final frame...");
                                                match camera.frame() {
                                                    Ok(frame) => {
                                                        println!("✅ Frame captured successfully");
                                                        let dyn_img = frame.decode_image::<RgbFormat>()?;
                                                        let _ = camera.stop_stream();
                                                        return Ok(DynamicImage::ImageRgb8(dyn_img));
                                                    },
                                                    Err(e) => {
                                                        println!("❌ Failed to capture frame from {}: {}", dev.human_name(), e);
                                                        let _ = camera.stop_stream();
                                                        last_err = e.into();
                                                    }
                                                }
                                            },
                                            Err(e) => {
                                                println!("❌ Failed to open stream for {} with {}: {}", dev.human_name(), fmt_name, e);
                                                last_err = e.into();
                                            }
                                        }
                                    },
                                    Err(e) => {
                                        println!("❌ Failed to initialize {} with {}: {}", dev.human_name(), fmt_name, e);
                                        last_err = e.into();
                                    }
                                }
                            }
                        }
                        Err(last_err)
                    })();

                    match capture_result {
                        Ok(dyn_img) => {
                            println!("🤔 Attempting to acquire AI Engine lock...");
                            let mut engine_lock = engine.lock().await;
                            println!("✅ AI Engine lock acquired.");

                            // Redundant lock removed - cfg is already available from outer scope
                            
                            println!("🧠 Running Face Detection...");
                            match engine_lock.detect_faces(&dyn_img) {
                                Ok(detections) => {
                                    println!("👥 Detected {} faces.", detections.len());
                                    if detections.is_empty() {
                                        vec![DaemonResponse::Failure { reason: "No face detected".to_string() }]
                                    } else {
                                        println!("📐 Aligning face and extracting embedding...");
                                        let face = &detections[0];
                                        let aligned = engine_lock.align_face(&dyn_img, &face.landmarks);
                                        match engine_lock.get_face_embedding(&aligned) {
                                            Ok(embedding) => {
                                                println!("💾 Comparing with saved signature for user: {}...", user);
                                                match store.load_signature(&user) {
                                                    Ok(saved_embedding) => {
                                                        let score = SignatureStore::cosine_similarity(&embedding, &saved_embedding);
                                                        println!("📊 Match Score: {:.4} (Threshold: {:.4})", score, cfg.threshold);
                                                        println!("💓 Liveness Score: {:.4}", face.liveness_score);
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
                    
                    let camera_path_override = {
                        let cfg = config.lock().await;
                        cfg.camera_path.clone()
                    };
                    
                    let capture_result: Result<DynamicImage> = (|| {
                        let devices = nokhwa::query(nokhwa::utils::ApiBackend::Video4Linux)?;
                        if devices.is_empty() { anyhow::bail!("No camera found"); }
                        
                        let sorted_devices = if let Some(ref path) = camera_path_override {
                            devices.iter().filter(|d| d.human_name() == *path || d.index().to_string() == *path).cloned().collect::<Vec<_>>()
                        } else {
                            let mut d = devices.clone();
                            d.sort_by_key(|a| {
                                let name = a.human_name().to_lowercase();
                                if name.contains("ir") || name.contains("infrared") { 0 } else { 1 }
                            });
                            d
                        };

                        let mut last_err = anyhow::anyhow!("No working camera found");
                        for dev in sorted_devices {
                            let format_strategies = vec![RequestedFormatType::AbsoluteHighestResolution, RequestedFormatType::None];
                            for strategy in format_strategies {
                                let format = RequestedFormat::new::<RgbFormat>(strategy);
                                if let Ok(mut camera) = Camera::with_backend(dev.index().clone(), format, nokhwa::utils::ApiBackend::Video4Linux) {
                                    if camera.open_stream().is_ok() {
                                        println!("📸 (Enroll) Warming up {}", dev.human_name());
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
                        Err(last_err)
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
