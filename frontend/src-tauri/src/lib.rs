mod crypto;
mod mls;
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
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                if window
                    .state::<storage::commands::DesktopState>()
                    .lock()
                    .is_err()
                {
                    eprintln!("failed to lock native storage during window close");
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            crypto::crypto_status,
            storage::commands::vault_status,
            storage::commands::session_set,
            storage::commands::session_current,
            storage::commands::session_clear,
            storage::commands::vault_backup,
            storage::commands::vault_restore,
            storage::commands::mls_initialize,
            storage::commands::mls_group_create,
            storage::commands::mls_group_add,
            storage::commands::mls_group_join,
            storage::commands::mls_encrypt,
            storage::commands::mls_process,
            storage::commands::mls_cached_application,
            storage::commands::mls_group_members,
            storage::commands::mls_remove_devices,
            storage::commands::mls_self_update
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Secure Messenger desktop");
}
