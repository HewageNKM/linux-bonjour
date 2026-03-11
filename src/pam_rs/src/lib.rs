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
    UpdateConfig { threshold: f32, smile_required: bool },
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(tag = "status", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DaemonResponse {
    Scanning { msg: String },
    Success { user: String },
    Failure { reason: String },
    Info { msg: String },
    Status { enabled: bool },
    IdentityList { users: Vec<String> },
    ActionSuccess { msg: String },
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

    // 2. Connect to Daemon
    let mut stream = match UnixStream::connect(SOCKET_PATH) {
        Ok(s) => s,
        Err(_) => {
            // Daemon not running, fail silently for fallback
            return PamReturnCode::AUTHINFO_UNAVAIL as libc::c_int;
        }
    };

    let _ = stream.set_read_timeout(Some(Duration::from_secs(30)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));

    // 3. Send Verify Request
    let request = DaemonRequest::Verify { user: username };
    if let Ok(req_json) = serde_json::to_string(&request) {
        if stream.write_all(format!("{}\n", req_json).as_bytes()).is_err() {
            return PamReturnCode::AUTH_ERR as libc::c_int;
        }
    } else {
        return PamReturnCode::AUTH_ERR as libc::c_int;
    }

    // 4. Read Responses (Line-delimited JSON)
    let reader = BufReader::new(stream);
    for line in reader.lines() {
        if let Ok(l) = line {
            if let Ok(resp) = serde_json::from_str::<DaemonResponse>(&l) {
                match resp {
                    DaemonResponse::Scanning { msg } => {
                        unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("🔍 Scanning: {}", msg)) };
                    },
                    DaemonResponse::Success { user } => {
                        unsafe { send_message(pamh, PAM_TEXT_INFO, &format!("✅ Welcome, {}!", user)) };
                        return PamReturnCode::SUCCESS as libc::c_int;
                    },
                    DaemonResponse::Failure { reason } => {
                        unsafe { send_message(pamh, PAM_ERROR_MSG, &format!("❌ Authentication failed: {}", reason)) };
                        return PamReturnCode::AUTH_ERR as libc::c_int;
                    },
                    DaemonResponse::Info { msg } => {
                        unsafe { send_message(pamh, PAM_TEXT_INFO, &msg) };
                    },
                    DaemonResponse::Status { .. } | 
                    DaemonResponse::IdentityList { .. } |
                    DaemonResponse::ActionSuccess { .. } => {} // Ignore in PAM
                }
            }
        }
    }

    PamReturnCode::AUTH_ERR as libc::c_int
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