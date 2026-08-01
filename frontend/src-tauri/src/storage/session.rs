use std::sync::Mutex;

use zeroize::{Zeroize, ZeroizeOnDrop};

use super::StorageError;

#[derive(Clone, Zeroize, ZeroizeOnDrop)]
pub struct NativeSession {
    token: String,
    login: String,
}

impl NativeSession {
    pub fn new(token: String, login: String) -> Result<Self, StorageError> {
        if token.is_empty() || token.len() > 8192 {
            return Err(StorageError::InvalidData("session token length is invalid"));
        }
        if login.is_empty() || login.len() > 255 {
            return Err(StorageError::InvalidData("session login length is invalid"));
        }
        Ok(Self { token, login })
    }

    pub fn token(&self) -> &str {
        &self.token
    }

    pub fn login(&self) -> &str {
        &self.login
    }
}

#[derive(Default)]
pub struct NativeSessionStore {
    current: Mutex<Option<NativeSession>>,
}

impl NativeSessionStore {
    pub fn replace(&self, session: NativeSession) -> Result<(), StorageError> {
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
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_can_be_replaced_and_cleared() {
        let store = NativeSessionStore::default();
        store
            .replace(NativeSession::new("secret-token".into(), "alice".into()).unwrap())
            .unwrap();
        let current = store.current().unwrap().unwrap();
        assert_eq!(current.token(), "secret-token");
        assert_eq!(current.login(), "alice");
        store.clear().unwrap();
        assert!(store.current().unwrap().is_none());
    }

    #[test]
    fn empty_session_secrets_are_rejected() {
        assert!(NativeSession::new(String::new(), "alice".into()).is_err());
        assert!(NativeSession::new("token".into(), String::new()).is_err());
    }
}
