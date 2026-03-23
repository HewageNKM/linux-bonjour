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
    Scanning { 
        msg: String,
        #[serde(default)]
        feedback: Option<String> 
    },
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
        depth_supported: bool,
    },
    DownloadProgress { 
        name: String,
        percentage: f32 
    },
    EnrollmentFrame {
        base64_image: String,
        message: String,
        progress: f32,
        #[serde(default)]
        feedback: Option<String>
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
        depth_active: bool,
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

const PAM_PROMPT_ECHO_OFF: libc::c_int = 1;
const PAM_PROMPT_ECHO_ON: libc::c_int = 2;

unsafe fn prompt_user(pamh: *const PamHandle, text: &str, echo_on: bool) -> Option<String> {
    let mut conv_ptr: *const libc::c_void = ptr::null();
    unsafe {
        if pam_sys::get_item(&*pamh, pam_sys::PamItemType::CONV, &mut conv_ptr) != PamReturnCode::SUCCESS || conv_ptr.is_null() {
            return None;
        }

        let conv = &*(conv_ptr as *const pam_sys::PamConversation);
        if let Some(conv_func) = conv.conv {
            let msg_str = CString::new(text).unwrap_or_default();
            let msg = pam_sys::PamMessage {
                msg_style: if echo_on { PAM_PROMPT_ECHO_ON } else { PAM_PROMPT_ECHO_OFF },
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

#[derive(Debug, PartialEq)]
enum VerifyResult {
    Success,
    ConsentRequired,
    RetryableFailure(String),
    HardFailure(String),
}

#[no_mangle]
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

    // Prevent Face ID from looping when sudo/login asks for password retries
    unsafe {
        if pam_sys::getenv(&mut *pamh, "BONJOUR_ATTEMPTED").is_some() {
            // We've already tried biometric auth in this PAM session. Skip so password retry works normally.
            return PamReturnCode::IGNORE;
        }
        pam_sys::putenv(&mut *pamh, "BONJOUR_ATTEMPTED=1");
    }

    let user_cstr = CStr::from_ptr(user_ptr);
    let user = user_cstr.to_string_lossy().into_owned();

    let mut retry_limit = 3; // Default fallback
    let mut system_enabled = true;
    let mut has_face_data = true;
    let mut enable_login = true;
    let mut enable_sudo = true;
    let mut enable_polkit = true;

    if let Ok(mut stream) = UnixStream::connect(SOCKET_PATH) {
        let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
        let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
        let req_json = serde_json::to_string(&DaemonRequest::GetConfig).unwrap_or_default();
        if let Ok(_) = stream.write_all(format!("{}\n", req_json).as_bytes()) {
            let mut reader = BufReader::new(stream).lines();
            if let Some(Ok(line)) = reader.next() {
                if let Ok(DaemonResponse::Config { 
                    retry_limit: limit, 
                    enabled, 
                    has_face_data: hfd, 
                    enable_login: el, 
                    enable_sudo: es, 
                    enable_polkit: ep, 
                    .. 
                }) = serde_json::from_str(&line) {
                    retry_limit = limit;
                    system_enabled = enabled;
                    has_face_data = hfd;
                    enable_login = el;
                    enable_sudo = es;
                    enable_polkit = ep;
                }
            }
        }
    }

    // Silent fallback if disabled globally
    if !system_enabled {
        return PamReturnCode::IGNORE;
    }

    // Granular service checks
    let mut service_ptr: *const libc::c_void = ptr::null();
    let mut bypass_consent = false;
    if pam_sys::get_item(&*pamh, pam_sys::PamItemType::SERVICE, &mut service_ptr) == PamReturnCode::SUCCESS && !service_ptr.is_null() {
        let service_cstr = CStr::from_ptr(service_ptr as *const libc::c_char);
        let service = service_cstr.to_string_lossy().into_owned().to_lowercase();
        
        // Skip if service specific toggle is OFF
        if ((service == "sudo" || service == "sudo-i" || service == "su") && !enable_sudo) || 
           ((service == "login" || service.contains("gdm") || service.contains("sddm") || service.contains("lightdm") || service.contains("dm")) && !enable_login) ||
           ((service.starts_with("polkit") || service == "pkexec") && !enable_polkit) {
            return PamReturnCode::IGNORE;
        }

        // Ignore consent on pre-login display managers and TTY login
        if service.contains("gdm") || service.contains("sddm") || service.contains("lightdm") || service.contains("dm") || service == "login" {
            bypass_consent = true;
        }
    }

    // Check enrollment status
    if !has_face_data {
        unsafe { send_message(pamh, PAM_TEXT_INFO, "ℹ️ [Bonjour] Not enrolled. Type password to login."); }
        // Fallback to password prompt immediately
        return PamReturnCode::IGNORE;
    }

    // On first pass, use the service default for bypass_consent.
    // This allows Zero-Touch if ask_permission=false in the daemon.
    match perform_verify(pamh, &user, bypass_consent) {
        VerifyResult::Success => return PamReturnCode::SUCCESS,
        VerifyResult::ConsentRequired | VerifyResult::RetryableFailure(_) | VerifyResult::HardFailure(_) => {
            // Proceed to the unified prompt loop
        }
    }

    for attempt in 1..=retry_limit {
        let prompt_text = format!("[Bonjour] Type password or hit Enter to (retry) scan [Attempt {}/{}]: ", attempt, retry_limit);

        if let Some(input) = unsafe { prompt_user(pamh, &prompt_text, false) } {
            let input = input.trim();
            if input.is_empty() {
                // User hit Enter -> Action: Force Biometric Scan (Treat as consent)
                match perform_verify(pamh, &user, true) {
                    VerifyResult::Success => return PamReturnCode::SUCCESS,
                    VerifyResult::HardFailure(reason) => {
                        unsafe { send_message(pamh, PAM_ERROR_MSG, &format!("❌ [Bonjour] Critical failure: {}", reason)); }
                        return PamReturnCode::IGNORE;
                    },
                    VerifyResult::RetryableFailure(reason) => {
                        unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("   - ❌ Failed: {}", reason)); }
                    },
                    VerifyResult::ConsentRequired => {
                        // Should not happen if bypass_consent is true
                    }
                }
            } else {
                // User typed something -> Action: Password Fallback
                unsafe {
                    let authtok = CString::new(input).unwrap_or_default();
                    if pam_sys::set_item(&mut *pamh, pam_sys::PamItemType::AUTHTOK, &*(authtok.as_ptr() as *const libc::c_void)) == PamReturnCode::SUCCESS {
                        return PamReturnCode::IGNORE;
                    }
                }
                break;
            }
        } else {
            break;
        }
    }

    unsafe { send_message(pamh, PAM_TEXT_INFO, "⚠️ [Bonjour] Biometric failure. Falling back to password."); }
    PamReturnCode::IGNORE
}

fn perform_verify(pamh: *mut PamHandle, user: &str, bypass_consent: bool) -> VerifyResult {
    let mut retry_count = 0;
    let max_retries = 5;
    let mut last_stream = None;

    while retry_count < max_retries {
        match UnixStream::connect(SOCKET_PATH) {
            Ok(stream) => {
                last_stream = Some(stream);
                break;
            }
            Err(_) => {
                retry_count += 1;
                if retry_count < max_retries {
                    std::thread::sleep(Duration::from_secs(1));
                }
            }
        }
    }

    match last_stream {
        Some(mut stream) => {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(30)));
            let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
            
            let request = DaemonRequest::Verify { 
                user: user.to_string(), 
                bypass_consent 
            };
            let req_json = serde_json::to_string(&request).unwrap_or_default();
            if let Err(_) = stream.write_all(format!("{}\n", req_json).as_bytes()) {
                return VerifyResult::HardFailure("Connection error writing to socket.".to_string());
            }

            let mut reader = BufReader::new(stream).lines();
            while let Some(Ok(line)) = reader.next() {
                if let Ok(resp) = serde_json::from_str::<DaemonResponse>(&line) {
                    match resp {
                        DaemonResponse::Scanning { msg, feedback } => {
                            if let Some(f) = feedback {
                                unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("   - ⚠️ {}", f)); }
                            } else {
                                unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("   - {}", msg)); }
                            }
                        },
                        DaemonResponse::Info { msg } => {
                            if msg == "CONSENT_REQUIRED" {
                                return VerifyResult::ConsentRequired;
                            } else {
                                unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("ℹ️ [Bonjour] {}", msg)); }
                            }
                        },
                        DaemonResponse::Success { user: _ } => {
                            unsafe { send_message(pamh, PAM_TEXT_INFO, "✅ [Bonjour] Authenticated."); }
                            return VerifyResult::Success;
                        },
                        DaemonResponse::Failure { reason } => {
                            // Immediately fail without retry if the system is disabled
                            if reason.contains("System is globally disabled") {
                                return VerifyResult::HardFailure(reason);
                            }
                            return VerifyResult::RetryableFailure(reason);
                        },
                        _ => {}
                    }
                }
            }
            VerifyResult::HardFailure("Unexpected end of stream from daemon.".to_string())
        },
        None => VerifyResult::HardFailure("Daemon unreachable after retries.".to_string())
    }
}

#[no_mangle]
pub unsafe extern "C" fn pam_sm_setcred(
    _pamh: *mut PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> PamReturnCode {
    PamReturnCode::SUCCESS
}