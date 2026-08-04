use openmls::prelude::{
    BasicCredential, Ciphersuite, CredentialWithKey, GroupId, KeyPackage, KeyPackageBundle,
    KeyPackageIn, MlsGroup, MlsGroupCreateConfig, MlsMessageBodyIn, MlsMessageIn, MlsMessageOut,
    OpenMlsProvider, ProcessedMessageContent, ProtocolVersion, SignaturePublicKey, StagedWelcome,
};
use openmls_basic_credential::SignatureKeyPair;
use openmls_rust_crypto::OpenMlsRustCrypto;
use sha2::{Digest, Sha256};
use tls_codec::{Deserialize as TlsDeserialize, Serialize as TlsSerialize};
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

fn group_config() -> MlsGroupCreateConfig {
    MlsGroupCreateConfig::builder()
        .ciphersuite(CIPHERSUITE)
        .use_ratchet_tree_extension(true)
        .build()
}

pub fn group_id(chat_id: &str) -> GroupId {
    GroupId::from_slice(format!("secure-messenger/chat/{chat_id}").as_bytes())
}

pub fn create_group(
    provider: &OpenMlsRustCrypto,
    key: &DeviceSignatureKey,
    device_id: &str,
    chat_id: &str,
) -> Result<u64, String> {
    let id = group_id(chat_id);
    if MlsGroup::load(provider.storage(), &id)
        .map_err(|e| format!("failed to inspect MLS group: {e:?}"))?
        .is_some()
    {
        return Err("MLS group already exists".into());
    }
    key.signer().store(provider.storage())
        .map_err(|e| format!("failed to store MLS signer: {e:?}"))?;
    let group = MlsGroup::new_with_group_id(
        provider, key.signer(), &group_config(), id, key.credential(device_id.as_bytes()),
    ).map_err(|e| format!("failed to create MLS group: {e:?}"))?;
    Ok(group.epoch().as_u64())
}

pub struct AddMembersOutput {
    pub commit: Vec<u8>,
    pub welcome: Vec<u8>,
    pub epoch: u64,
}

pub struct CommitOutput {
    pub commit: Vec<u8>,
    pub epoch: u64,
}

pub fn add_members(
    provider: &OpenMlsRustCrypto,
    key: &DeviceSignatureKey,
    chat_id: &str,
    encoded_packages: &[Vec<u8>],
) -> Result<AddMembersOutput, String> {
    let mut group = load_group(provider, chat_id)?;
    let packages = encoded_packages.iter().map(|bytes| {
        KeyPackageIn::tls_deserialize(&mut bytes.as_slice())
            .map_err(|_| "invalid TLS KeyPackage".to_string())?
            .validate(provider.crypto(), ProtocolVersion::Mls10)
            .map_err(|e| format!("invalid KeyPackage: {e:?}"))
    }).collect::<Result<Vec<_>, _>>()?;
    let (commit, welcome, _) = group.add_members(provider, key.signer(), &packages)
        .map_err(|e| format!("failed to add MLS members: {e:?}"))?;
    group.merge_pending_commit(provider)
        .map_err(|e| format!("failed to merge local MLS commit: {e:?}"))?;
    Ok(AddMembersOutput {
        commit: serialize_message(commit)?,
        welcome: serialize_message(welcome)?,
        epoch: group.epoch().as_u64(),
    })
}

pub fn join_group(provider: &OpenMlsRustCrypto, welcome_bytes: &[u8]) -> Result<(String, u64), String> {
    let mut cursor = welcome_bytes;
    let welcome = match MlsMessageIn::tls_deserialize(&mut cursor)
        .map_err(|_| "invalid TLS Welcome".to_string())?.extract() {
        MlsMessageBodyIn::Welcome(welcome) => welcome,
        _ => return Err("MLS message is not a Welcome".into()),
    };
    let group = StagedWelcome::new_from_welcome(provider, group_config().join_config(), welcome, None)
        .map_err(|e| format!("failed to stage MLS Welcome: {e:?}"))?
        .into_group(provider)
        .map_err(|e| format!("failed to join MLS group: {e:?}"))?;
    let id = String::from_utf8_lossy(group.group_id().as_slice()).into_owned();
    Ok((id, group.epoch().as_u64()))
}

