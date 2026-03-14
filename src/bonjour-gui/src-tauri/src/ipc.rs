use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug)]
#[serde(tag = "cmd", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DaemonRequest {
    Verify { 
        user: String,
        #[serde(default)]
        bypass_consent: bool 
    },
    Enroll { 
        user: String,
        #[serde(default)]
        bypass_consent: bool
    },
    GetStatus,
    SetEnabled { enabled: bool },
    ListIdentities,
    DeleteIdentity { user: String },
    UpdateConfig { 
        threshold: f32, 
        smile_required: bool,
        autocapture: bool,
        liveness_enabled: bool,
        liveness_threshold: f32,
        ask_permission: bool,
        retry_limit: u32,
        camera_path: Option<String>,
        active_model: Option<String>,
        #[serde(default)]
        enable_login: bool,
        #[serde(default)]
        enable_sudo: bool,
        #[serde(default)]
        enable_polkit: bool,
    },
    GetHardwareStatus,
    DownloadModel { name: String },
    GetCameraList,
    GetConfig,
    RenameIdentity { old_name: String, new_name: String },
    STOP,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct CameraInfo {
    pub name: String,
    pub path: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "status", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DaemonResponse {
    Scanning { msg: String },
    Success { user: String },
    Failure { reason: String },
    Info { msg: String },
    Status { enabled: bool },
    IdentityList { users: Vec<String> },
    ActionSuccess { msg: String },
    HardwareStatus { 
        tpm: String, 
        acceleration: String, 
        camera: String,
        active_model: String,
        enabled: bool,
        #[serde(default)]
        depth_supported: bool,
    },
    DownloadProgress { 
        name: String,
        percentage: f32 
    },
    EnrollmentFrame {
        base64_image: String,
        message: String,
        progress: f32
    },
    CameraList { devices: Vec<CameraInfo> },
    Config {
        threshold: f32,
        smile_required: bool,
        autocapture: bool,
        liveness_enabled: bool,
        liveness_threshold: f32,
        ask_permission: bool,
        retry_limit: u32,
        camera_path: Option<String>,
        active_model: String,
        #[serde(default)]
        enabled: bool,
        #[serde(default)]
        has_face_data: bool,
        #[serde(default)]
        enable_login: bool,
        #[serde(default)]
        enable_sudo: bool,
        #[serde(default)]
        enable_polkit: bool,
        #[serde(default)]
        depth_active: bool,
    },
}
