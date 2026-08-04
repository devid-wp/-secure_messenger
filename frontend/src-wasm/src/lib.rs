use base64::{engine::general_purpose::STANDARD as B64, Engine};
use openmls::prelude::*;
use openmls_basic_credential::SignatureKeyPair;
use openmls_rust_crypto::OpenMlsRustCrypto;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tls_codec::{Deserialize as TlsDeserialize, Serialize as TlsSerialize};
use wasm_bindgen::prelude::*;

const SUITE: Ciphersuite = Ciphersuite::MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519;

#[derive(Serialize, Deserialize)]
struct PersistedState {
    version: u8,
    device_id: String,
    signer: Vec<u8>,
    provider: Vec<u8>,
}

#[derive(Serialize, Deserialize)]
struct Bootstrap {
    identity_key: String,
    fingerprint: String,
    cipher_suite: u16,
    key_packages: Vec<String>,
}

#[derive(Serialize)]
struct GroupState {
    group_id: String,
    epoch: u64,
}

#[derive(Serialize)]
struct AddOutput {
    commit: String,
    welcome: String,
    epoch: u64,
}

#[derive(Serialize)]
struct WireOutput {
    message: String,
    epoch: u64,
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum ProcessOutput {
    Application { plaintext: String, epoch: u64 },
    Commit { epoch: u64 },
    Proposal { epoch: u64 },
}

fn error(message: impl ToString) -> JsValue {
    JsValue::from_str(&message.to_string())
}
fn json<T: Serialize>(value: &T) -> Result<String, JsValue> {
    serde_json::to_string(value).map_err(error)
}
fn config() -> MlsGroupCreateConfig {
    MlsGroupCreateConfig::builder()
        .ciphersuite(SUITE)
        .use_ratchet_tree_extension(true)
        .build()
}
fn group_id(chat_id: &str) -> GroupId {
    GroupId::from_slice(format!("secure-messenger/chat/{chat_id}").as_bytes())
}

#[wasm_bindgen]
pub struct WasmMlsClient {
    provider: OpenMlsRustCrypto,
    signer: SignatureKeyPair,
    device_id: String,
}

#[wasm_bindgen]
impl WasmMlsClient {
    #[wasm_bindgen(constructor)]
    pub fn new(device_id: String, state: Vec<u8>) -> Result<WasmMlsClient, JsValue> {
        if device_id.is_empty() {
            return Err(error("device id is required"));
        }
        if !state.is_empty() {
            let state: PersistedState =
                serde_json::from_slice(&state).map_err(|_| error("invalid MLS vault state"))?;
            if state.version != 1 || state.device_id != device_id {
                return Err(error("MLS vault identity mismatch"));
            }
            let signer =
                serde_json::from_slice(&state.signer).map_err(|_| error("invalid MLS signer"))?;
            let provider = OpenMlsRustCrypto::default();
            *provider
                .storage()
                .values
                .write()
                .map_err(|_| error("MLS storage lock failed"))? =
                serde_json::from_slice(&state.provider)
                    .map_err(|_| error("invalid MLS provider state"))?;
            return Ok(Self {
                provider,
                signer,
                device_id,
            });
        }
        let signer = SignatureKeyPair::new(SUITE.signature_algorithm())
            .map_err(|e| error(format!("signer generation failed: {e:?}")))?;
        Ok(Self {
            provider: OpenMlsRustCrypto::default(),
            signer,
            device_id,
        })
    }

    pub fn export_state(&self) -> Result<Vec<u8>, JsValue> {
        let values = self
            .provider
            .storage()
            .values
            .read()
            .map_err(|_| error("MLS storage lock failed"))?;
        serde_json::to_vec(&PersistedState {
            version: 1,
            device_id: self.device_id.clone(),
            signer: serde_json::to_vec(&self.signer).map_err(error)?,
            provider: serde_json::to_vec(&*values).map_err(error)?,
        })
        .map_err(error)
    }

    pub fn bootstrap(&self, count: u8) -> Result<String, JsValue> {
        if count > 100 {
            return Err(error("too many KeyPackages"));
        }
        self.signer
            .store(self.provider.storage())
            .map_err(|e| error(format!("signer storage failed: {e:?}")))?;
        let credential = || CredentialWithKey {
            credential: BasicCredential::new(self.device_id.as_bytes().to_vec()).into(),
            signature_key: self.signer.to_public_vec().into(),
        };
        let mut packages = Vec::with_capacity(count as usize);
        for _ in 0..count {
            let bundle = KeyPackage::builder()
                .build(SUITE, &self.provider, &self.signer, credential())
                .map_err(|e| error(format!("KeyPackage failed: {e:?}")))?;
            packages.push(
                B64.encode(
                    bundle
                        .key_package()
                        .tls_serialize_detached()
                        .map_err(error)?,
                ),
            );
        }
        let public = self.signer.public();
        json(&Bootstrap {
            identity_key: B64.encode(public),
            fingerprint: Sha256::digest(public)
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect(),
            cipher_suite: 1,
            key_packages: packages,
        })
    }

