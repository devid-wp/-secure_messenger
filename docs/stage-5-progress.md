# Stage 5: E2EE implementation status

## Protocol

Secure Messenger uses MLS 1.0 (RFC 9420) with OpenMLS 0.8.1. A direct message
is an MLS group with the devices of two users; a normal group contains every
active device of every member. Signal-style prekeys map to one-time MLS
`KeyPackage` objects.

The selected ciphersuite is:

```text
MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519
```

No custom cryptographic primitive may be implemented in JavaScript or Python.

## Implemented server foundation

- Every authenticated login creates a distinct device record.
- A device can publish one immutable public identity key.
- Identity fingerprints use SHA-256 and are available to authenticated clients.
- A device identity cannot silently change. A new identity requires a new
  device, allowing clients to display a key-change warning.
- Devices publish bounded, expiring, opaque MLS KeyPackages.
- Claiming consumes at most one KeyPackage per active target device.
- Claims are transactional and record the requesting device.
- Revoked devices disappear from discovery and cannot authenticate.
- The server stores no private identity key or KeyPackage private material.

## Implemented message path

- Native OpenMLS group creation and deterministic per-chat GroupId.
- Multi-device Add Commit and targeted Welcome delivery.
- Persistent epoch transitions for Add, Remove and self Update commits.
- Private MLS application messages on both supported runtimes: Tauri invokes
  native Rust and the PWA invokes OpenMLS WASM in a dedicated Web Worker.
- Opaque server-side `mls_envelopes` storage. The delivery service stores MLS
  wire bytes, epoch and routing metadata, never application plaintext.
- OpenMLS replay/duplicate rejection and out-of-order application processing.
- DPAPI protects desktop state; the PWA uses an AES-GCM encrypted IndexedDB
  envelope and a non-extractable WebCrypto key. Both caches are keyed by
  ciphertext hash so consumed generations remain readable after restart.
- Device revocation emits and publishes an MLS Remove Commit for every local
  group containing the revoked device.
- Automatic self Update Commit after every 100 sent application messages.
- The legacy WebSocket plaintext sender and plaintext edit endpoint fail closed.
- Browser sending fails closed unless WebAssembly, Worker, IndexedDB and
  WebCrypto are all available and the encrypted MLS vault opens successfully.

## Security gates still open

The product MUST NOT claim working E2EE until all of these are complete:

- encrypted attachments and encrypted backup export;
- safety number and QR verification;
- device-change warnings and group epoch updates after revocation;
- RFC/OpenMLS known-answer vectors, replay/reorder/duplicate tests, fuzzing, and
  an independent review of the Rust/WASM boundary.

Text messages now use the MLS envelope transport in desktop and PWA clients.
Attachments keep their separately documented encrypted-storage mode and are
not yet covered by the full E2EE claim. Independent review and fuzzing remain
release gates.
