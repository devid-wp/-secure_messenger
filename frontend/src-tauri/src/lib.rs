mod crypto;
mod storage;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let app_data_dir = app.path().app_data_dir()?;
            app.manage(storage::commands::DesktopState::new(&app_data_dir)?);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            crypto::crypto_status,
            storage::commands::vault_status,
            storage::commands::session_set,
            storage::commands::session_current,
            storage::commands::session_clear
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Secure Messenger desktop");
}