    pub fn create_group(&self, chat_id: String) -> Result<String, JsValue> {
        let id = group_id(&chat_id);
        if MlsGroup::load(self.provider.storage(), &id)
            .map_err(|e| error(format!("load failed: {e:?}")))?
            .is_some()
        {
            return Err(error("MLS group already exists"));
        }
        self.signer
            .store(self.provider.storage())
            .map_err(|e| error(format!("signer storage failed: {e:?}")))?;
        let group = MlsGroup::new_with_group_id(
            &self.provider,
            &self.signer,
            &config(),
            id,
            CredentialWithKey {
                credential: BasicCredential::new(self.device_id.as_bytes().to_vec()).into(),
                signature_key: self.signer.to_public_vec().into(),
            },
        )
        .map_err(|e| error(format!("group creation failed: {e:?}")))?;
        json(&GroupState {
            group_id: String::from_utf8_lossy(group.group_id().as_slice()).into(),
            epoch: group.epoch().as_u64(),
        })
    }

    pub fn group_members(&self, chat_id: String) -> Result<String, JsValue> {
        let group = self.load_group(&chat_id)?;
        json(
            &group
                .members()
                .map(|m| String::from_utf8_lossy(m.credential.serialized_content()).into_owned())
                .collect::<Vec<_>>(),
        )
    }

    pub fn add_members(&self, chat_id: String, packages_json: String) -> Result<String, JsValue> {
        let encoded: Vec<String> = serde_json::from_str(&packages_json).map_err(error)?;
        let packages = encoded
            .iter()
            .map(|value| {
                let bytes = B64.decode(value).map_err(error)?;
                KeyPackageIn::tls_deserialize(&mut bytes.as_slice())
                    .map_err(error)?
                    .validate(self.provider.crypto(), ProtocolVersion::Mls10)
                    .map_err(|e| error(format!("invalid KeyPackage: {e:?}")))
            })
            .collect::<Result<Vec<_>, JsValue>>()?;
        let mut group = self.load_group(&chat_id)?;
        let (commit, welcome, _) = group
            .add_members(&self.provider, &self.signer, &packages)
            .map_err(|e| error(format!("add failed: {e:?}")))?;
        group
            .merge_pending_commit(&self.provider)
            .map_err(|e| error(format!("merge failed: {e:?}")))?;
        json(&AddOutput {
            commit: B64.encode(commit.tls_serialize_detached().map_err(error)?),
            welcome: B64.encode(welcome.tls_serialize_detached().map_err(error)?),
            epoch: group.epoch().as_u64(),
        })
    }

    pub fn join_group(&self, welcome: Vec<u8>) -> Result<String, JsValue> {
        let body = MlsMessageIn::tls_deserialize(&mut welcome.as_slice())
            .map_err(error)?
            .extract();
        let welcome = match body {
            MlsMessageBodyIn::Welcome(w) => w,
            _ => return Err(error("not a Welcome")),
        };
        let group =
            StagedWelcome::new_from_welcome(&self.provider, config().join_config(), welcome, None)
                .map_err(|e| error(format!("Welcome failed: {e:?}")))?
                .into_group(&self.provider)
                .map_err(|e| error(format!("join failed: {e:?}")))?;
        json(&GroupState {
            group_id: String::from_utf8_lossy(group.group_id().as_slice()).into(),
            epoch: group.epoch().as_u64(),
        })
    }

    pub fn encrypt(&self, chat_id: String, plaintext: Vec<u8>) -> Result<String, JsValue> {
        let mut group = self.load_group(&chat_id)?;
        let message = group
            .create_message(&self.provider, &self.signer, &plaintext)
            .map_err(|e| error(format!("encryption failed: {e:?}")))?;
        let bytes = message.tls_serialize_detached().map_err(error)?;
        self.cache(&bytes, &plaintext)?;
        json(&WireOutput {
            message: B64.encode(bytes),
            epoch: group.epoch().as_u64(),
        })
    }

    pub fn cached_application(&self, message: Vec<u8>) -> Result<Option<String>, JsValue> {
        Ok(self
            .provider
            .storage()
            .values
            .read()
            .map_err(|_| error("MLS storage lock failed"))?
            .get(&cache_key(&message))
            .map(|value| B64.encode(value)))
    }

