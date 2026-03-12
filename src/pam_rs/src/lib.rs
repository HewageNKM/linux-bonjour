use pam_sys::{PamHandle, PamReturnCode};
use std::ffi::{CStr, CString};
use std::io::{Write, BufRead, BufReader};
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::ptr;
use serde::{Serialize, Deserialize};

const SOCKET_PATH: &str = "/run/linux-bonjour/daemon.sock";

// PAM Message Styles (Standard)
const PAM_ERROR_MSG: libc::c_int = 3;
const PAM_TEXT_INFO: libc::c_int = 4;

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

unsafe fn send_message(pamh: *const PamHandle, msg_style: libc::c_int, text: &str) {
    let mut conv_ptr: *const libc::c_void = ptr::null();
    unsafe {
        if pam_sys::get_item(&*pamh, pam_sys::PamItemType::CONV, &mut conv_ptr) != PamReturnCode::SUCCESS || conv_ptr.is_null() {
            return;
        }

        let conv = &*(conv_ptr as *const pam_sys::PamConversation);
        if let Some(conv_func) = conv.conv {
            let msg_str = CString::new(text).unwrap_or_default();
            let msg = pam_sys::PamMessage {
                msg_style: msg_style,
                msg: msg_str.as_ptr(),
            };
            let mut msg_ptr = &msg as *const pam_sys::PamMessage;
            let mut resp_ptr: *mut pam_sys::PamResponse = ptr::null_mut();
            
            (conv_func)(1, &mut msg_ptr as *mut *const pam_sys::PamMessage as *mut *mut pam_sys::PamMessage, &mut resp_ptr, conv.data_ptr);
            
            if !resp_ptr.is_null() {
                if !(*resp_ptr).resp.is_null() {
                    libc::free((*resp_ptr).resp as *mut libc::c_void);
                }
                libc::free(resp_ptr as *mut libc::c_void);
            }
        }
    }
}

const PAM_PROMPT_ECHO_ON: libc::c_int = 2;

