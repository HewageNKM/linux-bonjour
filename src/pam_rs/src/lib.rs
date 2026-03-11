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
    Verify { user: String },
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
        ask_permission: bool,
        retry_limit: u32,
    },
    GetHardwareStatus,
    DownloadModel { name: String },
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
            
            let res = (conv_func)(1, &mut msg_ptr as *mut *const pam_sys::PamMessage as *mut *mut pam_sys::PamMessage, &mut resp_ptr, conv.data_ptr);
            
            if res == 0 && !resp_ptr.is_null() {
                let resp_str = if (*resp_ptr).resp.is_null() {
                    None
                } else {
                    Some(CStr::from_ptr((*resp_ptr).resp).to_string_lossy().into_owned())
                };

                // Cleanup
                if !(*resp_ptr).resp.is_null() {
                    libc::free((*resp_ptr).resp as *mut libc::c_void);
                }
                libc::free(resp_ptr as *mut libc::c_void);
                
                return resp_str;
            }
        }
    }
    None
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn pam_sm_authenticate(
    pamh: *const PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> libc::c_int {
    // 1. Get username
    let mut user_ptr: *const libc::c_char = ptr::null();
    let res = unsafe { pam_sys::get_user(&*pamh, &mut user_ptr, ptr::null()) };
    
    if res != PamReturnCode::SUCCESS || user_ptr.is_null() {
        return PamReturnCode::USER_UNKNOWN as libc::c_int;
    }
    
    let username = unsafe { CStr::from_ptr(user_ptr).to_string_lossy().into_owned() };

    let mut attempts = 0;
    loop {
        attempts += 1;
        
        // 2. Connect to Daemon
        let stream_result = UnixStream::connect(SOCKET_PATH);
        if stream_result.is_err() {
            return PamReturnCode::AUTHINFO_UNAVAIL as libc::c_int;
        }
        let mut stream = stream_result.unwrap();

        let _ = stream.set_read_timeout(Some(Duration::from_secs(30)));
        let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));

        // 3. Send Verify Request
        let request = DaemonRequest::Verify { user: username.clone() };
        if let Ok(req_json) = serde_json::to_string(&request) {
            let _ = stream.write_all(format!("{}\n", req_json).as_bytes());
        } else {
            return PamReturnCode::AUTH_ERR as libc::c_int;
        }

        // 4. Read Responses
        let reader = BufReader::new(stream);
        let mut success = false;
        let mut failure_reason = String::from("Unknown failure");

        for line in reader.lines() {
            if let Ok(l) = line {
                if let Ok(resp) = serde_json::from_str::<DaemonResponse>(&l) {
                    match resp {
                        DaemonResponse::Info { msg } => {
                            if msg == "CONSENT_REQUIRED" {
                                let consent_prompt = format!("🛡️ [Bonjour] Allow face ID for '{}'? (Y/n): ", username);
                                let consent = unsafe { prompt_user(pamh, &consent_prompt) };
                                if let Some(c) = consent {
                                    if c.trim().to_lowercase() == "n" || c.trim().to_lowercase() == "no" {
                                        unsafe { send_message(pamh, PAM_TEXT_INFO, "➡️ [Bonjour] Authorization denied.") };
                                        return PamReturnCode::AUTHINFO_UNAVAIL as libc::c_int;
                                    }
                                    // User said Y, we need to re-verify but SKIP the prompt this time.
                                    // Complex in the current stateless loop, but for now we proceed.
                                    unsafe { send_message(pamh, PAM_TEXT_INFO, "✅ Authorized. Opening camera...") };
                                } else {
                                    return PamReturnCode::AUTHINFO_UNAVAIL as libc::c_int;
                                }
                            } else {
                                unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("ℹ️ [Bonjour] {}", msg)) };
                            }
                        },
                        DaemonResponse::Success { user } => {
                            unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("✅ [Bonjour] Authenticated as: {}", user)) };
                            success = true;
                            break;
                        },
                        DaemonResponse::Failure { reason } => {
                            failure_reason = reason;
                            success = false;
                            break;
                        },
                        _ => {}
                    }
                }
            }
        }

        if success {
            return PamReturnCode::SUCCESS as libc::c_int;
        }

        // 5. Retry Logic
        unsafe { send_message(pamh, PAM_ERROR_MSG, &format!("❌ [Bonjour] Authentication failed: {}", failure_reason)) };
        
        if attempts >= 3 {
            unsafe { send_message(pamh, PAM_TEXT_INFO, "⚠️ [Bonjour] Max attempts reached. Falling back.") };
            return PamReturnCode::AUTH_ERR as libc::c_int;
        }

        let retry_prompt = "🔄 [Bonjour] Try face recognition again? (Y/n): ";
        let response = unsafe { prompt_user(pamh, retry_prompt) };
        
        if let Some(resp) = response {
            let resp = resp.trim().to_lowercase();
            if resp == "n" || resp == "no" {
                unsafe { send_message(pamh, PAM_TEXT_INFO, "➡️ [Bonjour] Falling back to password.") };
                return PamReturnCode::AUTHINFO_UNAVAIL as libc::c_int; // Better cleanup for fallback
            }
        } else {
            return PamReturnCode::AUTHINFO_UNAVAIL as libc::c_int;
        }
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn pam_sm_setcred(
    _pamh: *const PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> libc::c_int {
    PamReturnCode::SUCCESS as libc::c_int
}