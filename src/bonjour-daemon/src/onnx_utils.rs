use ort::session::Session;
use ort::value::Value;
use ndarray::Array4;
use image::{DynamicImage, GenericImageView, RgbImage};
use anyhow::Result;
use nalgebra::{SMatrix, SVector};

const REFERENCE_LANDMARKS: [[f32; 2]; 5] = [
    [38.2946, 51.6963],
    [73.5318, 51.6963],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.3655],
];

#[derive(Debug, Clone)]
pub struct FaceDetection {
    pub bbox: [f32; 4],
    pub score: f32,
    pub landmarks: [[f32; 2]; 5],
    pub liveness_score: f32,
}

pub struct InferenceEngine {
    detection_session: Session,
    recognition_session: Session,
}

impl InferenceEngine {
    pub fn new(det_path: &str, rec_path: &str) -> Result<Self> {
        let detection_session = Session::builder()?.commit_from_file(det_path)?;
        let recognition_session = Session::builder()?.commit_from_file(rec_path)?;
        
        Ok(Self {
            detection_session,
            recognition_session,
        })
    }

    pub fn has_gpu(&self) -> bool {
        // ort handles execution providers. If CUDA/TensorRT is available and 
        // linked correctly, it will be used. Returning false won't block GPU usage
        // but it will affect the Hardware Dashboard labels.
        false
    }

    pub fn detect_faces(&mut self, img: &DynamicImage) -> Result<Vec<FaceDetection>> {
        let (orig_w, orig_h) = img.dimensions();
        let target_size = 640;
        let resized = img.resize_exact(target_size, target_size, image::imageops::FilterType::Triangle);
        
        let rgb = resized.to_rgb8();
        let input = ndarray::Array::from_shape_vec((target_size as usize, target_size as usize, 3), rgb.into_raw())?
            .mapv(|v| (v as f32 - 127.5) / 128.0)
            .permuted_axes([2, 0, 1]) // HWC -> CHW
            .insert_axis(ndarray::Axis(0)); // CHW -> NCHW

        let input_tensor = Value::from_array(input)?;
        let outputs = self.detection_session.run(ort::inputs![input_tensor])?;

        let strides = [8, 16, 32];
        let score_names = ["448", "471", "494"];
        let bbox_names = ["451", "474", "497"];
        let kps_names = ["454", "477", "500"];

        let mut all_detections = Vec::new();
        let score_threshold = 0.5;

        let scale_x = orig_w as f32 / target_size as f32;
        let scale_y = orig_h as f32 / target_size as f32;

        for i in 0..3 {
            let stride = strides[i];
            let (_, score_slice) = outputs[score_names[i]].try_extract_tensor::<f32>()?;
            let (_, bbox_slice) = outputs[bbox_names[i]].try_extract_tensor::<f32>()?;
            let (_, kps_slice) = outputs[kps_names[i]].try_extract_tensor::<f32>()?;
            
            let num_anchors = score_slice.len();
            let feat_w = target_size / stride;
            
            for idx in 0..num_anchors {
                let score = score_slice[idx];
                if score < score_threshold {
                    continue;
                }
                
                let anchor_idx = idx / 2;
                let y = (anchor_idx / feat_w as usize) as f32 * stride as f32;
                let x = (anchor_idx % feat_w as usize) as f32 * stride as f32;
                
                let b_idx = idx * 4;
                let dists = [
                    bbox_slice[b_idx] * stride as f32,
                    bbox_slice[b_idx + 1] * stride as f32,
                    bbox_slice[b_idx + 2] * stride as f32,
                    bbox_slice[b_idx + 3] * stride as f32,
                ];
                
                let x1 = (x - dists[0]) * scale_x;
                let y1 = (y - dists[1]) * scale_y;
                let x2 = (x + dists[2]) * scale_x;
                let y2 = (y + dists[3]) * scale_y;
                
                let mut landmarks = [[0.0; 2]; 5];
                let k_idx = idx * 10;
                for k in 0..5 {
                    landmarks[k][0] = (x + kps_slice[k_idx + k * 2] * stride as f32) * scale_x;
                    landmarks[k][1] = (y + kps_slice[k_idx + k * 2 + 1] * stride as f32) * scale_y;
                }
                
                let liveness_score = Self::calculate_liveness_score(&landmarks);

                all_detections.push(FaceDetection {
                    bbox: [x1, y1, x2, y2],
                    score,
                    landmarks,
                    liveness_score,
                });
            }
        }

        drop(outputs);
        Ok(Self::nms(all_detections, 0.4))
    }

