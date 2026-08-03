use std::fmt;
use std::io;
use std::path::{Path, PathBuf};

mod atomic;
mod device_key;
pub mod commands;
pub mod dpapi;
mod key;
mod mls_state;
mod session;
mod state;
mod vault;

pub(crate) use key::MasterKey;
pub(crate) use device_key::DeviceKeyStore;
pub(crate) use mls_state::MlsStateStore;
pub(crate) use session::{NativeSession, NativeSessionStore};
pub(crate) use state::NativeVault;
pub(crate) use vault::MasterKeyStore;

#[derive(Debug)]
pub enum StorageError {
    Io(io::Error),
    Platform(String),
    InvalidData(&'static str),
}

impl fmt::Display for StorageError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "native storage I/O failed: {error}"),
            Self::Platform(message) => write!(formatter, "platform protection failed: {message}"),
            Self::InvalidData(message) => {
                write!(formatter, "native storage data is invalid: {message}")
            }
        }
    }
}

impl std::error::Error for StorageError {}

impl From<io::Error> for StorageError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

#[derive(Debug, Clone)]
pub struct StoragePaths {
    root: PathBuf,
}

impl StoragePaths {
    pub fn new(app_data_dir: &Path) -> Result<Self, StorageError> {
        if !app_data_dir.is_absolute() {
            return Err(StorageError::InvalidData(
                "application data directory must be absolute",
            ));
        }
        Ok(Self {
            root: app_data_dir.join("secure-vault"),
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn master_key(&self) -> PathBuf {
        self.root.join("master-key.dpapi")
    }

    pub fn session(&self) -> PathBuf {
        self.root.join("session.dpapi")
    }

    pub fn mls_state(&self) -> PathBuf {
        self.root.join("openmls-state.dpapi")
    }

    pub fn mls_signature_key(&self) -> PathBuf {
        self.root.join("mls-signature-key.dpapi")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn errors_do_not_include_secret_values() {
        assert!(StorageError::InvalidData("bad envelope")
            .to_string()
            .contains("bad envelope"));
    }

    #[test]
    fn storage_paths_stay_below_absolute_app_data_directory() {
        let base = if cfg!(windows) {
            PathBuf::from(r"C:\Users\tester\AppData\Roaming\SecureMessenger")
        } else {
            PathBuf::from("/tmp/secure-messenger")
        };
        let paths = StoragePaths::new(&base).unwrap();
        assert!(paths.root().starts_with(&base));
        assert!(paths.master_key().starts_with(paths.root()));
        assert!(paths.session().starts_with(paths.root()));
        assert!(paths.mls_state().starts_with(paths.root()));
        assert!(paths.mls_signature_key().starts_with(paths.root()));
    }

    #[test]
    fn relative_storage_directory_is_rejected() {
        assert!(StoragePaths::new(Path::new("relative")).is_err());
    }
}
