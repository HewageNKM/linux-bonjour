use pam_sys::{PamHandle, PamReturnCode};
use std::ffi::{CStr, CString};
use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::ptr;

const SOCKET_PATH: &str = "/run/linux-bonjour.sock";

#[no_mangle]
pub unsafe extern "C" fn pam_sm_authenticate(
    pamh: *const PamHandle,
    _flags: libc::c_int,
    _argc: libc::c_int,
    _argv: *const *const libc::c_char,
) -> libc::c_int {
    // 1. Get username
    let mut user_ptr: *const libc::c_char = ptr::null();
    // In pam-sys 0.5.6, get_user is in the 'wrapped' or re-exported at root
    let res = pam_sys::get_user(&*pamh, &mut user_ptr, ptr::null());
    
    if res != PamReturnCode::SUCCESS || user_ptr.is_null() {
        return PamReturnCode::AUTH_ERR as libc::c_int;
    }
    
    let username = CStr::from_ptr(user_ptr).to_string_lossy();

    // 2. Connect to Daemon
    let mut stream = match UnixStream::connect(SOCKET_PATH) {
        Ok(s) => s,
        Err(_) => return PamReturnCode::AUTH_ERR as libc::c_int,
    };

    // 3. Set Timeout
    if stream.set_read_timeout(Some(Duration::from_secs(2))).is_err() {
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
                return PamReturnCode::SUCCESS as libc::c_int;
            }
        }
        _ => {}
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
