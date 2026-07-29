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

## Security gates still open

The product MUST NOT claim working E2EE until all of these are complete:

- pinned OpenMLS Rust/WASM wrapper and reproducible browser build;
- encrypted local MLS state isolated in a Web Worker;
- MLS group creation, Welcome processing, Commit handling, and application
  encryption in Chromium and Firefox;
- opaque ciphertext message storage replacing server-visible content;
- regular Update/Commit scheduling for forward secrecy and PCS;
- encrypted attachments and encrypted backup export;
- safety number and QR verification;
- device-change warnings and group epoch updates after revocation;
- RFC/OpenMLS known-answer vectors, replay/reorder/duplicate tests, fuzzing, and
  an independent review of the Rust/WASM boundary.

The current frontend and existing message transport still send plaintext. This
is an intentional migration boundary, not an E2EE release.
