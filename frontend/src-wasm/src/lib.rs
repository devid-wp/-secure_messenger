use base64::{engine::general_purpose::STANDARD as B64, Engine};
use openmls::prelude::*;
use openmls_basic_credential::SignatureKeyPair;
use openmls_rust_crypto::OpenMlsRustCrypto;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
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

#[derive(Serialize, Deserialize)]
struct GroupState {
    group_id: String,
    epoch: u64,
}

#[derive(Serialize, Deserialize)]
struct AddOutput {
    commit: String,
    welcome: String,
    epoch: u64,
}

#[derive(Serialize, Deserialize)]
struct WireOutput {
    message: String,
    epoch: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum ProcessOutput {
    Application { plaintext: String, epoch: u64 },
    Commit { epoch: u64 },
    Proposal { epoch: u64 },
}

#[cfg(target_arch = "wasm32")]
fn error(message: impl ToString) -> JsValue {
    JsValue::from_str(&message.to_string())
}
#[cfg(not(target_arch = "wasm32"))]
fn error(_message: impl ToString) -> JsValue {
    // `JsValue::from_str` is only implemented by the wasm-bindgen runtime.
    // Native tests only need the Result boundary when asserting rejection.
    JsValue::NULL
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

const PROVIDER_STATE_MAGIC: &[u8; 5] = b"SMMS1";

fn serialize_provider(values: &HashMap<Vec<u8>, Vec<u8>>) -> Vec<u8> {
    let mut output = Vec::new();
    output.extend_from_slice(PROVIDER_STATE_MAGIC);
    output.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for (key, value) in values {
        output.extend_from_slice(&(key.len() as u64).to_be_bytes());
        output.extend_from_slice(&(value.len() as u64).to_be_bytes());
        output.extend_from_slice(key);
        output.extend_from_slice(value);
    }
    output
}

fn deserialize_provider(input: &[u8]) -> Result<HashMap<Vec<u8>, Vec<u8>>, ()> {
    if !input.starts_with(PROVIDER_STATE_MAGIC) {
        return serde_json::from_slice(input).map_err(|_| ());
    }
    let mut cursor = PROVIDER_STATE_MAGIC.len();
    let read_u64 = |cursor: &mut usize| -> Result<u64, ()> {
        let end = cursor.checked_add(8).ok_or(())?;
        let bytes: [u8; 8] = input
            .get(*cursor..end)
            .ok_or(())?
            .try_into()
            .map_err(|_| ())?;
        *cursor = end;
        Ok(u64::from_be_bytes(bytes))
    };
    let count = usize::try_from(read_u64(&mut cursor)?).map_err(|_| ())?;
    let mut values = HashMap::with_capacity(count);
    for _ in 0..count {
        let key_len = usize::try_from(read_u64(&mut cursor)?).map_err(|_| ())?;
        let value_len = usize::try_from(read_u64(&mut cursor)?).map_err(|_| ())?;
        let key_end = cursor.checked_add(key_len).ok_or(())?;
        let key = input.get(cursor..key_end).ok_or(())?.to_vec();
        cursor = key_end;
        let value_end = cursor.checked_add(value_len).ok_or(())?;
        let value = input.get(cursor..value_end).ok_or(())?.to_vec();
        cursor = value_end;
        values.insert(key, value);
    }
    (cursor == input.len()).then_some(values).ok_or(())
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
            let provider_values = deserialize_provider(&state.provider)
                .map_err(|_| error("invalid MLS provider state"))?;
            *provider
                .storage()
                .values
                .write()
                .map_err(|_| error("MLS storage lock failed"))? = provider_values;
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
            provider: serialize_provider(&values),
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

    fn two_member_group(chat_id: &str) -> (WasmMlsClient, WasmMlsClient) {
        let alice = WasmMlsClient::new("alice-device".into(), vec![]).unwrap();
        let bob = WasmMlsClient::new("bob-device".into(), vec![]).unwrap();
        alice.create_group(chat_id.into()).unwrap();
        let bootstrap: Bootstrap = serde_json::from_str(&bob.bootstrap(1).unwrap()).unwrap();
        let packages = serde_json::to_string(&bootstrap.key_packages).unwrap();
        let added: AddOutput =
            serde_json::from_str(&alice.add_members(chat_id.into(), packages).unwrap()).unwrap();
        bob.join_group(B64.decode(added.welcome).unwrap()).unwrap();
        (alice, bob)
    }

    fn wire_message(client: &WasmMlsClient, chat_id: &str, plaintext: &[u8]) -> WireOutput {
        serde_json::from_str(
            &client
                .encrypt(chat_id.into(), plaintext.to_vec())
                .unwrap(),
        )
        .unwrap()
    }

    fn process_output(client: &WasmMlsClient, chat_id: &str, message: &str) -> ProcessOutput {
        serde_json::from_str(
            &client
                .process(chat_id.into(), B64.decode(message).unwrap())
                .unwrap(),
        )
        .unwrap()
    }

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

    #[test]
    fn dm_and_group_chats_create_distinct_mls_groups() {
        let client = WasmMlsClient::new("coordinator-device".into(), vec![]).unwrap();
        let dm: GroupState =
            serde_json::from_str(&client.create_group("41".into()).unwrap()).unwrap();
        let group: GroupState =
            serde_json::from_str(&client.create_group("42".into()).unwrap()).unwrap();

        assert_ne!(dm.group_id, group.group_id);
        assert_eq!(dm.epoch, 0);
        assert_eq!(group.epoch, 0);
        let dm_members: Vec<String> =
            serde_json::from_str(&client.group_members("41".into()).unwrap()).unwrap();
        let group_members: Vec<String> =
            serde_json::from_str(&client.group_members("42".into()).unwrap()).unwrap();
        assert_eq!(dm_members, vec!["coordinator-device"]);
        assert_eq!(group_members, vec!["coordinator-device"]);
    }

    #[test]
    fn add_update_and_remove_commits_cover_every_participant_device() {
        let chat_id = "multi-device-group";
        let alice = WasmMlsClient::new("alice-device".into(), vec![]).unwrap();
        let bob_phone = WasmMlsClient::new("bob-phone".into(), vec![]).unwrap();
        let bob_browser = WasmMlsClient::new("bob-browser".into(), vec![]).unwrap();
        alice.create_group(chat_id.into()).unwrap();

        let phone_bootstrap: Bootstrap =
            serde_json::from_str(&bob_phone.bootstrap(1).unwrap()).unwrap();
        let browser_bootstrap: Bootstrap =
            serde_json::from_str(&bob_browser.bootstrap(1).unwrap()).unwrap();
        let packages = serde_json::to_string(&vec![
            phone_bootstrap.key_packages[0].clone(),
            browser_bootstrap.key_packages[0].clone(),
        ])
        .unwrap();
        let added: AddOutput =
            serde_json::from_str(&alice.add_members(chat_id.into(), packages).unwrap()).unwrap();
        assert_eq!(added.epoch, 1);
        let welcome = B64.decode(&added.welcome).unwrap();
        bob_phone.join_group(welcome.clone()).unwrap();
        bob_browser.join_group(welcome).unwrap();

        for client in [&alice, &bob_phone, &bob_browser] {
            let members: Vec<String> =
                serde_json::from_str(&client.group_members(chat_id.into()).unwrap()).unwrap();
            assert_eq!(members.len(), 3);
            assert!(members.contains(&"alice-device".to_string()));
            assert!(members.contains(&"bob-phone".to_string()));
            assert!(members.contains(&"bob-browser".to_string()));
        }

        let alice_update: WireOutput =
            serde_json::from_str(&alice.self_update(chat_id.into()).unwrap()).unwrap();
        assert_eq!(alice_update.epoch, 2);
        let alice_commit = B64.decode(alice_update.message).unwrap();
        bob_phone
            .process(chat_id.into(), alice_commit.clone())
            .unwrap();
        bob_browser.process(chat_id.into(), alice_commit).unwrap();

        let phone_update: WireOutput =
            serde_json::from_str(&bob_phone.self_update(chat_id.into()).unwrap()).unwrap();
        assert_eq!(phone_update.epoch, 3);
        let phone_commit = B64.decode(phone_update.message).unwrap();
        alice.process(chat_id.into(), phone_commit.clone()).unwrap();
        bob_browser.process(chat_id.into(), phone_commit).unwrap();

        let browser_update: WireOutput =
            serde_json::from_str(&bob_browser.self_update(chat_id.into()).unwrap()).unwrap();
        assert_eq!(browser_update.epoch, 4);
        let browser_commit = B64.decode(browser_update.message).unwrap();
        alice
            .process(chat_id.into(), browser_commit.clone())
            .unwrap();
        bob_phone.process(chat_id.into(), browser_commit).unwrap();

        let remove_phone: WireOutput = serde_json::from_str(
            &alice
                .remove_devices(chat_id.into(), r#"["bob-phone"]"#.into())
                .unwrap(),
        )
        .unwrap();
        assert_eq!(remove_phone.epoch, 5);
        bob_browser
            .process(chat_id.into(), B64.decode(remove_phone.message).unwrap())
            .unwrap();
        let remaining: Vec<String> =
            serde_json::from_str(&alice.group_members(chat_id.into()).unwrap()).unwrap();
        assert_eq!(remaining, vec!["alice-device", "bob-browser"]);

        let remove_browser: WireOutput = serde_json::from_str(
            &alice
                .remove_devices(chat_id.into(), r#"["bob-browser"]"#.into())
                .unwrap(),
        )
        .unwrap();
        assert_eq!(remove_browser.epoch, 6);
        let remaining: Vec<String> =
            serde_json::from_str(&alice.group_members(chat_id.into()).unwrap()).unwrap();
        assert_eq!(remaining, vec!["alice-device"]);
    }

    #[test]
    fn epoch_changes_after_add_device_revocation_and_participant_leave() {
        let chat_id = "membership-epoch-group";
        let coordinator = WasmMlsClient::new("owner-device".into(), vec![]).unwrap();
        let member_phone = WasmMlsClient::new("member-phone".into(), vec![]).unwrap();
        let member_browser = WasmMlsClient::new("member-browser".into(), vec![]).unwrap();
        let initial: GroupState =
            serde_json::from_str(&coordinator.create_group(chat_id.into()).unwrap()).unwrap();
        assert_eq!(initial.epoch, 0);

        let phone: Bootstrap =
            serde_json::from_str(&member_phone.bootstrap(1).unwrap()).unwrap();
        let browser: Bootstrap =
            serde_json::from_str(&member_browser.bootstrap(1).unwrap()).unwrap();
        let packages = serde_json::to_string(&vec![
            phone.key_packages[0].clone(),
            browser.key_packages[0].clone(),
        ])
        .unwrap();
        let add: AddOutput = serde_json::from_str(
            &coordinator
                .add_members(chat_id.into(), packages)
                .unwrap(),
        )
        .unwrap();
        assert_eq!(add.epoch, initial.epoch + 1, "Add Commit must advance epoch");

        let revoke: WireOutput = serde_json::from_str(
            &coordinator
                .remove_devices(chat_id.into(), r#"["member-phone"]"#.into())
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            revoke.epoch,
            add.epoch + 1,
            "device revocation Remove Commit must advance epoch"
        );

        let leave: WireOutput = serde_json::from_str(
            &coordinator
                .remove_devices(chat_id.into(), r#"["member-browser"]"#.into())
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            leave.epoch,
            revoke.epoch + 1,
            "participant leave Remove Commit must advance epoch"
        );
        let remaining: Vec<String> = serde_json::from_str(
            &coordinator.group_members(chat_id.into()).unwrap(),
        )
        .unwrap();
        assert_eq!(remaining, vec!["owner-device"]);
    }

    #[test]
    fn replay_and_duplicate_application_messages_are_rejected() {
        let chat_id = "replay-group";
        let (alice, bob) = two_member_group(chat_id);
        let message = wire_message(&alice, chat_id, b"deliver exactly once");

        assert!(matches!(
            process_output(&bob, chat_id, &message.message),
            ProcessOutput::Application { epoch: 1, .. }
        ));
        assert!(
            bob.process(chat_id.into(), B64.decode(&message.message).unwrap())
                .is_err(),
            "replaying identical MLS ciphertext must be rejected"
        );
    }

    #[test]
    fn application_messages_can_be_delivered_out_of_order_once() {
        let chat_id = "application-reorder-group";
        let (alice, bob) = two_member_group(chat_id);
        let first = wire_message(&alice, chat_id, b"first");
        let second = wire_message(&alice, chat_id, b"second");

        let second_output = process_output(&bob, chat_id, &second.message);
        let first_output = process_output(&bob, chat_id, &first.message);
        assert!(matches!(
            second_output,
            ProcessOutput::Application { epoch: 1, .. }
        ));
        assert!(matches!(
            first_output,
            ProcessOutput::Application { epoch: 1, .. }
        ));
        assert!(
            bob.process(chat_id.into(), B64.decode(first.message).unwrap())
                .is_err(),
            "an out-of-order message must still be consumable only once"
        );
    }

    #[test]
    fn delayed_old_epoch_application_is_rejected_after_commit() {
        let chat_id = "delayed-old-epoch-group";
        let (alice, bob) = two_member_group(chat_id);
        let delayed = wire_message(&alice, chat_id, b"epoch one");
        let update: WireOutput =
            serde_json::from_str(&alice.self_update(chat_id.into()).unwrap()).unwrap();

        assert!(matches!(
            process_output(&bob, chat_id, &update.message),
            ProcessOutput::Commit { epoch: 2 }
        ));
        assert!(
            bob.process(chat_id.into(), B64.decode(delayed.message).unwrap())
                .is_err(),
            "an application delayed past its epoch must be rejected"
        );
    }

    #[test]
    fn future_epoch_application_waits_for_the_missing_commit() {
        let chat_id = "future-epoch-group";
        let (alice, bob) = two_member_group(chat_id);
        let update: WireOutput =
            serde_json::from_str(&alice.self_update(chat_id.into()).unwrap()).unwrap();
        let future = wire_message(&alice, chat_id, b"epoch two");

        assert!(
            bob.process(chat_id.into(), B64.decode(&future.message).unwrap())
                .is_err(),
            "an application from a future epoch must be rejected until its Commit arrives"
        );
        assert!(matches!(
            process_output(&bob, chat_id, &update.message),
            ProcessOutput::Commit { epoch: 2 }
        ));
        assert!(matches!(
            process_output(&bob, chat_id, &future.message),
            ProcessOutput::Application { epoch: 2, .. }
        ));
    }

    #[test]
    fn reordered_commit_is_rejected_then_applies_after_the_missing_commit() {
        let chat_id = "commit-reorder-group";
        let (alice, bob) = two_member_group(chat_id);
        let epoch_two: WireOutput =
            serde_json::from_str(&alice.self_update(chat_id.into()).unwrap()).unwrap();
        let epoch_three: WireOutput =
            serde_json::from_str(&alice.self_update(chat_id.into()).unwrap()).unwrap();

        assert!(
            bob.process(chat_id.into(), B64.decode(&epoch_three.message).unwrap())
                .is_err(),
            "Commit for epoch three must not skip the epoch two Commit"
        );
        assert!(matches!(
            process_output(&bob, chat_id, &epoch_two.message),
            ProcessOutput::Commit { epoch: 2 }
        ));
        assert!(matches!(
            process_output(&bob, chat_id, &epoch_three.message),
            ProcessOutput::Commit { epoch: 3 }
        ));
    }
}
