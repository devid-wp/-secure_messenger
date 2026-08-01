use std::fs;
use std::sync::Mutex;

use zeroize::{Zeroize, ZeroizeOnDrop};

use super::{dpapi, StorageError, StoragePaths};

#[derive(Clone, Zeroize, ZeroizeOnDrop)]
pub struct NativeSession {
    refresh_token: String,
    login: String,
}

impl NativeSession {
    pub fn new(refresh_token: String, login: String) -> Result<Self, StorageError> {
        if refresh_token.is_empty() || refresh_token.len() > 8192 {
            return Err(StorageError::InvalidData("session token length is invalid"));
        }
        if login.is_empty() || login.len() > 255 {
            return Err(StorageError::InvalidData("session login length is invalid"));
        }
        Ok(Self {
            refresh_token,
            login,
        })
    }

    pub fn refresh_token(&self) -> &str {
        &self.refresh_token
    }

    pub fn login(&self) -> &str {
        &self.login
    }
}

pub struct NativeSessionStore {
    current: Mutex<Option<NativeSession>>,
    paths: StoragePaths,
}

impl NativeSessionStore {
    pub fn new(paths: StoragePaths) -> Result<Self, StorageError> {
        let current = match fs::read(paths.session()) {
            Ok(ciphertext) => Some(Self::decode(&dpapi::unprotect(&ciphertext)?)?),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => return Err(error.into()),
        };
        Ok(Self {
            current: Mutex::new(current),
            paths,
        })
    }

    fn encode(session: &NativeSession) -> Result<Vec<u8>, StorageError> {
        let token = session.refresh_token.as_bytes();
        let login = session.login.as_bytes();
        let token_len = u32::try_from(token.len())
            .map_err(|_| StorageError::InvalidData("session token is too large"))?;
        let mut data = Vec::with_capacity(4 + token.len() + login.len());
        data.extend_from_slice(&token_len.to_le_bytes());
        data.extend_from_slice(token);
        data.extend_from_slice(login);
        Ok(data)
    }

    fn decode(data: &[u8]) -> Result<NativeSession, StorageError> {
        if data.len() < 4 {
            return Err(StorageError::InvalidData("session envelope is truncated"));
        }
        let token_len = u32::from_le_bytes(data[..4].try_into().unwrap()) as usize;
        if token_len == 0 || 4 + token_len >= data.len() {
            return Err(StorageError::InvalidData(
                "session envelope length is invalid",
            ));
        }
        let refresh_token = String::from_utf8(data[4..4 + token_len].to_vec())
            .map_err(|_| StorageError::InvalidData("session token is not UTF-8"))?;
        let login = String::from_utf8(data[4 + token_len..].to_vec())
            .map_err(|_| StorageError::InvalidData("session login is not UTF-8"))?;
        NativeSession::new(refresh_token, login)
    }

    pub fn replace(&self, session: NativeSession) -> Result<(), StorageError> {
        fs::create_dir_all(self.paths.root())?;
        fs::write(
            self.paths.session(),
            dpapi::protect(&Self::encode(&session)?)?,
        )?;
        *self
            .current
            .lock()
            .map_err(|_| StorageError::Platform("native session state is poisoned".into()))? =
            Some(session);
        Ok(())
    }

    pub fn current(&self) -> Result<Option<NativeSession>, StorageError> {
        Ok(self
            .current
            .lock()
            .map_err(|_| StorageError::Platform("native session state is poisoned".into()))?
            .clone())
    }

    pub fn clear(&self) -> Result<(), StorageError> {
        self.current
            .lock()
            .map_err(|_| StorageError::Platform("native session state is poisoned".into()))?
            .take();
        match fs::remove_file(self.paths.session()) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_can_be_replaced_and_cleared() {
        let root = std::env::temp_dir().join("secure-messenger-session-store-test");
        let store = NativeSessionStore::new(StoragePaths::new(&root).unwrap()).unwrap();
        store
            .replace(NativeSession::new("secret-token".into(), "alice".into()).unwrap())
            .unwrap();
        let current = store.current().unwrap().unwrap();
        assert_eq!(current.refresh_token(), "secret-token");
        assert_eq!(current.login(), "alice");
        store.clear().unwrap();
        assert!(store.current().unwrap().is_none());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn empty_session_secrets_are_rejected() {
        assert!(NativeSession::new(String::new(), "alice".into()).is_err());
        assert!(NativeSession::new("token".into(), String::new()).is_err());
    }
}
