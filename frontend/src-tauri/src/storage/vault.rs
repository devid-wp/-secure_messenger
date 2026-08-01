use std::fs::{self, OpenOptions};
use std::io::Write;

use super::dpapi;
use super::key::MASTER_KEY_BYTES;
use super::{MasterKey, StorageError, StoragePaths};

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
        let protected = fs::read(self.paths.master_key())?;
        let plaintext = dpapi::unprotect(&protected)?;
        let bytes: [u8; MASTER_KEY_BYTES] = plaintext
            .try_into()
            .map_err(|_| StorageError::InvalidData("master key length is invalid"))?;
        Ok(MasterKey::from_bytes(bytes))
    }

    fn create(&self) -> Result<MasterKey, StorageError> {
        let key = MasterKey::generate()?;
        let protected = dpapi::protect(key.expose())?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(self.paths.master_key())?;
        file.write_all(&protected)?;
        file.sync_all()?;
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
}
