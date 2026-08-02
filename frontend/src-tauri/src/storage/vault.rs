use std::fs;

use super::atomic::{self, WriteMode};
use super::dpapi;
use super::key::MASTER_KEY_BYTES;
use super::{MasterKey, StorageError, StoragePaths};

const ENVELOPE_MAGIC: &[u8; 8] = b"SMVAULT\0";
const ENVELOPE_VERSION: u8 = 1;
const HEADER_BYTES: usize = ENVELOPE_MAGIC.len() + 1 + size_of::<u32>();

fn encode_envelope(protected: &[u8]) -> Result<Vec<u8>, StorageError> {
    let length = u32::try_from(protected.len())
        .map_err(|_| StorageError::InvalidData("protected master key is too large"))?;
    let mut envelope = Vec::with_capacity(HEADER_BYTES + protected.len());
    envelope.extend_from_slice(ENVELOPE_MAGIC);
    envelope.push(ENVELOPE_VERSION);
    envelope.extend_from_slice(&length.to_le_bytes());
    envelope.extend_from_slice(protected);
    Ok(envelope)
}

fn decode_envelope(envelope: &[u8]) -> Result<&[u8], StorageError> {
    if envelope.len() < HEADER_BYTES || &envelope[..ENVELOPE_MAGIC.len()] != ENVELOPE_MAGIC {
        return Err(StorageError::InvalidData(
            "master key envelope header is invalid",
        ));
    }
    if envelope[ENVELOPE_MAGIC.len()] != ENVELOPE_VERSION {
        return Err(StorageError::InvalidData(
            "master key envelope version is unsupported",
        ));
    }
    let length_offset = ENVELOPE_MAGIC.len() + 1;
    let protected_length = u32::from_le_bytes(
        envelope[length_offset..HEADER_BYTES]
            .try_into()
            .expect("header length is fixed"),
    ) as usize;
    if envelope.len() != HEADER_BYTES + protected_length {
        return Err(StorageError::InvalidData(
            "master key envelope length is invalid",
        ));
    }
    Ok(&envelope[HEADER_BYTES..])
}

pub struct MasterKeyStore {
    paths: StoragePaths,
}

impl MasterKeyStore {
    pub fn new(paths: StoragePaths) -> Self {
        Self { paths }
    }

    pub fn load_or_create(&self) -> Result<MasterKey, StorageError> {
        fs::create_dir_all(self.paths.root())?;
        match self.load() {
            Ok(key) => Ok(key),
            Err(StorageError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
                self.create()
            }
            Err(error) => Err(error),
        }
    }

    fn load(&self) -> Result<MasterKey, StorageError> {
        let envelope = fs::read(self.paths.master_key())?;
        let plaintext = dpapi::unprotect(decode_envelope(&envelope)?)?;
        let bytes: [u8; MASTER_KEY_BYTES] = plaintext
            .try_into()
            .map_err(|_| StorageError::InvalidData("master key length is invalid"))?;
        Ok(MasterKey::from_bytes(bytes))
    }

    fn create(&self) -> Result<MasterKey, StorageError> {
        let key = MasterKey::generate()?;
        let protected = dpapi::protect(key.expose())?;
        let envelope = encode_envelope(&protected)?;
        atomic::write(&self.paths.master_key(), &envelope, WriteMode::CreateNew)?;
        Ok(key)
    }
}

#[cfg(test)]
mod tests {
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    fn temporary_store() -> (std::path::PathBuf, MasterKeyStore) {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("secure-messenger-vault-{suffix}"));
        let paths = StoragePaths::new(&root).unwrap();
        (root, MasterKeyStore::new(paths))
    }

    #[test]
    fn master_key_is_reloaded_from_dpapi_file() {
        let (root, store) = temporary_store();
        let first = store.load_or_create().unwrap();
        let second = store.load_or_create().unwrap();
        assert_eq!(first.expose(), second.expose());
        let protected = fs::read(store.paths.master_key()).unwrap();
        assert!(!protected
            .windows(MASTER_KEY_BYTES)
            .any(|part| part == first.expose()));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn corrupt_and_future_envelopes_are_rejected_before_dpapi() {
        assert!(decode_envelope(b"not-a-vault").is_err());
        let mut envelope = encode_envelope(b"protected").unwrap();
        envelope[ENVELOPE_MAGIC.len()] = ENVELOPE_VERSION + 1;
        assert!(decode_envelope(&envelope).is_err());
        envelope[ENVELOPE_MAGIC.len()] = ENVELOPE_VERSION;
        envelope.pop();
        assert!(decode_envelope(&envelope).is_err());
    }

    #[test]
    fn corrupt_vault_is_reported_without_being_overwritten() {
        let (root, store) = temporary_store();
        fs::create_dir_all(store.paths.root()).unwrap();
        let corrupt = b"corrupt vault that must be preserved";
        fs::write(store.paths.master_key(), corrupt).unwrap();

        assert!(store.load_or_create().is_err());
        assert_eq!(fs::read(store.paths.master_key()).unwrap(), corrupt);

        fs::remove_dir_all(root).unwrap();
    }
}
