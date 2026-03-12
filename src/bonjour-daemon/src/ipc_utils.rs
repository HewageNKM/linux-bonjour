use serde::{Serialize, Deserialize};
use anyhow::Result;
use std::path::Path;
use tokio::net::UnixListener;
use tokio_util::codec::{Framed, LinesCodec};
use futures::StreamExt;
use futures::SinkExt;

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
        camera: String,
        enabled: bool
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

pub struct UdsServer {
    socket_path: String,
}

impl UdsServer {
    pub fn new(socket_path: &str) -> Self {
        Self {
            socket_path: socket_path.to_string(),
        }
    }

    pub async fn start<F, Fut>(&self, handler: F) -> Result<()>
    where
        F: Fn(DaemonRequest) -> Fut + Clone + Send + 'static,
        Fut: std::future::Future<Output = Vec<DaemonResponse>> + Send,
    {
        let path = Path::new(&self.socket_path);
        if path.exists() {
            std::fs::remove_file(path)?;
        }

        let listener = UnixListener::bind(path)?;
        
        // Ensure the socket is world-writable (0666) so the GUI/PAM can connect
        use std::os::unix::fs::PermissionsExt;
        if let Ok(metadata) = std::fs::metadata(path) {
            let mut perms = metadata.permissions();
            perms.set_mode(0o666);
            let _ = std::fs::set_permissions(path, perms);
        }

        println!("📡 UDS Server listening on: {}", self.socket_path);

        loop {
            match listener.accept().await {
                Ok((stream, _)) => {
                    let h = handler.clone();
                    tokio::spawn(async move {
                        let mut framed = Framed::new(stream, LinesCodec::new());
                        while let Some(Ok(line)) = framed.next().await {
                            if let Ok(req) = serde_json::from_str::<DaemonRequest>(&line) {
                                let responses = h(req).await;
                                for res in responses {
                                    if let Ok(res_json) = serde_json::to_string(&res) {
                                        let _ = framed.send(res_json).await;
                                    }
                                }
                            }
                        }
                    });
                }
                Err(e) => {
                    eprintln!("❌ UDS Accept error: {}", e);
                }
            }
        }
    }
}
