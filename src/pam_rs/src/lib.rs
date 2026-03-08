use pam_sys::{PamHandle, PamReturnCode};
use std::ffi::{CStr, CString};
use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::ptr;

const SOCKET_PATH: &str = "/run/linux-bonjour.sock";

// PAM Message Styles (Standard)
const PAM_ERROR_MSG: libc::c_int = 3;
const PAM_TEXT_INFO: libc::c_int = 4;

unsafe fn send_message(pamh: *const PamHandle, msg_style: libc::c_int, text: &str) {
    let mut conv_ptr: *const libc::c_void = ptr::null();
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
        
        // FFI call expects *mut *mut PamMessage
        (conv_func)(1, &mut msg_ptr as *mut *const pam_sys::PamMessage as *mut *mut pam_sys::PamMessage, &mut resp_ptr, conv.data_ptr);
        
        if !resp_ptr.is_null() {
            libc::free(resp_ptr as *mut libc::c_void);
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn pam_sm_authenticate(
    pamh: *const PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> libc::c_int {
    // 1. Get username
    let mut user_ptr: *const libc::c_char = ptr::null();
    let res = pam_sys::get_user(&*pamh, &mut user_ptr, ptr::null());
    
    if res != PamReturnCode::SUCCESS || user_ptr.is_null() {
        return PamReturnCode::AUTH_ERR as libc::c_int;
    }
    
    let username = CStr::from_ptr(user_ptr).to_string_lossy();
    
    // Provide visual feedback for terminal/lock screen
    send_message(pamh, PAM_TEXT_INFO, &format!("🛡️ Linux Bonjour: Scanning for {}...", username));

    // 2. Connect to Daemon
    let mut stream = match UnixStream::connect(SOCKET_PATH) {
        Ok(s) => s,
        Err(_) => {
            send_message(pamh, PAM_ERROR_MSG, "❌ Linux Bonjour: Daemon not responding.");
            return PamReturnCode::AUTHINFO_UNAVAIL as libc::c_int;
        }
    };

    // 3. Set Timeout
    if stream.set_read_timeout(Some(Duration::from_secs(5))).is_err() {
        return PamReturnCode::AUTH_ERR as libc::c_int;
    }

    // 4. Send AUTH request
    let request = format!("AUTH {}", username);
    if stream.write_all(request.as_bytes()).is_err() {
        return PamReturnCode::AUTH_ERR as libc::c_int;
    }

    // 5. Read response
    let mut buffer = [0; 128];
    match stream.read(&mut buffer) {
        Ok(n) if n > 0 => {
            let response = String::from_utf8_lossy(&buffer[..n]);
            if response.trim() == "SUCCESS" {
                send_message(pamh, PAM_TEXT_INFO, "✅ Linux Bonjour: Face Recognized!");
                return PamReturnCode::SUCCESS as libc::c_int;
            }
        }
        _ => {}
    }

    send_message(pamh, PAM_ERROR_MSG, "❌ Linux Bonjour: Recognition Failed.");
    PamReturnCode::AUTH_ERR as libc::c_int
}

#[no_mangle]
pub unsafe extern "C" fn pam_sm_setcred(
    _pamh: *const PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> libc::c_int {
    PamReturnCode::SUCCESS as libc::c_int
}
