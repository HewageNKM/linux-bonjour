mod ipc;

use ipc::{DaemonRequest, DaemonResponse};
use tokio::net::UnixStream;
use tokio::io::{AsyncWriteExt, BufReader, AsyncBufReadExt};
use tauri::{AppHandle, Emitter};

const SOCKET_PATH: &str = "/run/linux-bonjour/daemon.sock";

#[tauri::command]
async fn run_biometric_command(app: AppHandle, cmd: String, user: String) -> Result<(), String> {
    let request = match cmd.as_str() {
        "VERIFY" => DaemonRequest::Verify { user },
        "ENROLL" => DaemonRequest::Enroll { user },
        _ => return Err("Invalid command".to_string()),
    };

    let mut stream = UnixStream::connect(SOCKET_PATH).await.map_err(|e| format!("Daemon connection failed: {}", e))?;
    
    let req_json = serde_json::to_string(&request).map_err(|e| e.to_string())?;
    stream.write_all(format!("{}\n", req_json).as_bytes()).await.map_err(|e| e.to_string())?;

    let mut reader = BufReader::new(stream).lines();

    while let Ok(Some(line)) = reader.next_line().await {
        if let Ok(resp) = serde_json::from_str::<DaemonResponse>(&line) {
            // Emit event to frontend
            let _ = app.emit("biometric-status", resp.clone());
            
            // Terminal conditions
            match resp {
                DaemonResponse::Success { .. } | DaemonResponse::Failure { .. } => break,
                _ => {}
            }
        }
    }

    Ok(())
}

#[tauri::command]
async fn toggle_system(enabled: bool) -> Result<(), String> {
    let mut stream = UnixStream::connect(SOCKET_PATH).await.map_err(|e| format!("Daemon connection failed: {}", e))?;
    let request = DaemonRequest::SetEnabled { enabled };
    let req_json = serde_json::to_string(&request).map_err(|e| e.to_string())?;
    stream.write_all(format!("{}\n", req_json).as_bytes()).await.map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
async fn get_system_status() -> Result<DaemonResponse, String> {
    let mut stream = UnixStream::connect(SOCKET_PATH).await.map_err(|e| format!("Daemon connection failed: {}", e))?;
    let request = DaemonRequest::GetStatus;
    let req_json = serde_json::to_string(&request).map_err(|e| e.to_string())?;
    stream.write_all(format!("{}\n", req_json).as_bytes()).await.map_err(|e| e.to_string())?;
    
    let mut reader = BufReader::new(stream).lines();
    if let Ok(Some(line)) = reader.next_line().await {
        let resp = serde_json::from_str::<DaemonResponse>(&line).map_err(|e| e.to_string())?;
        return Ok(resp);
    }
    Err("Failed to get status from daemon".to_string())
}

#[tauri::command]
async fn get_journal_logs() -> Result<String, String> {
    let output = std::process::Command::new("journalctl")
        .args(["-u", "linux-bonjour", "-n", "100", "--no-pager"])
        .output()
        .map_err(|e| e.to_string())?;
    
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

#[tauri::command]
async fn list_identities() -> Result<DaemonResponse, String> {
    let mut stream = UnixStream::connect(SOCKET_PATH).await.map_err(|e| format!("Daemon connection failed: {}", e))?;
    let request = DaemonRequest::ListIdentities;
    let req_json = serde_json::to_string(&request).map_err(|e| e.to_string())?;
    stream.write_all(format!("{}\n", req_json).as_bytes()).await.map_err(|e| e.to_string())?;
    
    let mut reader = BufReader::new(stream).lines();
    if let Ok(Some(line)) = reader.next_line().await {
        let resp = serde_json::from_str::<DaemonResponse>(&line).map_err(|e| e.to_string())?;
        return Ok(resp);
    }
    Err("Failed to get identities from daemon".to_string())
}

#[tauri::command]
async fn delete_identity(user: String) -> Result<DaemonResponse, String> {
    let mut stream = UnixStream::connect(SOCKET_PATH).await.map_err(|e| format!("Daemon connection failed: {}", e))?;
    let request = DaemonRequest::DeleteIdentity { user };
    let req_json = serde_json::to_string(&request).map_err(|e| e.to_string())?;
    stream.write_all(format!("{}\n", req_json).as_bytes()).await.map_err(|e| e.to_string())?;
    
    let mut reader = BufReader::new(stream).lines();
    if let Ok(Some(line)) = reader.next_line().await {
        let resp = serde_json::from_str::<DaemonResponse>(&line).map_err(|e| e.to_string())?;
        return Ok(resp);
    }
    Err("Failed to delete identity".to_string())
}

#[tauri::command]
async fn update_config(threshold: f32, smile_required: bool, autocapture: bool, liveness_enabled: bool) -> Result<DaemonResponse, String> {
    let mut stream = UnixStream::connect(SOCKET_PATH).await.map_err(|e| format!("Daemon connection failed: {}", e))?;
    let request = DaemonRequest::UpdateConfig { threshold, smile_required, autocapture, liveness_enabled };
    let req_json = serde_json::to_string(&request).map_err(|e| e.to_string())?;
    stream.write_all(format!("{}\n", req_json).as_bytes()).await.map_err(|e| e.to_string())?;
    
    let mut reader = BufReader::new(stream).lines();
    if let Ok(Some(line)) = reader.next_line().await {
        let resp = serde_json::from_str::<DaemonResponse>(&line).map_err(|e| e.to_string())?;
        return Ok(resp);
    }
    Err("Failed to update config".to_string())
}

#[tauri::command]
async fn get_hardware_status() -> Result<DaemonResponse, String> {
    let mut stream = UnixStream::connect(SOCKET_PATH).await.map_err(|e| format!("Daemon connection failed: {}", e))?;
    let request = DaemonRequest::GetHardwareStatus;
    let req_json = serde_json::to_string(&request).map_err(|e| e.to_string())?;
    stream.write_all(format!("{}\n", req_json).as_bytes()).await.map_err(|e| e.to_string())?;
    
    let mut reader = BufReader::new(stream).lines();
    if let Ok(Some(line)) = reader.next_line().await {
        let resp = serde_json::from_str::<DaemonResponse>(&line).map_err(|e| e.to_string())?;
        return Ok(resp);
    }
    Err("Failed to get hardware status".to_string())
}

#[tauri::command]
async fn download_model(name: String) -> Result<DaemonResponse, String> {
    let mut stream = UnixStream::connect(SOCKET_PATH).await.map_err(|e| format!("Daemon connection failed: {}", e))?;
    let request = DaemonRequest::DownloadModel { name };
    let req_json = serde_json::to_string(&request).map_err(|e| e.to_string())?;
    stream.write_all(format!("{}\n", req_json).as_bytes()).await.map_err(|e| e.to_string())?;
    
    let mut reader = BufReader::new(stream).lines();
    if let Ok(Some(line)) = reader.next_line().await {
        let resp = serde_json::from_str::<DaemonResponse>(&line).map_err(|e| e.to_string())?;
        return Ok(resp);
    }
    Err("Failed to trigger model download".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            run_biometric_command,
            toggle_system,
            get_system_status,
            list_identities,
            delete_identity,
            update_config,
            get_journal_logs,
            get_hardware_status,
            download_model
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
