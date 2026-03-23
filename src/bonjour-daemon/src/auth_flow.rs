use std::time::{Duration, Instant};
use tokio::sync::mpsc;
use crate::inference_worker::InferenceJob;
use crate::liveness_3d::LivenessResult;
use crate::ipc_utils::{DaemonResponse};
use crate::signature_utils::SignatureStore;
use std::sync::Arc;
use anyhow::Result;
use image::DynamicImage;
use tracing::{info, warn, error, debug};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum SessionState {
    Idle,
    InitializingCamera,
    Scanning,
    Identified,
    Success,
    Failure,
    Timeout,
}

#[derive(Debug, Clone, PartialEq)]
pub enum AuthDecision {
    Continue { message: String, progress: f32, feedback: Option<String> },
    Success { user: String, score: f32, liveness: f32 },
    Failure { reason: String },
}

pub struct AuthSession {
    pub state: SessionState,
    pub start_time: Instant,
    pub timeout: Duration,
    pub inference_tx: mpsc::Sender<InferenceJob>,
    pub response_tx: mpsc::Sender<DaemonResponse>,
    pub store: Arc<SignatureStore>,
    pub threshold: f32,
    pub liveness_threshold: f32,
    pub liveness_enabled: bool,
}

impl AuthSession {
    pub fn new(
        inference_tx: mpsc::Sender<InferenceJob>,
        response_tx: mpsc::Sender<DaemonResponse>,
        store: Arc<SignatureStore>,
        threshold: f32,
        liveness_threshold: f32,
        liveness_enabled: bool,
        timeout_secs: u64,
    ) -> Self {
        Self {
            state: SessionState::Idle,
            start_time: Instant::now(),
            timeout: Duration::from_secs(timeout_secs),
            inference_tx,
            response_tx,
            store,
            threshold,
            liveness_threshold,
            liveness_enabled,
        }
    }

    pub async fn handle_verify_frame(&mut self, user: &str, img: DynamicImage, depth_map: Option<Vec<f32>>) -> Result<AuthDecision> {
        if self.start_time.elapsed() > self.timeout {
            return Ok(AuthDecision::Failure { reason: "Timeout reached".to_string() });
        }

        let (res_tx, res_rx) = tokio::sync::oneshot::channel();
        self.inference_tx.send(InferenceJob::Detect { 
            image: img.clone(), 
            depth_map, 
            respond_to: res_tx 
        }).await?;
        
        let (detections, quality, liveness_3d): (Vec<crate::onnx_utils::FaceDetection>, Option<crate::onnx_utils::FaceQuality>, LivenessResult) = match res_rx.await? {
            Ok(res) => res,
            Err(e) => return Ok(AuthDecision::Failure { reason: format!("Detection error: {}", e) }),
        };

        let feedback = Self::generate_feedback(&quality);
        if let Some(f) = &feedback {
            let _ = self.response_tx.send(DaemonResponse::Scanning { 
                msg: "Improving capture...".to_string(), 
                feedback: Some(f.clone()) 
            }).await;
        }

        if detections.is_empty() {
            return Ok(AuthDecision::Continue { 
                message: "No face detected".to_string(),
                progress: 0.0,
                feedback: None
            });
        }

        // HARD GATING: If 3D liveness detected a spoof, fail immediately
        match liveness_3d {
            LivenessResult::SpoofPlanar => return Ok(AuthDecision::Failure { reason: "Security Alert: Planar spoof detected".to_string() }),
            LivenessResult::SpoofAnomalous => return Ok(AuthDecision::Failure { reason: "Security Alert: Anomalous face geometry".to_string() }),
            _ => {}
        }

        let detection = &detections[0];
        let (emb_tx, emb_rx) = tokio::sync::oneshot::channel();
        self.inference_tx.send(InferenceJob::AlignAndEmbed { 
            image: img, 
            landmarks: detection.landmarks, 
            respond_to: emb_tx 
        }).await?;
        
        let embedding = match emb_rx.await? {
            Ok(e) => e,
            Err(e) => return Ok(AuthDecision::Failure { reason: format!("Embedding error: {}", e) }),
        };
        
        // Check against target user
        if let Ok(saved_embedding) = self.store.load_signature(user) {
            let score = crate::signature_utils::SignatureStore::cosine_similarity(&embedding, &saved_embedding);
            if score > self.threshold {
                let liveness_passed = !self.liveness_enabled || detection.liveness_score > self.liveness_threshold;
                if liveness_passed {
                    return Ok(AuthDecision::Success { 
                        user: user.to_string(), 
                        score, 
                        liveness: detection.liveness_score 
                    });
                }
            }
        }

        // Search all
        if let Ok(Some((identified_user, score))) = self.store.identify_user(&embedding, self.threshold) {
            let liveness_passed = !self.liveness_enabled || detection.liveness_score > self.liveness_threshold;
            if liveness_passed {
                return Ok(AuthDecision::Success { 
                    user: identified_user, 
                    score, 
                    liveness: detection.liveness_score 
                });
            }
        }

        Ok(AuthDecision::Continue { 
            message: "Face detected, but no match".to_string(), 
            progress: 0.5,
            feedback: None 
        })
    }

    pub async fn handle_enroll_frame(&mut self, img: DynamicImage, depth_map: Option<Vec<f32>>) -> Result<(Option<Vec<f32>>, Option<String>)> {
        let (res_tx, res_rx) = tokio::sync::oneshot::channel();
        self.inference_tx.send(InferenceJob::Detect { 
            image: img.clone(), 
            depth_map, 
            respond_to: res_tx 
        }).await?;
        
        let (detections, quality, _): (Vec<crate::onnx_utils::FaceDetection>, Option<crate::onnx_utils::FaceQuality>, LivenessResult) = match res_rx.await? {
            Ok(d) => d,
            Err(_) => return Ok((None, None)),
        };

        let feedback = Self::generate_feedback(&quality);

        let detection = &detections[0];
        let (emb_tx, emb_rx) = tokio::sync::oneshot::channel();
        self.inference_tx.send(InferenceJob::AlignAndEmbed { 
            image: img, 
            landmarks: detection.landmarks, 
            respond_to: emb_tx 
        }).await?;
        
        let embedding = match emb_rx.await? {
            Ok(e) => e,
            Err(_) => return Ok((None, None)),
        };

        info!("📍 Collected scan (liveness: {:.2})", detection.liveness_score);
        Ok((Some(embedding), None))
    }

    fn generate_feedback(quality: &Option<crate::onnx_utils::FaceQuality>) -> Option<String> {
        if let Some(q) = quality {
            if q.is_too_dark { return Some("Too dark, adjust lighting".to_string()); }
            if q.is_too_bright { return Some("Too bright, avoid glare".to_string()); }
            if q.is_too_small { return Some("Move closer".to_string()); }
            if q.is_too_large { return Some("Too close, move back".to_string()); }
            if q.is_not_centered { return Some("Center your face".to_string()); }
            if q.is_tilted { return Some("Keep your head straight".to_string()); }
        }
        None
    }
}
