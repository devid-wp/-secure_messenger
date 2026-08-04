use std::path::Path;

use serde::Serialize;
use tauri::State;
use tls_codec::Serialize as TlsSerialize;
use zeroize::{Zeroize, ZeroizeOnDrop};

use super::{
    DeviceKeyStore, MlsStateStore, NativeSession, NativeSessionStore, NativeVault, StorageError,
    StoragePaths,
};
use crate::mls::{self, DeviceSignatureKey};

pub struct DesktopState {
    paths: StoragePaths,
    vault: NativeVault,
    sessions: NativeSessionStore,
    #[allow(dead_code)]
    mls_state: MlsStateStore,
}

impl DesktopState {
    pub fn new(app_data_dir: &Path) -> Result<Self, StorageError> {
        let paths = StoragePaths::new(app_data_dir)?;
        Ok(Self {
            paths: paths.clone(),
            vault: NativeVault::new(paths.clone()),
            sessions: NativeSessionStore::new(paths.clone())?,
            mls_state: MlsStateStore::new(paths),
        })
    }

    pub fn export_backup(&self, destination: &Path) -> Result<String, StorageError> {
        super::backup::export(&self.paths, destination)
    }

    pub fn restore_backup(&self, source: &Path, recovery_key: &str) -> Result<(), StorageError> {
        super::backup::restore(&self.paths, source, recovery_key)
    }

    pub fn lock(&self) -> Result<(), StorageError> {
        self.sessions.clear()?;
        self.vault.lock()
    }

    pub fn mls_available(&self) -> bool {
        DeviceKeyStore::new(self.paths.clone())
            .load()
            .map(|key| key.is_some())
            .unwrap_or(false)
            && self.mls_state.load().map(|state| state.is_some()).unwrap_or(false)
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
    refresh_token: String,
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
    refresh_token: String,
    login: String,
) -> Result<(), String> {
    state.vault.unlock().map_err(command_error)?;
    state
        .sessions
        .replace(NativeSession::new(refresh_token, login).map_err(command_error)?)
        .map_err(command_error)
}

#[tauri::command]
pub fn session_current(state: State<'_, DesktopState>) -> Result<Option<SessionSnapshot>, String> {
    Ok(state
        .sessions
        .current()
        .map_err(command_error)?
        .map(|session| SessionSnapshot {
            refresh_token: session.refresh_token().to_owned(),
            login: session.login().to_owned(),
        }))
}

#[tauri::command]
pub fn session_clear(state: State<'_, DesktopState>) -> Result<(), String> {
    state.lock().map_err(command_error)
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MlsBootstrap {
    identity_key: Vec<u8>,
    fingerprint: String,
    cipher_suite: u16,
    key_packages: Vec<Vec<u8>>,
}

#[tauri::command]
pub fn vault_backup(
    state: State<'_, DesktopState>,
    destination: String,
) -> Result<String, String> {
    state.export_backup(Path::new(&destination)).map_err(command_error)
}

#[tauri::command]
pub fn vault_restore(
    state: State<'_, DesktopState>,
    source: String,
    recovery_key: String,
) -> Result<(), String> {
    state
        .restore_backup(Path::new(&source), &recovery_key)
        .map_err(command_error)
}

#[tauri::command]
pub fn mls_initialize(
    state: State<'_, DesktopState>,
    device_id: String,
    package_count: u8,
) -> Result<MlsBootstrap, String> {
    if device_id.is_empty() || package_count > 100 {
        return Err("invalid MLS initialization parameters".into());
    }

    state.vault.unlock().map_err(command_error)?;
    let device_key = DeviceSignatureKey::load_or_create(&DeviceKeyStore::new(state.paths.clone()))
        .map_err(command_error)?;
    let provider = mls::load_provider(&state.mls_state).map_err(command_error)?;
    let mut key_packages = Vec::with_capacity(package_count as usize);
    for _ in 0..package_count {
        let bundle = device_key
            .generate_key_package(&provider, device_id.as_bytes().to_vec())?;
        key_packages.push(
            bundle
                .key_package()
                .tls_serialize_detached()
                .map_err(|_| "failed to serialize MLS KeyPackage")?,
        );
    }
    mls::save_provider(&provider, &state.mls_state).map_err(command_error)?;
    Ok(MlsBootstrap {
        identity_key: device_key.public_key_bytes(),
        fingerprint: device_key.fingerprint(),
        cipher_suite: mls::CIPHERSUITE_ID,
        key_packages,
    })
}

#[cfg(test)]
mod tests {
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    #[test]
    fn locking_desktop_state_clears_session_and_master_key() {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("secure-messenger-app-state-{suffix}"));
        let state = DesktopState::new(&root).unwrap();
        state.vault.unlock().unwrap();
        state
            .sessions
            .replace(NativeSession::new("token".into(), "alice".into()).unwrap())
            .unwrap();
        state.lock().unwrap();
        assert!(!state.vault.is_unlocked().unwrap());
        assert!(state.sessions.current().unwrap().is_none());
        std::fs::remove_dir_all(root).unwrap();
    }
}
