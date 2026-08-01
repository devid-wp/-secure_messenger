use zeroize::{Zeroize, ZeroizeOnDrop};

use super::StorageError;

pub const MASTER_KEY_BYTES: usize = 32;

#[derive(Zeroize, ZeroizeOnDrop)]
pub struct MasterKey([u8; MASTER_KEY_BYTES]);

impl MasterKey {
    pub fn generate() -> Result<Self, StorageError> {
        let mut bytes = [0_u8; MASTER_KEY_BYTES];
        getrandom::fill(&mut bytes)
            .map_err(|error| StorageError::Platform(format!("OS RNG failed: {error}")))?;
        Ok(Self(bytes))
    }

    pub(crate) fn from_bytes(bytes: [u8; MASTER_KEY_BYTES]) -> Self {
        Self(bytes)
    }

    pub(crate) fn expose(&self) -> &[u8; MASTER_KEY_BYTES] {
        &self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_master_keys_have_expected_length_and_are_unique() {
        let first = MasterKey::generate().unwrap();
        let second = MasterKey::generate().unwrap();
        assert_eq!(first.expose().len(), MASTER_KEY_BYTES);
        assert_ne!(first.expose(), second.expose());
        assert_ne!(first.expose(), &[0; MASTER_KEY_BYTES]);
    }
}