pub fn encrypt_application(
    provider: &OpenMlsRustCrypto, key: &DeviceSignatureKey, chat_id: &str, plaintext: &[u8]
) -> Result<(Vec<u8>, u64), String> {
    if plaintext.is_empty() { return Err("MLS application payload is empty".into()); }
    let mut group = load_group(provider, chat_id)?;
    let message = group.create_message(provider, key.signer(), plaintext)
        .map_err(|e| format!("failed to encrypt MLS application message: {e:?}"))?;
    let encoded = serialize_message(message)?;
    provider.storage().values.write()
        .map_err(|_| "OpenMLS provider state is poisoned".to_string())?
        .insert(application_cache_key(&encoded), plaintext.to_vec());
    Ok((encoded, group.epoch().as_u64()))
}

pub fn remove_devices(
    provider: &OpenMlsRustCrypto,
    key: &DeviceSignatureKey,
    chat_id: &str,
    device_ids: &[String],
) -> Result<CommitOutput, String> {
    let mut group = load_group(provider, chat_id)?;
    let indices = group.members()
        .filter(|member| device_ids.iter().any(|id| member.credential.serialized_content() == id.as_bytes()))
        .map(|member| member.index)
        .collect::<Vec<_>>();
    if indices.is_empty() { return Err("revoked device is not an MLS group member".into()); }
    let (commit, _, _) = group.remove_members(provider, key.signer(), &indices)
        .map_err(|e| format!("failed to remove MLS members: {e:?}"))?;
    group.merge_pending_commit(provider)
        .map_err(|e| format!("failed to merge MLS Remove Commit: {e:?}"))?;
    Ok(CommitOutput { commit: serialize_message(commit)?, epoch: group.epoch().as_u64() })
}

pub fn self_update(
    provider: &OpenMlsRustCrypto, key: &DeviceSignatureKey, chat_id: &str
) -> Result<CommitOutput, String> {
    let mut group = load_group(provider, chat_id)?;
    let commit = group.self_update(provider, key.signer(), Default::default())
        .map_err(|e| format!("failed to create MLS Update Commit: {e:?}"))?.into_commit();
    group.merge_pending_commit(provider)
        .map_err(|e| format!("failed to merge MLS Update Commit: {e:?}"))?;
    Ok(CommitOutput { commit: serialize_message(commit)?, epoch: group.epoch().as_u64() })
}

pub enum ProcessedMlsMessage {
    Application { plaintext: Vec<u8>, epoch: u64 },
    Commit { epoch: u64 },
    Proposal { epoch: u64 },
}

pub fn process_message(
    provider: &OpenMlsRustCrypto, chat_id: &str, encoded: &[u8]
) -> Result<ProcessedMlsMessage, String> {
    let mut group = load_group(provider, chat_id)?;
    let mut cursor = encoded;
    let inbound = MlsMessageIn::tls_deserialize(&mut cursor)
        .map_err(|_| "invalid TLS MLS message".to_string())?
        .try_into_protocol_message().map_err(|_| "unexpected MLS wire message".to_string())?;
    let processed = group.process_message(provider, inbound)
        .map_err(|e| format!("rejected MLS message: {e:?}"))?;
    match processed.into_content() {
        ProcessedMessageContent::ApplicationMessage(application) => {
            let plaintext = application.into_bytes();
            provider.storage().values.write()
                .map_err(|_| "OpenMLS provider state is poisoned".to_string())?
                .insert(application_cache_key(encoded), plaintext.clone());
            Ok(ProcessedMlsMessage::Application { plaintext, epoch: group.epoch().as_u64() })
        },
        ProcessedMessageContent::StagedCommitMessage(commit) => {
            group.merge_staged_commit(provider, *commit)
                .map_err(|e| format!("failed to merge MLS commit: {e:?}"))?;
            Ok(ProcessedMlsMessage::Commit { epoch: group.epoch().as_u64() })
        }
        ProcessedMessageContent::ProposalMessage(_) => Ok(
            ProcessedMlsMessage::Proposal { epoch: group.epoch().as_u64() }
        ),
        _ => Err("unsupported MLS message content".into()),
    }
}

