use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug)]
#[serde(tag = "cmd", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DaemonRequest {
    Verify { 
        user: String,
        #[serde(default)]
        bypass_consent: bool 
    },
    Enroll { user: String },
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
    },
    GetHardwareStatus,
    DownloadModel { name: String },
    GetCameraList,
    GetConfig,
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
        camera: String 
    },
    DownloadProgress { 
        name: String,
        percentage: f32 
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
    },
}
