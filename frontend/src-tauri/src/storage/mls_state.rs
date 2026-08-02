use std::fs;

use zeroize::Zeroizing;

use super::atomic::{self, WriteMode};
use super::{dpapi, StorageError, StoragePaths};

const ENVELOPE_MAGIC: &[u8; 8] = b"SMMLS\0\0\0";
const STORAGE_SCHEMA_VERSION: u16 = 1;
const HEADER_BYTES: usize = ENVELOPE_MAGIC.len() + size_of::<u16>() + size_of::<u32>();
const MAX_STATE_BYTES: usize = 64 * 1024 * 1024;

/// Native-only persistence for serialized OpenMLS provider state.
///
/// The caller owns OpenMLS serialization. This boundary keeps plaintext out of
/// the WebView and persists only a DPAPI-protected, atomically replaced blob.
pub struct MlsStateStore {
    paths: StoragePaths,
}

impl MlsStateStore {
    pub fn new(paths: StoragePaths) -> Self {
        Self { paths }
    }

    pub fn load(&self) -> Result<Option<Zeroizing<Vec<u8>>>, StorageError> {
        let envelope = match fs::read(self.paths.mls_state()) {
            Ok(envelope) => envelope,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        let protected = decode_envelope(&envelope)?;
        let plaintext = Zeroizing::new(dpapi::unprotect(protected)?);
        validate_state_size(plaintext.len())?;
        Ok(Some(plaintext))
    }

    pub fn save(&self, state: &[u8]) -> Result<(), StorageError> {
        validate_state_size(state.len())?;
        let protected = dpapi::protect(state)?;
        let envelope = encode_envelope(&protected)?;
        atomic::write(&self.paths.mls_state(), &envelope, WriteMode::Replace)
    }
}

fn validate_state_size(length: usize) -> Result<(), StorageError> {
    if length == 0 || length > MAX_STATE_BYTES {
        return Err(StorageError::InvalidData("OpenMLS state length is invalid"));
    }
    Ok(())
}

fn encode_envelope(protected: &[u8]) -> Result<Vec<u8>, StorageError> {
    let length = u32::try_from(protected.len())
        .map_err(|_| StorageError::InvalidData("protected OpenMLS state is too large"))?;
    let mut envelope = Vec::with_capacity(HEADER_BYTES + protected.len());
    envelope.extend_from_slice(ENVELOPE_MAGIC);
    envelope.extend_from_slice(&STORAGE_SCHEMA_VERSION.to_le_bytes());
    envelope.extend_from_slice(&length.to_le_bytes());
    envelope.extend_from_slice(protected);
    Ok(envelope)
}

fn decode_envelope(envelope: &[u8]) -> Result<&[u8], StorageError> {
    if envelope.len() < HEADER_BYTES {
        return Err(StorageError::InvalidData("OpenMLS state envelope is truncated"));
    }
    if &envelope[..ENVELOPE_MAGIC.len()] != ENVELOPE_MAGIC {
        return Err(StorageError::InvalidData(
            "OpenMLS state envelope header is invalid",
        ));
    }
    let version_offset = ENVELOPE_MAGIC.len();
    let length_offset = version_offset + size_of::<u16>();
    let version = u16::from_le_bytes(
        envelope[version_offset..length_offset]
            .try_into()
            .expect("schema version length is fixed"),
    );
    if version != STORAGE_SCHEMA_VERSION {
        return Err(StorageError::InvalidData(
            "OpenMLS storage schema version is unsupported",
        ));
    }
    let protected_length = u32::from_le_bytes(
        envelope[length_offset..HEADER_BYTES]
            .try_into()
            .expect("header length is fixed"),
    ) as usize;
    if envelope.len() != HEADER_BYTES + protected_length {
        return Err(StorageError::InvalidData(
            "OpenMLS state envelope length is invalid",
        ));
    }
    Ok(&envelope[HEADER_BYTES..])
}

#[cfg(test)]
mod tests {
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    fn temporary_store() -> (std::path::PathBuf, MlsStateStore) {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("secure-messenger-mls-state-{suffix}"));
        let paths = StoragePaths::new(&root).unwrap();
        (root, MlsStateStore::new(paths))
    }

    #[test]
    fn open_mls_state_round_trips_without_plaintext_on_disk() {
        let (root, store) = temporary_store();
        let plaintext = b"serialized OpenMLS private state";
        store.save(plaintext).unwrap();

        let disk = fs::read(store.paths.mls_state()).unwrap();
        assert!(!disk.windows(plaintext.len()).any(|part| part == plaintext));
        assert_eq!(store.load().unwrap().unwrap().as_slice(), plaintext);

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn invalid_or_empty_state_is_rejected() {
        assert!(validate_state_size(0).is_err());
        assert!(decode_envelope(b"not OpenMLS state").is_err());
    }

    #[test]
    fn unknown_storage_schema_is_rejected_without_rewriting_the_file() {
        let (root, store) = temporary_store();
        fs::create_dir_all(store.paths.root()).unwrap();
        let mut future = encode_envelope(b"protected bytes").unwrap();
        let version_offset = ENVELOPE_MAGIC.len();
        future[version_offset..version_offset + size_of::<u16>()]
            .copy_from_slice(&(STORAGE_SCHEMA_VERSION + 1).to_le_bytes());
        fs::write(store.paths.mls_state(), &future).unwrap();

        assert!(store.load().is_err());
        assert_eq!(fs::read(store.paths.mls_state()).unwrap(), future);

        fs::remove_dir_all(root).unwrap();
    }
}
