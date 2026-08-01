use std::path::Path;

use serde::Serialize;
use tauri::State;
use zeroize::{Zeroize, ZeroizeOnDrop};

use super::{NativeSession, NativeSessionStore, NativeVault, StorageError, StoragePaths};

pub struct DesktopState {
    vault: NativeVault,
    sessions: NativeSessionStore,
}

impl DesktopState {
    pub fn new(app_data_dir: &Path) -> Result<Self, StorageError> {
        Ok(Self {
            vault: NativeVault::new(StoragePaths::new(app_data_dir)?),
            sessions: NativeSessionStore::default(),
        })
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VaultStatus {
    unlocked: bool,
    session_available: bool,
}

#[derive(Serialize, Zeroize, ZeroizeOnDrop)]
pub struct SessionSnapshot {
    token: String,
    login: String,
}

fn command_error(error: StorageError) -> String {
    error.to_string()
}

#[tauri::command]
pub fn vault_status(state: State<'_, DesktopState>) -> Result<VaultStatus, String> {
    Ok(VaultStatus {
        unlocked: state.vault.is_unlocked().map_err(command_error)?,
        session_available: state.sessions.current().map_err(command_error)?.is_some(),
    })
}

#[tauri::command]
pub fn session_set(
    state: State<'_, DesktopState>,
    token: String,
    login: String,
) -> Result<(), String> {
    state.vault.unlock().map_err(command_error)?;
    state
        .sessions
        .replace(NativeSession::new(token, login).map_err(command_error)?)
        .map_err(command_error)
}

#[tauri::command]
pub fn session_current(state: State<'_, DesktopState>) -> Result<Option<SessionSnapshot>, String> {
    Ok(state
        .sessions
        .current()
        .map_err(command_error)?
        .map(|session| SessionSnapshot {
            token: session.token().to_owned(),
            login: session.login().to_owned(),
        }))
}

#[tauri::command]
pub fn session_clear(state: State<'_, DesktopState>) -> Result<(), String> {
    state.sessions.clear().map_err(command_error)?;
    state.vault.lock().map_err(command_error)
}
