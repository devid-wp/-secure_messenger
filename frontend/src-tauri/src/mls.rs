use openmls::prelude::{
    BasicCredential, Ciphersuite, CredentialWithKey, KeyPackage, KeyPackageBundle,
    OpenMlsProvider, SignaturePublicKey,
};
use openmls_basic_credential::SignatureKeyPair;
use sha2::{Digest, Sha256};

/// The only MLS ciphersuite supported by this client.
pub const CIPHERSUITE: Ciphersuite =
    Ciphersuite::MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519;

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

    /// Returns the public signature key used in the device's MLS credential.
    pub fn public_key(&self) -> SignaturePublicKey {
        self.key_pair.public().into()
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
