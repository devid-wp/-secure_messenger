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

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MlsGroupState {
    group_id: String,
    epoch: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MlsAddResult {
    commit: Vec<u8>,
    welcome: Vec<u8>,
    epoch: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MlsCiphertext {
    ciphertext: Vec<u8>,
    epoch: u64,
}

#[derive(Serialize)]
pub struct MlsCommitResult {
    commit: Vec<u8>,
    epoch: u64,
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum MlsProcessResult {
    Application { plaintext: Vec<u8>, epoch: u64 },
    Commit { epoch: u64 },
    Proposal { epoch: u64 },
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

fn native_mls(state: &DesktopState) -> Result<(DeviceSignatureKey, openmls_rust_crypto::OpenMlsRustCrypto), String> {
    state.vault.unlock().map_err(command_error)?;
    let key = DeviceSignatureKey::load_or_create(&DeviceKeyStore::new(state.paths.clone()))
        .map_err(command_error)?;
    let provider = mls::load_provider(&state.mls_state).map_err(command_error)?;
    Ok((key, provider))
}

#[tauri::command]
pub fn mls_group_create(state: State<'_, DesktopState>, device_id: String, chat_id: String) -> Result<MlsGroupState, String> {
    let (key, provider) = native_mls(&state)?;
    let epoch = mls::create_group(&provider, &key, &device_id, &chat_id)?;
    mls::save_provider(&provider, &state.mls_state).map_err(command_error)?;
    Ok(MlsGroupState { group_id: String::from_utf8_lossy(mls::group_id(&chat_id).as_slice()).into_owned(), epoch })
}

#[tauri::command]
pub fn mls_group_add(state: State<'_, DesktopState>, chat_id: String, key_packages: Vec<Vec<u8>>) -> Result<MlsAddResult, String> {
    if key_packages.is_empty() { return Err("at least one KeyPackage is required".into()); }
    let (key, provider) = native_mls(&state)?;
    let output = mls::add_members(&provider, &key, &chat_id, &key_packages)?;
    mls::save_provider(&provider, &state.mls_state).map_err(command_error)?;
    Ok(MlsAddResult { commit: output.commit, welcome: output.welcome, epoch: output.epoch })
}

#[tauri::command]
pub fn mls_group_join(state: State<'_, DesktopState>, welcome: Vec<u8>) -> Result<MlsGroupState, String> {
    let (_, provider) = native_mls(&state)?;
    let (group_id, epoch) = mls::join_group(&provider, &welcome)?;
    mls::save_provider(&provider, &state.mls_state).map_err(command_error)?;
    Ok(MlsGroupState { group_id, epoch })
}

#[tauri::command]
pub fn mls_encrypt(state: State<'_, DesktopState>, chat_id: String, plaintext: Vec<u8>) -> Result<MlsCiphertext, String> {
    let (key, provider) = native_mls(&state)?;
    let (ciphertext, epoch) = mls::encrypt_application(&provider, &key, &chat_id, &plaintext)?;
    mls::save_provider(&provider, &state.mls_state).map_err(command_error)?;
    Ok(MlsCiphertext { ciphertext, epoch })
}

#[tauri::command]
pub fn mls_process(state: State<'_, DesktopState>, chat_id: String, message: Vec<u8>) -> Result<MlsProcessResult, String> {
    let (_, provider) = native_mls(&state)?;
    let result = mls::process_message(&provider, &chat_id, &message)?;
    mls::save_provider(&provider, &state.mls_state).map_err(command_error)?;
    Ok(match result {
        mls::ProcessedMlsMessage::Application { plaintext, epoch } => MlsProcessResult::Application { plaintext, epoch },
        mls::ProcessedMlsMessage::Commit { epoch } => MlsProcessResult::Commit { epoch },
        mls::ProcessedMlsMessage::Proposal { epoch } => MlsProcessResult::Proposal { epoch },
    })
}

#[tauri::command]
pub fn mls_cached_application(state: State<'_, DesktopState>, message: Vec<u8>) -> Result<Option<Vec<u8>>, String> {
    let (_, provider) = native_mls(&state)?;
    mls::cached_application(&provider, &message)
}

#[tauri::command]
pub fn mls_group_members(state: State<'_, DesktopState>, chat_id: String) -> Result<Vec<String>, String> {
    let (_, provider) = native_mls(&state)?;
    mls::group_members(&provider, &chat_id)
}

#[tauri::command]
pub fn mls_remove_devices(state: State<'_, DesktopState>, chat_id: String, device_ids: Vec<String>) -> Result<MlsCommitResult, String> {
    if device_ids.is_empty() { return Err("at least one revoked device is required".into()); }
    let (key, provider) = native_mls(&state)?;
    let output = mls::remove_devices(&provider, &key, &chat_id, &device_ids)?;
    mls::save_provider(&provider, &state.mls_state).map_err(command_error)?;
    Ok(MlsCommitResult { commit: output.commit, epoch: output.epoch })
}

#[tauri::command]
pub fn mls_self_update(state: State<'_, DesktopState>, chat_id: String) -> Result<MlsCommitResult, String> {
    let (key, provider) = native_mls(&state)?;
    let output = mls::self_update(&provider, &key, &chat_id)?;
    mls::save_provider(&provider, &state.mls_state).map_err(command_error)?;
    Ok(MlsCommitResult { commit: output.commit, epoch: output.epoch })
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
