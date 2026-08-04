use std::fs;
use std::path::Path;

use chacha20poly1305::aead::{Aead, KeyInit};
use chacha20poly1305::{XChaCha20Poly1305, XNonce};
use serde::{Deserialize, Serialize};
use zeroize::{Zeroize, Zeroizing};

use super::atomic::{self, WriteMode};
use super::{DeviceKeyStore, MasterKeyStore, MlsStateStore, StorageError, StoragePaths};

const MAGIC: &[u8; 8] = b"SMBACKUP";
const VERSION: u8 = 1;
const KEY_BYTES: usize = 32;
const NONCE_BYTES: usize = 24;
const HEADER_BYTES: usize = MAGIC.len() + 1 + NONCE_BYTES;

#[derive(Serialize, Deserialize, Zeroize)]
struct BackupPayload {
    master_key: Vec<u8>,
    mls_state: Option<Vec<u8>>,
    mls_signature_key: Option<Vec<u8>>,
}

pub fn export(paths: &StoragePaths, destination: &Path) -> Result<String, StorageError> {
    let master_key = MasterKeyStore::new(paths.clone()).load()?;
    let mls_state = MlsStateStore::new(paths.clone()).load()?;
    let signature_key = DeviceKeyStore::new(paths.clone()).load()?;
    let payload = BackupPayload {
        master_key: master_key.expose().to_vec(),
        mls_state: mls_state.map(|value| value.to_vec()),
        mls_signature_key: signature_key.map(|value| value.to_vec()),
    };
    let plaintext = Zeroizing::new(
        serde_json::to_vec(&payload)
            .map_err(|_| StorageError::InvalidData("backup payload serialization failed"))?,
    );
    let mut key = Zeroizing::new([0_u8; KEY_BYTES]);
    let mut nonce = [0_u8; NONCE_BYTES];
    getrandom::fill(key.as_mut()).map_err(random_error)?;
    getrandom::fill(&mut nonce).map_err(random_error)?;
    let ciphertext = XChaCha20Poly1305::new_from_slice(key.as_ref())
        .expect("backup key length is fixed")
        .encrypt(XNonce::from_slice(&nonce), plaintext.as_ref())
        .map_err(|_| StorageError::InvalidData("backup encryption failed"))?;
    let mut envelope = Vec::with_capacity(HEADER_BYTES + ciphertext.len());
    envelope.extend_from_slice(MAGIC);
    envelope.push(VERSION);
    envelope.extend_from_slice(&nonce);
    envelope.extend_from_slice(&ciphertext);
    atomic::write(destination, &envelope, WriteMode::CreateNew)?;
    Ok(encode_key(key.as_ref()))
}

pub fn restore(
    paths: &StoragePaths,
    source: &Path,
    recovery_key: &str,
) -> Result<(), StorageError> {
    ensure_empty(paths)?;
    let envelope = fs::read(source)?;
    if envelope.len() <= HEADER_BYTES || &envelope[..MAGIC.len()] != MAGIC {
        return Err(StorageError::InvalidData("backup envelope is invalid"));
    }
    if envelope[MAGIC.len()] != VERSION {
        return Err(StorageError::InvalidData("backup version is unsupported"));
    }
    let mut key = Zeroizing::new(decode_key(recovery_key)?);
    let nonce = XNonce::from_slice(&envelope[MAGIC.len() + 1..HEADER_BYTES]);
    let plaintext = Zeroizing::new(
        XChaCha20Poly1305::new_from_slice(key.as_ref())
            .expect("backup key length is fixed")
            .decrypt(nonce, &envelope[HEADER_BYTES..])
            .map_err(|_| StorageError::InvalidData("backup authentication failed"))?,
    );
    key.zeroize();
    let mut payload: BackupPayload = serde_json::from_slice(plaintext.as_ref())
        .map_err(|_| StorageError::InvalidData("backup payload is invalid"))?;
    MasterKeyStore::new(paths.clone()).restore(&payload.master_key)?;
    if let Some(state) = &payload.mls_state {
        MlsStateStore::new(paths.clone()).save(state)?;
    }
    if let Some(signature_key) = &payload.mls_signature_key {
        DeviceKeyStore::new(paths.clone()).create(signature_key)?;
    }
    payload.zeroize();
    Ok(())
}