    pub fn process(&self, chat_id: String, message: Vec<u8>) -> Result<String, JsValue> {
        let mut group = self.load_group(&chat_id)?;
        let protocol = MlsMessageIn::tls_deserialize(&mut message.as_slice())
            .map_err(error)?
            .try_into_protocol_message()
            .map_err(|_| error("unexpected MLS message"))?;
        let processed = group
            .process_message(&self.provider, protocol)
            .map_err(|e| error(format!("MLS message rejected: {e:?}")))?;
        let output = match processed.into_content() {
            ProcessedMessageContent::ApplicationMessage(app) => {
                let plaintext = app.into_bytes();
                self.cache(&message, &plaintext)?;
                ProcessOutput::Application {
                    plaintext: B64.encode(plaintext),
                    epoch: group.epoch().as_u64(),
                }
            }
            ProcessedMessageContent::StagedCommitMessage(commit) => {
                group
                    .merge_staged_commit(&self.provider, *commit)
                    .map_err(|e| error(format!("commit merge failed: {e:?}")))?;
                ProcessOutput::Commit {
                    epoch: group.epoch().as_u64(),
                }
            }
            ProcessedMessageContent::ProposalMessage(_) => ProcessOutput::Proposal {
                epoch: group.epoch().as_u64(),
            },
            _ => return Err(error("unsupported MLS content")),
        };
        json(&output)
    }

    pub fn remove_devices(&self, chat_id: String, ids_json: String) -> Result<String, JsValue> {
        let ids: Vec<String> = serde_json::from_str(&ids_json).map_err(error)?;
        let mut group = self.load_group(&chat_id)?;
        let indices = group
            .members()
            .filter(|m| {
                ids.iter()
                    .any(|id| m.credential.serialized_content() == id.as_bytes())
            })
            .map(|m| m.index)
            .collect::<Vec<_>>();
        if indices.is_empty() {
            return Err(error("revoked device is not an MLS group member"));
        }
        let (commit, _, _) = group
            .remove_members(&self.provider, &self.signer, &indices)
            .map_err(|e| error(format!("remove failed: {e:?}")))?;
        group
            .merge_pending_commit(&self.provider)
            .map_err(|e| error(format!("merge failed: {e:?}")))?;
        json(&WireOutput {
            message: B64.encode(commit.tls_serialize_detached().map_err(error)?),
            epoch: group.epoch().as_u64(),
        })
    }

    pub fn self_update(&self, chat_id: String) -> Result<String, JsValue> {
        let mut group = self.load_group(&chat_id)?;
        let commit = group
            .self_update(&self.provider, &self.signer, Default::default())
            .map_err(|e| error(format!("update failed: {e:?}")))?
            .into_commit();
        group
            .merge_pending_commit(&self.provider)
            .map_err(|e| error(format!("merge failed: {e:?}")))?;
        json(&WireOutput {
            message: B64.encode(commit.tls_serialize_detached().map_err(error)?),
            epoch: group.epoch().as_u64(),
        })
    }
}

impl WasmMlsClient {
    fn load_group(&self, chat_id: &str) -> Result<MlsGroup, JsValue> {
        MlsGroup::load(self.provider.storage(), &group_id(chat_id))
            .map_err(|e| error(format!("group load failed: {e:?}")))?
            .ok_or_else(|| error("MLS group is not initialized"))
    }
    fn cache(&self, message: &[u8], plaintext: &[u8]) -> Result<(), JsValue> {
        self.provider
            .storage()
            .values
            .write()
            .map_err(|_| error("MLS storage lock failed"))?
            .insert(cache_key(message), plaintext.to_vec());
        Ok(())
    }
}

fn cache_key(message: &[u8]) -> Vec<u8> {
    let mut key = b"secure-messenger/application-cache/".to_vec();
    key.extend_from_slice(&Sha256::digest(message));
    key
}

#[cfg(test)]
mod tests {
    use super::*;
    use wasm_bindgen_test::*;

    wasm_bindgen_test_configure!(run_in_browser);

    #[wasm_bindgen_test]
    fn state_round_trip_preserves_identity_and_key_packages() {
        let first = WasmMlsClient::new("pwa-device".into(), vec![]).unwrap();
        let initial: Bootstrap = serde_json::from_str(&first.bootstrap(1).unwrap()).unwrap();
        assert_eq!(initial.cipher_suite, 1);
        assert_eq!(initial.key_packages.len(), 1);
        let restored =
            WasmMlsClient::new("pwa-device".into(), first.export_state().unwrap()).unwrap();
        let later: Bootstrap = serde_json::from_str(&restored.bootstrap(0).unwrap()).unwrap();
        assert_eq!(initial.identity_key, later.identity_key);
        assert_eq!(initial.fingerprint, later.fingerprint);
    }
}
