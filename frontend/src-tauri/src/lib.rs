mod crypto;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![crypto::crypto_status])
        .run(tauri::generate_context!())
        .expect("failed to run Secure Messenger desktop");
}
