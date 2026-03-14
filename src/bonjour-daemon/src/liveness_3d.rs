use tracing::{info, warn, debug};
use anyhow::Result;

pub struct Liveness3D;

#[derive(Debug, PartialEq)]
pub enum LivenessResult {
    Verified,
    SpoofPlanar,   // Detected a flat surface (photo/tablet)
    SpoofAnomalous, // Invalid geometry (mask/non-human)
    NoData,
}

impl Liveness3D {
    /// Analyzes a depth map corresponding to a detected face region.
    /// depth_map: A slice of f32 containing depth values (meters).
    /// width/height: Dimensions of the depth patch.
    /// landmarks: Face landmarks scaled to the depth patch.
    pub fn verify_geometry(
        depth_map: &[f32],
        width: usize,
        height: usize,
        landmarks: &[[f32; 2]; 5],
    ) -> LivenessResult {
        if depth_map.is_empty() {
            return LivenessResult::NoData;
        }

        // 1. Planar Detection (Standard Deviation check)
        // If the variance in depth is too low, it's a flat surface like a photo.
        let mean: f32 = depth_map.iter().sum::<f32>() / depth_map.len() as f32;
        let variance: f32 = depth_map.iter()
            .map(|val| (val - mean).powi(2))
            .sum::<f32>() / depth_map.len() as f32;
        
        let std_dev = variance.sqrt();
        
        // Thresholds based on typical face depth variance (~2cm - 5cm)
        // A flat screen will have < 1mm variance.
        if std_dev < 0.002 { 
            warn!("🛑 3D Liveness: Planar surface detected (StdDev: {:.4}m). Possible photo spoof.", std_dev);
            return LivenessResult::SpoofPlanar;
        }

        // 2. Convexity (Nose vs. Ears)
        // Nose is at index 2 in typical InsightFace landmarks.
        // Ears/Sides are roughly indices 3 and 4? 
        // Actually: 0=LeftEye, 1=RightEye, 2=NoseTip, 3=LeftMouth, 4=RightMouth.
        
        let nose_tip = landmarks[2];
        let l_eye = landmarks[0];
        let r_eye = landmarks[1];

        // Sample depth at landmarks
        let d_nose = depth_map[(nose_tip[1] as usize * width + nose_tip[0] as usize).min(depth_map.len()-1)];
        let d_l_eye = depth_map[(l_eye[1] as usize * width + l_eye[0] as usize).min(depth_map.len()-1)];
        let d_r_eye = depth_map[(r_eye[1] as usize * width + r_eye[0] as usize).min(depth_map.len()-1)];

        // In a real face, the nose tip should be CLOSER to the camera than the eyes.
        // (Assuming Z-axis points into the camera, smaller depth = closer)
        let eye_avg = (d_l_eye + d_r_eye) / 2.0;
        let nose_offset = eye_avg - d_nose; // Positive if nose is closer

        if nose_offset < 0.015 { // Less than 1.5cm depth difference
             warn!("🛑 3D Liveness: Insufficient face convexity (Offset: {:.4}m).", nose_offset);
             return LivenessResult::SpoofAnomalous;
        }

        info!("✅ 3D Liveness: Geometry verified (Offset: {:.4}m, StdDev: {:.4}m).", nose_offset, std_dev);
        LivenessResult::Verified
    }
}