    pub fn align_face(&self, img: &DynamicImage, landmarks: &[[f32; 2]; 5]) -> DynamicImage {
        let transform = Self::get_similarity_transform(landmarks, &REFERENCE_LANDMARKS);
        let a = transform[0];
        let b = transform[1];
        let tx = transform[2];
        let ty = transform[3];

        let det = a * a + b * b;
        let ia = a / det;
        let ib = b / det;

        let mut aligned = RgbImage::new(112, 112);
        let (w, h) = img.dimensions();

        for (u, v, pixel) in aligned.enumerate_pixels_mut() {
            let du = u as f32 - tx;
            let dv = v as f32 - ty;
            
            let x = ia * du + ib * dv;
            let y = -ib * du + ia * dv;
            
            if x >= 0.0 && x < (w - 1) as f32 && y >= 0.0 && y < (h - 1) as f32 {
                let x0 = x.floor() as u32;
                let y0 = y.floor() as u32;
                let x1 = x0 + 1;
                let y1 = y0 + 1;
                
                let dx = x - x0 as f32;
                let dy = y - y0 as f32;
                
                let p00 = img.get_pixel(x0, y0);
                let p10 = img.get_pixel(x1, y0);
                let p01 = img.get_pixel(x0, y1);
                let p11 = img.get_pixel(x1, y1);
                
                for i in 0..3 {
                    let val = (1.0 - dx) * (1.0 - dy) * p00[i] as f32
                            + dx * (1.0 - dy) * p10[i] as f32
                            + (1.0 - dx) * dy * p01[i] as f32
                            + dx * dy * p11[i] as f32;
                    pixel[i] = val as u8;
                }
            }
        }
        DynamicImage::ImageRgb8(aligned)
    }

    pub fn get_face_embedding(&mut self, aligned_img: &DynamicImage) -> Result<Vec<f32>> {
        let rgb = aligned_img.to_rgb8();
        let input = ndarray::Array::from_shape_vec((112, 112, 3), rgb.into_raw())?
            .mapv(|v| (v as f32 - 127.5) / 128.0)
            .permuted_axes([2, 0, 1]) // HWC -> CHW
            .insert_axis(ndarray::Axis(0)); // CHW -> NCHW

        let input_tensor = Value::from_array(input)?;
        let outputs = self.recognition_session.run(ort::inputs![input_tensor])?;

        let (_, embedding_slice) = outputs[0].try_extract_tensor::<f32>()?;
        
        let mut norm = 0.0;
        for &v in embedding_slice {
            norm += v * v;
        }
        norm = norm.sqrt().max(1e-6);
        
        Ok(embedding_slice.iter().map(|&v| v / norm).collect())
    }

    fn get_similarity_transform(src: &[[f32; 2]; 5], dst: &[[f32; 2]; 5]) -> [f32; 4] {
        let mut a_mat = SMatrix::<f32, 10, 4>::zeros();
        let mut b_vec = SVector::<f32, 10>::zeros();

        for i in 0..5 {
            a_mat[(2 * i, 0)] = src[i][0];
            a_mat[(2 * i, 1)] = -src[i][1];
            a_mat[(2 * i, 2)] = 1.0;
            a_mat[(2 * i, 3)] = 0.0;

            a_mat[(2 * i + 1, 0)] = src[i][1];
            a_mat[(2 * i + 1, 1)] = src[i][0];
            a_mat[(2 * i + 1, 2)] = 0.0;
            a_mat[(2 * i + 1, 3)] = 1.0;

            b_vec[2 * i] = dst[i][0];
            b_vec[2 * i + 1] = dst[i][1];
        }

        let x = (a_mat.transpose() * a_mat).try_inverse().unwrap_or_else(SMatrix::identity) * a_mat.transpose() * b_vec;
        [x[0], x[1], x[2], x[3]]
    }

    fn nms(mut dets: Vec<FaceDetection>, iou_threshold: f32) -> Vec<FaceDetection> {
        if dets.is_empty() {
            return Vec::new();
        }
        dets.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
        
        let mut keep = Vec::new();
        let mut suppressed = vec![false; dets.len()];
        for i in 0..dets.len() {
            if suppressed[i] { continue; }
            keep.push(dets[i].clone());
            for j in i + 1..dets.len() {
                if suppressed[j] { continue; }
                if Self::iou(&dets[i].bbox, &dets[j].bbox) > iou_threshold {
                    suppressed[j] = true;
                }
            }
        }
        keep
    }

    fn iou(box1: &[f32; 4], box2: &[f32; 4]) -> f32 {
        let x1 = box1[0].max(box2[0]);
        let y1 = box1[1].max(box2[1]);
        let x2 = box1[2].min(box2[2]);
        let y2 = box1[3].min(box2[3]);
        let w = (x2 - x1).max(0.0);
        let h = (y2 - y1).max(0.0);
        let inter = w * h;
        let area1 = (box1[2] - box1[0]) * (box1[3] - box1[1]);
        let area2 = (box2[2] - box2[0]) * (box2[3] - box2[1]);
        inter / (area1 + area2 - inter)
    }

    fn calculate_liveness_score(landmarks: &[[f32; 2]; 5]) -> f32 {
        let eye_dist = ((landmarks[0][0] - landmarks[1][0]).powi(2) + (landmarks[0][1] - landmarks[1][1]).powi(2)).sqrt();
        let mouth_width = ((landmarks[3][0] - landmarks[4][0]).powi(2) + (landmarks[3][1] - landmarks[4][1]).powi(2)).sqrt();
        if eye_dist > 0.0 { mouth_width / eye_dist } else { 0.0 }
    }

    pub fn average_embeddings(embeddings: &[Vec<f32>]) -> Vec<f32> {
        if embeddings.is_empty() { return Vec::new(); }
        let dim = embeddings[0].len();
        let mut avg = vec![0.0f32; dim];
        for emb in embeddings {
            for (i, &v) in emb.iter().enumerate() {
                if i < dim { avg[i] += v; }
            }
        }
        for v in avg.iter_mut() {
            *v /= embeddings.len() as f32;
        }
        avg
    }
}
