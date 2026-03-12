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
        active_model: Option<String>,
        #[serde(default = "default_true")]
        enable_login: bool,
        #[serde(default = "default_true")]
        enable_sudo: bool,
        #[serde(default = "default_true")]
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
        enabled: bool
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
        enabled: bool,
        has_face_data: bool,
        enable_login: bool,
        enable_sudo: bool,
        enable_polkit: bool,
    },
}

fn default_true() -> bool { true }

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
        F: Fn(DaemonRequest, tokio::sync::mpsc::Sender<DaemonResponse>) -> Fut + Clone + Send + 'static,
        Fut: std::future::Future<Output = ()> + Send,
    {
        let path = Path::new(&self.socket_path);
        if path.exists() {
            // Try to connect to see if another daemon is actually running
            if tokio::net::UnixStream::connect(path).await.is_ok() {
                anyhow::bail!("Another daemon instance is already running and responding at {}", self.socket_path);
            }
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
                        let (mut writer, mut reader) = Framed::new(stream, LinesCodec::new()).split();
                        let (tx, mut rx) = tokio::sync::mpsc::channel::<DaemonResponse>(10);
                        
                        // Spawn writer task
                        let writer_handle = tokio::spawn(async move {
                            while let Some(res) = rx.recv().await {
                                if let Ok(res_json) = serde_json::to_string(&res) {
                                    if let Err(_) = writer.send(res_json).await { break; }
                                }
                            }
                        });
                        
                        while let Some(Ok(line)) = reader.next().await {
                            if let Ok(req) = serde_json::from_str::<DaemonRequest>(&line) {
                                let tx_inner = tx.clone();
                                h(req, tx_inner).await;
                            }
                        }
                        
                        drop(tx); // Close channel to terminate writer
                        let _ = writer_handle.await;
                    });
                }
                Err(e) => {
                    eprintln!("❌ UDS Accept error: {}", e);
                }
            }
        }
    }
}
