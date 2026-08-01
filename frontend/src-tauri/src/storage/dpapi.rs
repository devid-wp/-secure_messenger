use std::ptr;

use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Cryptography::{
    CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
};

use super::StorageError;

const APP_ENTROPY: &[u8] = b"SecureMessenger.NativeVault.v1";

fn blob(bytes: &[u8]) -> CRYPT_INTEGER_BLOB {
    CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr().cast_mut(),
    }
}

fn copy_and_release(output: CRYPT_INTEGER_BLOB, clear_before_free: bool) -> Vec<u8> {
    if output.pbData.is_null() || output.cbData == 0 {
        return Vec::new();
    }
    let result =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    if clear_before_free {
        for index in 0..output.cbData as usize {
            unsafe { ptr::write_volatile(output.pbData.add(index), 0) };
        }
    }
    unsafe { LocalFree(output.pbData.cast()) };
    result
}

pub fn protect(plaintext: &[u8]) -> Result<Vec<u8>, StorageError> {
    let input = blob(plaintext);
    let entropy = blob(APP_ENTROPY);
    let mut output = CRYPT_INTEGER_BLOB::default();
    let succeeded = unsafe {
        CryptProtectData(
            &input,
            ptr::null(),
            &entropy,
            ptr::null(),
            ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if succeeded == 0 {
        return Err(StorageError::Platform(
            std::io::Error::last_os_error().to_string(),
        ));
    }
    Ok(copy_and_release(output, false))
}

pub fn unprotect(ciphertext: &[u8]) -> Result<Vec<u8>, StorageError> {
    let input = blob(ciphertext);
    let entropy = blob(APP_ENTROPY);
    let mut output = CRYPT_INTEGER_BLOB::default();
    let succeeded = unsafe {
        CryptUnprotectData(
            &input,
            ptr::null_mut(),
            &entropy,
            ptr::null(),
            ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if succeeded == 0 {
        return Err(StorageError::Platform(
            std::io::Error::last_os_error().to_string(),
        ));
    }
    Ok(copy_and_release(output, true))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dpapi_round_trip_is_bound_to_current_windows_user() {
        let plaintext = b"native vault test secret";
        let protected = protect(plaintext).unwrap();
        assert_ne!(protected, plaintext);
        assert_eq!(unprotect(&protected).unwrap(), plaintext);
    }
}
