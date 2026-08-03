use std::fs;

use zeroize::Zeroizing;

use super::atomic::{self, WriteMode};
use super::{dpapi, StorageError, StoragePaths};

const MAGIC: &[u8; 8] = b"SMMLSSIG";
const HEADER_BYTES: usize = MAGIC.len() + size_of::<u32>();
const MAX_KEY_BYTES: usize = 4096;

/// DPAPI-backed native-only storage for the MLS device signature key.
pub struct DeviceKeyStore {
    paths: StoragePaths,
}

impl DeviceKeyStore {
    pub fn new(paths: StoragePaths) -> Self {
        Self { paths }
    }

    pub fn load(&self) -> Result<Option<Zeroizing<Vec<u8>>>, StorageError> {
        let envelope = match fs::read(self.paths.mls_signature_key()) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        if envelope.len() < HEADER_BYTES || &envelope[..MAGIC.len()] != MAGIC {
            return Err(StorageError::InvalidData("MLS signature key envelope is invalid"));
        }
        let length = u32::from_le_bytes(
            envelope[MAGIC.len()..HEADER_BYTES]
                .try_into()
                .expect("header length is fixed"),
        ) as usize;
        if envelope.len() != HEADER_BYTES + length {
            return Err(StorageError::InvalidData("MLS signature key length is invalid"));
        }
        Ok(Some(Zeroizing::new(dpapi::unprotect(
            &envelope[HEADER_BYTES..],
        )?)))
    }

    pub fn create(&self, key: &[u8]) -> Result<(), StorageError> {
        if key.is_empty() || key.len() > MAX_KEY_BYTES {
            return Err(StorageError::InvalidData("MLS signature key size is invalid"));
        }
        let protected = dpapi::protect(key)?;
        let length = u32::try_from(protected.len())
            .map_err(|_| StorageError::InvalidData("protected MLS signature key is too large"))?;
        let mut envelope = Vec::with_capacity(HEADER_BYTES + protected.len());
        envelope.extend_from_slice(MAGIC);
        envelope.extend_from_slice(&length.to_le_bytes());
        envelope.extend_from_slice(&protected);
        fs::create_dir_all(self.paths.root())?;
        atomic::write(
            &self.paths.mls_signature_key(),
            &envelope,
            WriteMode::CreateNew,
        )
    }
}
