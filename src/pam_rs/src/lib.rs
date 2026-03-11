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

unsafe fn is_pam_logging_enabled() -> bool {
    let mut stream = match UnixStream::connect(SOCKET_PATH) {
        Ok(s) => s,
        Err(_) => return true,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
    if stream.write_all(b"GET_CONFIG pam_logging").is_err() {
        return true;
    }
    let mut buffer = [0; 16];
    match stream.read(&mut buffer) {
        Ok(n) if n > 0 => {
            let val = String::from_utf8_lossy(&buffer[..n]).to_lowercase();
            val.trim() == "true"
        }
        _ => true,
    }
}

unsafe fn send_message(pamh: *const PamHandle, msg_style: libc::c_int, text: &str, force: bool) {
    if !force && !is_pam_logging_enabled() {
        return;
    }
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

unsafe fn prompt_retry(pamh: *const PamHandle, text: &str) -> bool {
    let mut conv_ptr: *const libc::c_void = ptr::null();
    if pam_sys::get_item(&*pamh, pam_sys::PamItemType::CONV, &mut conv_ptr) != PamReturnCode::SUCCESS || conv_ptr.is_null() {
        return false;
    }

    let conv = &*(conv_ptr as *const pam_sys::PamConversation);
    if let Some(conv_func) = conv.conv {
        let msg_str = CString::new(text).unwrap_or_default();
        let msg = pam_sys::PamMessage {
            msg_style: 1, // PAM_PROMPT_ECHO_ON
            msg: msg_str.as_ptr(),
        };
        let mut msg_ptr = &msg as *const pam_sys::PamMessage;
        let mut resp_ptr: *mut pam_sys::PamResponse = ptr::null_mut();
        
        // FFI call
        let res = (conv_func)(1, &mut msg_ptr as *mut *const pam_sys::PamMessage as *mut *mut pam_sys::PamMessage, &mut resp_ptr, conv.data_ptr);
        
        if res == PamReturnCode::SUCCESS as libc::c_int && !resp_ptr.is_null() {
            let resp = &*resp_ptr;
            if !resp.resp.is_null() {
                let response = CStr::from_ptr(resp.resp).to_string_lossy().to_lowercase();
                let trimmed = response.trim();
                libc::free(resp.resp as *mut libc::c_void);
                libc::free(resp_ptr as *mut libc::c_void);
                // Return true ONLY if explicitly started with 'y' or is empty (default to yes if logging disabled, but here we require Y)
                return trimmed.starts_with('y') || trimmed.is_empty();
            }
            libc::free(resp_ptr as *mut libc::c_void);
        }
    }
    false
}

unsafe fn get_max_retries() -> i32 {
    let mut stream = match UnixStream::connect(SOCKET_PATH) {
        Ok(s) => s,
        Err(_) => return 2, // Default: 3 attempts total (0, 1, 2)
    };
    
    let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
    if stream.write_all(b"GET_CONFIG max_failures").is_err() {
        return 2;
    }
    
    let mut buffer = [0; 16];
    match stream.read(&mut buffer) {
        Ok(n) if n > 0 => {
            let val_str = String::from_utf8_lossy(&buffer[..n]);
            let max_f = val_str.trim().parse::<i32>().unwrap_or(3);
            if max_f < 1 { 0 } else { max_f - 1 }
        }
        _ => 2,
    }
}

unsafe fn is_system_enabled() -> bool {
    let mut stream = match UnixStream::connect(SOCKET_PATH) {
        Ok(s) => s,
        Err(_) => return true,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
    if stream.write_all(b"GET_CONFIG system_enabled").is_err() {
        return true;
    }
    let mut buffer = [0; 16];
    match stream.read(&mut buffer) {
        Ok(n) if n > 0 => {
            let val = String::from_utf8_lossy(&buffer[..n]).to_lowercase();
            val.trim() == "true"
        }
        _ => true,
    }
}

unsafe fn is_user_enrolled(username: &str) -> bool {
    let mut stream = match UnixStream::connect(SOCKET_PATH) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
    if stream.write_all(format!("HAS_DATA {}", username).as_bytes()).is_err() {
        return false;
    }
    let mut buffer = [0; 16];
    match stream.read(&mut buffer) {
        Ok(n) if n > 0 => {
            let val = String::from_utf8_lossy(&buffer[..n]).to_lowercase();
            val.trim() == "true"
        }
        _ => false,
    }
}

#[no_mangle]
pub unsafe extern "C" fn pam_sm_authenticate(
    pamh: *const PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> libc::c_int {
    // 0. Global Kill-Switch Check
    if !is_system_enabled() {
        return PamReturnCode::AUTH_ERR as libc::c_int;
    }

    // 1. Get username
    let mut user_ptr: *const libc::c_char = ptr::null();
    let res = pam_sys::get_user(&*pamh, &mut user_ptr, ptr::null());
    
    if res != PamReturnCode::SUCCESS || user_ptr.is_null() {
        return PamReturnCode::AUTH_ERR as libc::c_int;
    }
    
    let username = CStr::from_ptr(user_ptr).to_string_lossy();
    
    // 1.2 Get service name
    let mut service_ptr: *const libc::c_void = ptr::null();
    let service_res = pam_sys::get_item(&*pamh, pam_sys::PamItemType::SERVICE, &mut service_ptr);
    
    let service = if service_res == PamReturnCode::SUCCESS && !service_ptr.is_null() {
        CStr::from_ptr(service_ptr as *const libc::c_char).to_string_lossy().into_owned()
    } else {
        "unknown".to_string()
    };
    
    // 1.3 Stealth Enrollment Check (Immediate fallback if no data)
    if !is_user_enrolled(&username) {
        // Only print "No Face Data!" for non-login services to keep login screen clean
        if !service.contains("gdm") && !service.contains("login") && !service.contains("sddm") && !service.contains("lightdm") {
            send_message(pamh, PAM_TEXT_INFO, "No Face Data!", false);
        }
        return PamReturnCode::AUTH_ERR as libc::c_int;
    }

    let mut retries = 0;
    let max_retries = get_max_retries();

    loop {
        // 2. Connect to Daemon
        let mut stream = match UnixStream::connect(SOCKET_PATH) {
            Ok(s) => s,
            Err(_) => {
                // If daemon is down, fail silently to allow password fallback immediately
                return PamReturnCode::AUTHINFO_UNAVAIL as libc::c_int;
            }
        };

        // 3. Set Timeout (Increase to 60s to allow for user approval dialog)
        let _ = stream.set_read_timeout(Some(Duration::from_secs(60)));

        // 4. Send AUTH request with service info
        let request = format!("AUTH {} {}", username, service);
        if stream.write_all(request.as_bytes()).is_ok() {
            // 5. Read response (Loop for intermediate INFO messages)
            loop {
                let mut buffer = [0; 512];
                match stream.read(&mut buffer) {
                    Ok(n) if n > 0 => {
                        let response = String::from_utf8_lossy(&buffer[..n]);
                        for line in response.lines() {
                            let resp_trim = line.trim();
                            if resp_trim.starts_with("INFO: ") {
                                let instruction = &resp_trim[6..];
                                send_message(pamh, PAM_TEXT_INFO, instruction, false);
                                continue;
                            }
                            
                            if resp_trim == "SUCCESS" {
                                send_message(pamh, PAM_TEXT_INFO, "✅ Linux Bonjour: Face Recognized!", false);
                                return PamReturnCode::SUCCESS as libc::c_int;
                            } else if resp_trim == "DENIED" {
                                send_message(pamh, PAM_TEXT_INFO, "🚫 Linux Bonjour: Authorization Denied.", false);
                                return PamReturnCode::AUTH_ERR as libc::c_int;
                            } else if resp_trim == "FAILURE" {
                                // Break and allow retry prompt
                                break;
                            }
                        }
                        // Check if we got a terminal status
                        let last_line = response.lines().last().unwrap_or_default().trim();
                        if last_line == "FAILURE" || last_line == "SUCCESS" || last_line == "DENIED" { break; }
                    }
                    _ => break, // Connection closed or error
                }
            }
        }

        retries += 1;
        if retries > max_retries {
            send_message(pamh, PAM_ERROR_MSG, "❌ Max attempts reached. Falling back to password...", false);
            break;
        }

        // 6. Ask to Try Again - Improved Prompt
        if !is_pam_logging_enabled() || !prompt_retry(pamh, "\n❌ Face not recognized. Try again? [Y/n]: ") {
            break;
        }
    }

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