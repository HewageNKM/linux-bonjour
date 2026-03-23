use tokio::sync::{mpsc, oneshot};
use crate::onnx_utils::{InferenceEngine, FaceDetection};
use crate::liveness_3d::{Liveness3D, LivenessResult};
use image::DynamicImage;
use tracing::{info, warn, error, debug};
use std::sync::Arc;
use tokio::sync::Mutex;
use anyhow::Result;

pub enum InferenceJob {
    Detect {
        image: DynamicImage,
        depth_map: Option<Vec<f32>>, // New: Optional 3D data
        respond_to: oneshot::Sender<Result<(Vec<FaceDetection>, Option<crate::onnx_utils::FaceQuality>, LivenessResult)>>,
    },
    AlignAndEmbed {
        image: DynamicImage,
        landmarks: [[f32; 2]; 5],
        respond_to: oneshot::Sender<Result<Vec<f32>>>,
    },
    UpdateModel {
        det_path: String,
        rec_path: String,
        respond_to: oneshot::Sender<Result<()>>,
    },
}

pub struct InferenceWorker {
    engine: Arc<Mutex<InferenceEngine>>,
}

impl InferenceWorker {
    pub fn spawn(engine: Arc<Mutex<InferenceEngine>>) -> mpsc::Sender<InferenceJob> {
        let (tx, mut rx) = mpsc::channel::<InferenceJob>(32);
        let worker = Self { engine };

        tokio::spawn(async move {
            info!("🚀 [InferenceWorker] Started.");
            while let Some(job) = rx.recv().await {
                match job {
                    InferenceJob::Detect { image, depth_map, respond_to } => {
                        let mut engine = worker.engine.lock().await;
                        let faces = engine.detect_faces(&image);
                        let quality = if let Ok(ref f) = faces {
                            if !f.is_empty() {
                                Some(engine.analyze_quality(&image, &f[0]))
                            } else {
                                None
                            }
                        } else {
                            None
                        };

                        let liveness = match &depth_map {
                            Some(dm) if !faces.as_ref().map_or(true, |f: &Vec<crate::onnx_utils::FaceDetection>| f.is_empty()) => {
                                // Validate liveness of the primary face
                                let primary = &faces.as_ref().unwrap()[0];
                                Liveness3D::verify_geometry(
                                    dm, 
                                    image.width() as usize, 
                                    image.height() as usize, 
                                    &primary.landmarks
                                )
                            },
                            _ => LivenessResult::NoData,
                        };

                        let _ = respond_to.send(faces.map(|f| (f, quality, liveness)));
                    }
                    InferenceJob::AlignAndEmbed { image, landmarks, respond_to } => {
                        let mut engine = worker.engine.lock().await;
                        let aligned = engine.align_face(&image, &landmarks);
                        let res = engine.get_face_embedding(&aligned);
                        let _ = respond_to.send(res);
                    }
                    InferenceJob::UpdateModel { det_path, rec_path, respond_to } => {
                        info!("🔄 [InferenceWorker] Updating model...");
                        let res = match InferenceEngine::new(&det_path, &rec_path) {
                            Ok(new_engine) => {
                                let mut engine = worker.engine.lock().await;
                                *engine = new_engine;
                                Ok(())
                            }
                            Err(e) => Err(e),
                        };
                        let _ = respond_to.send(res);
                    }
                }
            }
            info!("👋 [InferenceWorker] Shutting down.");
        });

        tx
    }
}