unsafe fn prompt_user(pamh: *const PamHandle, text: &str) -> Option<String> {
    let mut conv_ptr: *const libc::c_void = ptr::null();
    unsafe {
        if pam_sys::get_item(&*pamh, pam_sys::PamItemType::CONV, &mut conv_ptr) != PamReturnCode::SUCCESS || conv_ptr.is_null() {
            return None;
        }

        let conv = &*(conv_ptr as *const pam_sys::PamConversation);
        if let Some(conv_func) = conv.conv {
            let msg_str = CString::new(text).unwrap_or_default();
            let msg = pam_sys::PamMessage {
                msg_style: PAM_PROMPT_ECHO_ON,
                msg: msg_str.as_ptr(),
            };
            let mut msg_ptr = &msg as *const pam_sys::PamMessage;
            let mut resp_ptr: *mut pam_sys::PamResponse = ptr::null_mut();
            
            (conv_func)(1, &mut msg_ptr as *mut *const pam_sys::PamMessage as *mut *mut pam_sys::PamMessage, &mut resp_ptr, conv.data_ptr);
            
            if !resp_ptr.is_null() {
                let resp_str = if !(*resp_ptr).resp.is_null() {
                    let c_str = CStr::from_ptr((*resp_ptr).resp);
                    let s = c_str.to_string_lossy().into_owned();
                    libc::free((*resp_ptr).resp as *mut libc::c_void);
                    Some(s)
                } else {
                    None
                };
                libc::free(resp_ptr as *mut libc::c_void);
                return resp_str;
            }
        }
    }
    None
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn pam_sm_authenticate(
    pamh: *mut PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> PamReturnCode {
    let mut user_ptr: *const libc::c_char = ptr::null();
    if pam_sys::get_user(&*pamh, &mut user_ptr, ptr::null()) != PamReturnCode::SUCCESS || user_ptr.is_null() {
        return PamReturnCode::USER_UNKNOWN;
    }

    let user_cstr = CStr::from_ptr(user_ptr);
    let user = user_cstr.to_string_lossy().into_owned();

    let mut bypass_consent = false;
    let mut service_ptr: *const libc::c_void = ptr::null();
    if pam_sys::get_item(&*pamh, pam_sys::PamItemType::SERVICE, &mut service_ptr) == PamReturnCode::SUCCESS && !service_ptr.is_null() {
        let service_cstr = CStr::from_ptr(service_ptr as *const libc::c_char);
        let service = service_cstr.to_string_lossy().into_owned().to_lowercase();
        // Ignore consent on pre-login display managers and TTY login
        if service.contains("gdm") || service.contains("sddm") || service.contains("lightdm") || service.contains("dm") || service == "login" {
            bypass_consent = true;
        }
    }

    let mut retry_limit = 3; // Default fallback
    if let Ok(mut stream) = UnixStream::connect(SOCKET_PATH) {
        let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
        let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
        let req_json = serde_json::to_string(&DaemonRequest::GetConfig).unwrap_or_default();
        if let Ok(_) = stream.write_all(format!("{}\n", req_json).as_bytes()) {
            let mut reader = BufReader::new(stream).lines();
            if let Some(Ok(line)) = reader.next() {
                if let Ok(DaemonResponse::Config { retry_limit: limit, .. }) = serde_json::from_str(&line) {
                    retry_limit = limit;
                }
            }
        }
    }

    match perform_verify(pamh, &user, bypass_consent, 1, retry_limit) {
        PamReturnCode::SUCCESS => PamReturnCode::SUCCESS,
        _ => PamReturnCode::AUTH_ERR,
    }
}

fn perform_verify(pamh: *mut PamHandle, user: &str, bypass_consent: bool, attempt: u32, max_attempts: u32) -> PamReturnCode {
    match UnixStream::connect(SOCKET_PATH) {
        Ok(mut stream) => {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(30)));
            let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
            
            let request = DaemonRequest::Verify { 
                user: user.to_string(), 
                bypass_consent 
            };
            let req_json = serde_json::to_string(&request).unwrap_or_default();
            if let Err(_) = stream.write_all(format!("{}\n", req_json).as_bytes()) {
                unsafe { send_message(pamh, PAM_ERROR_MSG, "❌ [Bonjour] Connection error."); }
                return PamReturnCode::AUTH_ERR;
            }

            let mut reader = BufReader::new(stream).lines();
            while let Some(Ok(line)) = reader.next() {
                if let Ok(resp) = serde_json::from_str::<DaemonResponse>(&line) {
                    match resp {
                        DaemonResponse::Scanning { msg } => {
                            unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("📸 [Bonjour] (Attempt {}/{}) {}", attempt, max_attempts, msg)); }
                        },
                        DaemonResponse::Info { msg } => {
                            if msg == "CONSENT_REQUIRED" {
                                let prompt = "🔄 [Bonjour] Press Enter to confirm face unlock...";
                                unsafe {
                                    if prompt_user(pamh, prompt).is_some() {
                                        // User consented (pressed enter), retry with bypass
                                        return perform_verify(pamh, user, true, attempt, max_attempts);
                                    } else {
                                        return PamReturnCode::AUTH_ERR;
                                    }
                                }
                            } else {
                                unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("ℹ️ [Bonjour] {}", msg)); }
                            }
                        },
                        DaemonResponse::Success { user: _ } => {
                            unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("✅ [Bonjour] Authenticated as: {}", user)); }
                            return PamReturnCode::SUCCESS;
                        },
                        DaemonResponse::Failure { reason } => {
                            unsafe { send_message(pamh, PAM_ERROR_MSG, &format!("❌ [Bonjour] Authentication failed: {}", reason)); }
                            
                            // Immediately fail without retry if the system is disabled
                            if reason.contains("System is globally disabled") {
                                return PamReturnCode::AUTHINFO_UNAVAIL;
                            }

                            if attempt >= max_attempts {
                                unsafe { send_message(pamh, PAM_ERROR_MSG, "❌ [Bonjour] Maximum attempts reached."); }
                                unsafe { send_message(pamh, PAM_TEXT_INFO, "⚠️ [Bonjour] Biometric fallback. Please use system password."); }
                                return PamReturnCode::AUTHINFO_UNAVAIL;
                            }

                            // Ask for retry
                            let prompt = format!("🔄 [Bonjour] Face failure. Try again? (yes/no): ");
                            unsafe {
                                if let Some(r) = prompt_user(pamh, &prompt) {
                                    if !r.trim().to_lowercase().starts_with('n') {
                                        return perform_verify(pamh, user, false, attempt + 1, max_attempts);
                                    } else {
                                        unsafe { send_message(pamh, PAM_TEXT_INFO, "⚠️ [Bonjour] Biometric fallback. Please use system password."); }
                                    }
                                } else {
                                    unsafe { send_message(pamh, PAM_TEXT_INFO, "⚠️ [Bonjour] Biometric fallback. Please use system password."); }
                                }
                            }
                            // Return AUTHINFO_UNAVAIL to indicate biometric failure so PAM moves on
                            return PamReturnCode::AUTHINFO_UNAVAIL;
                        },
                        _ => {}
                    }
                }
            }
            PamReturnCode::AUTH_ERR
        },
        Err(_) => {
            unsafe { send_message(pamh, PAM_ERROR_MSG, "❌ [Bonjour] Daemon unreachable."); }
            PamReturnCode::AUTH_ERR
        }
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn pam_sm_setcred(
    _pamh: *mut PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> PamReturnCode {
    PamReturnCode::SUCCESS
}