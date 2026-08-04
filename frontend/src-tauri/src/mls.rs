use openmls::prelude::{
    BasicCredential, Ciphersuite, CredentialWithKey, KeyPackage, KeyPackageBundle,
    OpenMlsProvider, SignaturePublicKey,
};
use openmls_basic_credential::SignatureKeyPair;
use openmls_rust_crypto::OpenMlsRustCrypto;
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

use crate::storage::{DeviceKeyStore, MlsStateStore, StorageError};

/// The only MLS ciphersuite supported by this client.
pub const CIPHERSUITE: Ciphersuite =
    Ciphersuite::MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519;
pub const CIPHERSUITE_ID: u16 = 1;

/// A signature identity belonging to this device.
///
/// This key is deliberately generated independently from storage encryption
/// keys and from MLS group secrets. Callers must persist it in protected device
/// storage before using it to create MLS credentials or key packages.
pub struct DeviceSignatureKey {
    key_pair: SignatureKeyPair,
}

impl DeviceSignatureKey {
    /// Generates a fresh Ed25519 signature key for one device.
    pub fn generate() -> Result<Self, String> {
        let key_pair = SignatureKeyPair::new(CIPHERSUITE.signature_algorithm())
            .map_err(|error| format!("failed to generate device signature key: {error:?}"))?;

        Ok(Self { key_pair })
    }

    /// Loads the device key from the native vault or creates it there once.
    /// No plaintext private-key file is ever written.
    pub fn load_or_create(vault: &DeviceKeyStore) -> Result<Self, StorageError> {
        if let Some(serialized) = vault.load()? {
            let key_pair = serde_json::from_slice(&serialized)
                .map_err(|_| StorageError::InvalidData("MLS device key is invalid"))?;
            return Ok(Self { key_pair });
        }

        let key = Self::generate().map_err(StorageError::Platform)?;
        let serialized = Zeroizing::new(
            serde_json::to_vec(&key.key_pair)
                .map_err(|_| StorageError::InvalidData("MLS device key cannot be serialized"))?,
        );
        vault.create(&serialized)?;
        Ok(key)
    }

    /// Returns the public signature key used in the device's MLS credential.
    pub fn public_key(&self) -> SignaturePublicKey {
        self.key_pair.public().into()
    }

    pub fn public_key_bytes(&self) -> Vec<u8> {
        self.key_pair.public().to_vec()
    }

    /// Provides the signer to OpenMLS while keeping ownership device-scoped.
    pub fn signer(&self) -> &SignatureKeyPair {
        &self.key_pair
    }

    /// SHA-256 fingerprint of the public Ed25519 key, formatted for display.
    pub fn fingerprint(&self) -> String {
        Sha256::digest(self.key_pair.public())
            .iter()
            .map(|byte| format!("{byte:02X}"))
            .collect::<Vec<_>>()
            .join(":")
    }

    /// Creates the MLS BasicCredential bound to this device signature key.
    pub fn credential(&self, identity: impl Into<Vec<u8>>) -> CredentialWithKey {
        CredentialWithKey {
            credential: BasicCredential::new(identity.into()).into(),
            signature_key: self.key_pair.to_public_vec().into(),
        }
    }

    /// Generates a fresh KeyPackage and stores its private material only in the
    /// native OpenMLS provider supplied by the caller.
    pub fn generate_key_package(
        &self,
        provider: &impl OpenMlsProvider,
        identity: impl Into<Vec<u8>>,
    ) -> Result<KeyPackageBundle, String> {
        self.key_pair
            .store(provider.storage())
            .map_err(|error| format!("failed to store MLS signer: {error:?}"))?;
        KeyPackage::builder()
            .build(CIPHERSUITE, provider, &self.key_pair, self.credential(identity))
            .map_err(|error| format!("failed to generate MLS KeyPackage: {error:?}"))
    }
}

pub fn load_provider(store: &MlsStateStore) -> Result<OpenMlsRustCrypto, StorageError> {
    let provider = OpenMlsRustCrypto::default();
    if let Some(serialized) = store.load()? {
        let values = serde_json::from_slice(&serialized)
            .map_err(|_| StorageError::InvalidData("OpenMLS provider state is invalid"))?;
        *provider
            .storage()
            .values
            .write()
            .map_err(|_| StorageError::Platform("OpenMLS provider state is poisoned".into()))? =
            values;
    }
    Ok(provider)
}

pub fn save_provider(
    provider: &OpenMlsRustCrypto,
    store: &MlsStateStore,
) -> Result<(), StorageError> {
    let values = provider
        .storage()
        .values
        .read()
        .map_err(|_| StorageError::Platform("OpenMLS provider state is poisoned".into()))?;
    let serialized = Zeroizing::new(
        serde_json::to_vec(&*values)
            .map_err(|_| StorageError::InvalidData("OpenMLS provider state cannot be serialized"))?,
    );
    store.save(&serialized)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ciphersuite_is_fixed() {
        assert_eq!(
            CIPHERSUITE,
            Ciphersuite::MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519
        );
    }

    #[test]
    fn each_device_gets_a_distinct_signature_key() {
        let first = DeviceSignatureKey::generate().expect("first device key");
        let second = DeviceSignatureKey::generate().expect("second device key");

        assert_ne!(first.public_key(), second.public_key());
    }

    #[test]
    fn fingerprint_is_sha256_in_colon_separated_hex() {
        let key = DeviceSignatureKey::generate().expect("device key");
        let fingerprint = key.fingerprint();
        assert_eq!(fingerprint.len(), 95);
        assert_eq!(fingerprint.matches(':').count(), 31);
    }

    #[test]
    fn credential_and_key_package_use_the_device_key() {
        let provider = openmls_rust_crypto::OpenMlsRustCrypto::default();
        let key = DeviceSignatureKey::generate().expect("device key");
        let credential = key.credential(b"device-1".to_vec());
        assert_eq!(credential.signature_key, key.public_key());
        key.generate_key_package(&provider, b"device-1".to_vec())
            .expect("key package");
    }
}