pub fn cached_application(provider: &OpenMlsRustCrypto, encoded: &[u8]) -> Result<Option<Vec<u8>>, String> {
    Ok(provider.storage().values.read()
        .map_err(|_| "OpenMLS provider state is poisoned".to_string())?
        .get(&application_cache_key(encoded)).cloned())
}

fn application_cache_key(encoded: &[u8]) -> Vec<u8> {
    let mut key = b"secure-messenger/application-cache/".to_vec();
    key.extend_from_slice(&Sha256::digest(encoded));
    key
}

fn load_group(provider: &OpenMlsRustCrypto, chat_id: &str) -> Result<MlsGroup, String> {
    MlsGroup::load(provider.storage(), &group_id(chat_id))
        .map_err(|e| format!("failed to load MLS group: {e:?}"))?
        .ok_or_else(|| "MLS group is not initialized".into())
}

pub fn group_members(provider: &OpenMlsRustCrypto, chat_id: &str) -> Result<Vec<String>, String> {
    Ok(load_group(provider, chat_id)?.members()
        .map(|member| String::from_utf8_lossy(member.credential.serialized_content()).into_owned())
        .collect())
}

fn serialize_message(message: MlsMessageOut) -> Result<Vec<u8>, String> {
    message.tls_serialize_detached().map_err(|_| "failed to serialize MLS message".into())
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

    #[test]
    fn two_devices_join_advance_epoch_and_exchange_out_of_order_messages() {
        let alice_provider = OpenMlsRustCrypto::default();
        let bob_provider = OpenMlsRustCrypto::default();
        let alice = DeviceSignatureKey::generate().unwrap();
        let bob = DeviceSignatureKey::generate().unwrap();
        let chat = "42";

        assert_eq!(create_group(&alice_provider, &alice, "alice-device", chat).unwrap(), 0);
        let bob_package = bob.generate_key_package(&bob_provider, b"bob-device".to_vec()).unwrap();
        let encoded_package = bob_package.key_package().tls_serialize_detached().unwrap();
        let add = add_members(&alice_provider, &alice, chat, &[encoded_package]).unwrap();
        assert_eq!(add.epoch, 1);
        let (_, bob_epoch) = join_group(&bob_provider, &add.welcome).unwrap();
        assert_eq!(bob_epoch, 1);

        let (first, _) = encrypt_application(&alice_provider, &alice, chat, b"first").unwrap();
        let (second, _) = encrypt_application(&alice_provider, &alice, chat, b"second").unwrap();
        match process_message(&bob_provider, chat, &second).unwrap() {
            ProcessedMlsMessage::Application { plaintext, epoch } => {
                assert_eq!(plaintext, b"second");
                assert_eq!(epoch, 1);
            }
            _ => panic!("expected application message"),
        }
        match process_message(&bob_provider, chat, &first).unwrap() {
            ProcessedMlsMessage::Application { plaintext, .. } => assert_eq!(plaintext, b"first"),
            _ => panic!("expected application message"),
        }
        assert!(process_message(&bob_provider, chat, &first).is_err(), "replay must fail closed");

        let removal = remove_devices(&alice_provider, &alice, chat, &["bob-device".into()]).unwrap();
        assert_eq!(removal.epoch, 2);
        match process_message(&bob_provider, chat, &removal.commit).unwrap() {
            ProcessedMlsMessage::Commit { epoch } => assert_eq!(epoch, 2),
            _ => panic!("expected Remove Commit"),
        }
        let (after_removal, _) = encrypt_application(&alice_provider, &alice, chat, b"after removal").unwrap();
        assert!(process_message(&bob_provider, chat, &after_removal).is_err());
    }
}
