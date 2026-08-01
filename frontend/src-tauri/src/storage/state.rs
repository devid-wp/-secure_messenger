use std::sync::{Mutex, MutexGuard};

use super::{MasterKey, MasterKeyStore, StorageError, StoragePaths};

pub struct NativeVault {
    key_store: MasterKeyStore,
    master_key: Mutex<Option<MasterKey>>,
}

impl NativeVault {
    pub fn new(paths: StoragePaths) -> Self {
        Self {
            key_store: MasterKeyStore::new(paths),
            master_key: Mutex::new(None),
        }
    }

    fn key_guard(&self) -> Result<MutexGuard<'_, Option<MasterKey>>, StorageError> {
        self.master_key
            .lock()
            .map_err(|_| StorageError::Platform("native vault state is poisoned".into()))
    }

    pub fn unlock(&self) -> Result<(), StorageError> {
        let mut key = self.key_guard()?;
        if key.is_none() {
            *key = Some(self.key_store.load_or_create()?);
        }
        Ok(())
    }

    pub fn lock(&self) -> Result<(), StorageError> {
        self.key_guard()?.take();
        Ok(())
    }

    pub fn is_unlocked(&self) -> Result<bool, StorageError> {
        Ok(self.key_guard()?.is_some())
    }
}

#[cfg(test)]
mod tests {
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    #[test]
    fn vault_has_explicit_lock_lifecycle() {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("secure-messenger-state-{suffix}"));
        let vault = NativeVault::new(StoragePaths::new(&root).unwrap());
        assert!(!vault.is_unlocked().unwrap());
        vault.unlock().unwrap();
        assert!(vault.is_unlocked().unwrap());
        vault.lock().unwrap();
        assert!(!vault.is_unlocked().unwrap());
        std::fs::remove_dir_all(root).unwrap();
    }
}