fn ensure_empty(paths: &StoragePaths) -> Result<(), StorageError> {
    for path in [
        paths.master_key(),
        paths.mls_state(),
        paths.mls_signature_key(),
    ] {
        if path.exists() {
            return Err(StorageError::InvalidData(
                "backup restore requires an empty vault",
            ));
        }
    }
    Ok(())
}

fn random_error(error: getrandom::Error) -> StorageError {
    StorageError::Platform(format!("random generation failed: {error}"))
}

fn encode_key(key: &[u8]) -> String {
    key.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn decode_key(value: &str) -> Result<[u8; KEY_BYTES], StorageError> {
    if value.len() != KEY_BYTES * 2 || !value.is_ascii() {
        return Err(StorageError::InvalidData("recovery key is invalid"));
    }
    let mut key = [0_u8; KEY_BYTES];
    for (index, byte) in key.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| StorageError::InvalidData("recovery key is invalid"))?;
    }
    Ok(key)
}

#[cfg(test)]
mod tests {
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    fn temporary_root(name: &str) -> std::path::PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("secure-messenger-{name}-{suffix}"))
    }

    #[test]
    fn encrypted_backup_restores_crypto_state_but_not_session() {
        let source_root = temporary_root("backup-source");
        let restored_root = temporary_root("backup-restored");
        let backup = temporary_root("backup-file");
        let source = StoragePaths::new(&source_root).unwrap();
        let restored = StoragePaths::new(&restored_root).unwrap();
        let master = MasterKeyStore::new(source.clone())
            .load_or_create()
            .unwrap();
        MlsStateStore::new(source.clone())
            .save(b"mls-private-state")
            .unwrap();
        DeviceKeyStore::new(source.clone())
            .create(b"signature-key")
            .unwrap();

        let recovery_key = export(&source, &backup).unwrap();
        let disk = fs::read(&backup).unwrap();
        assert!(!disk.windows(17).any(|part| part == b"mls-private-state"));
        restore(&restored, &backup, &recovery_key).unwrap();

        assert_eq!(
            MasterKeyStore::new(restored.clone())
                .load()
                .unwrap()
                .expose(),
            master.expose()
        );
        assert_eq!(
            MlsStateStore::new(restored.clone())
                .load()
                .unwrap()
                .unwrap()
                .as_slice(),
            b"mls-private-state"
        );
        assert_eq!(
            DeviceKeyStore::new(restored.clone())
                .load()
                .unwrap()
                .unwrap()
                .as_slice(),
            b"signature-key"
        );
        assert!(!restored.session().exists());
        assert!(restore(&restored, &backup, &recovery_key).is_err());

        fs::remove_dir_all(source_root).unwrap();
        fs::remove_dir_all(restored_root).unwrap();
        fs::remove_file(backup).unwrap();
    }

    #[test]
    fn wrong_recovery_key_does_not_create_vault_files() {
        let source_root = temporary_root("wrong-key-source");
        let restored_root = temporary_root("wrong-key-restored");
        let backup = temporary_root("wrong-key-file");
        let source = StoragePaths::new(&source_root).unwrap();
        let restored = StoragePaths::new(&restored_root).unwrap();
        MasterKeyStore::new(source.clone())
            .load_or_create()
            .unwrap();
        export(&source, &backup).unwrap();
        assert!(restore(&restored, &backup, &"00".repeat(KEY_BYTES)).is_err());
        assert!(!restored.root().exists());
        fs::remove_dir_all(source_root).unwrap();
        fs::remove_file(backup).unwrap();
    }
}
