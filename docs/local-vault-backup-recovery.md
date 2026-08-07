# Local vault backup and recovery policy

Status: **passphrase-protected browser vault v2 implemented**

## Purpose

The browser-only client keeps the MLS state and the device identity key in
IndexedDB under the user's profile. v2 binds that vault to a user-supplied
passphrase so a copy of the IndexedDB file or its tables does not reveal
plaintext state on its own. v1, which stored a non-extractable CryptoKey
inside IndexedDB without password protection, is supported only as a
migration source.

## v2 vault schema

Each device's vault is a single record in the `state` object store of the
`secure-messenger-mls-v1` IndexedDB database:

```json
{
  "version": 2,
  "device_id": "<device id>",
  "kdf": {
    "name": "PBKDF2-HMAC-SHA-256",
    "salt": "<base64 16 bytes>",
    "parameters": { "iterations": 600000 }
  },
  "wrapped_dek": "<AES-256-GCM ciphertext of the DEK>",
  "wrap_iv": "<base64 12 bytes>",
  "state_ciphertext": "<AES-256-GCM ciphertext of the MLS state>",
  "state_iv": "<base64 12 bytes>",
  "updated_at": "<ISO-8601>"
}
```

Cryptographic wiring:

- A random 256-bit Data Encryption Key (DEK) is generated for the device
  when the vault is created. The DEK never leaves WebCrypto and is marked
  non-extractable, so the JS worker holds an opaque handle to it only.
- The user passphrase runs through PBKDF2-HMAC-SHA-256 with the record's
  salt and stored iteration count. The derived key is also non-extractable
  and is used solely as a Key Encryption Key (KEK) to wrap the DEK.
- Wrapping uses AES-256-GCM with a fresh 12-byte nonce and AAD
  `secure-messenger:v2:<device_id>:dek`.
- MLS state encryption uses the DEK with a fresh 12-byte nonce and AAD
  `secure-messenger:v2:<device_id>:state`.
- The passphrase itself and the derived KEK are never persisted. A v2
  vault unlock re-derives the KEK on every call and zeroes the temporary
  raw DEK bytes as soon as the unwrap finishes.

## Properties the v2 scheme MUST satisfy

| Property | How it is enforced |
| --- | --- |
| Random 256-bit DEK per device | `crypto.getRandomValues` of 32 bytes per `wrapNewDek` call |
| MLS state encrypted with DEK (AES-256-GCM) | `crypto.subtle.encrypt` with the DEK, AAD binds device + purpose |
| Passphrase runs through a KDF | PBKDF2-HMAC-SHA-256, 600 000 iterations |
| Derived key used only to wrap the DEK | The KEK is the only key that ever touches `wrapped_dek` |
| Passphrase and derived key not persisted | `importKey` with `extractable=false`, no IndexedDB writes |
| Unique salt per installation | 16-byte salt, regenerated for every `wrapNewDek` call |
| Unique KDF parameters per installation | Iteration count stored per record; future cost changes ride along |
| Unique nonce per AES-GCM encryption | 12-byte `wrap_iv` and 12-byte `state_iv`, regenerated per call |
| Device ID + version in AAD | `vaultAad` prefixes `secure-messenger:v2:` |

## v1 → v2 migration

v1 stored the AES-GCM key in the `keys` object store of the same database.
The migration flow is:

1. Decrypt the v1 ciphertext under the v1 IndexedDB key and read the
   plaintext MLS state.
2. Prompt for a passphrase, run `wrapNewDek`, then re-encrypt the state
   under the new DEK.
3. Write the v2 record over the v1 one and delete the legacy `keys`
   entry atomically.

If the v2 write fails for any reason, the worker restores the v1 record
and zeroes the temporary plaintext buffer.

## Backup and recovery

- The browser vault is intentionally portable only via the user's
  passphrase. There is no automatic upload, no recovery key, and no
  out-of-band escrow in v2.
- A refresh session is replaceable authentication state, not user data.
  It is excluded from any backup; the user signs in again after recovery.
- Restoring the vault on a new browser profile requires the passphrase;
  there is no supported path that recovers the DEK without it.
- Corrupt, truncated, or unsupported vault records fail closed. The
  client MUST NOT silently create a replacement over them.
- Deleting or resetting cryptographic state requires an explicit user
  action that explains that old encrypted history may become unavailable.

## Recovery outcomes

| Situation | Supported action | Old E2EE history |
| --- | --- | --- |
| Session file lost | Sign in and create a fresh session | Unchanged |
| One device lost | Revoke it from another trusted device and add a replacement through MLS commits | Available only where another device retains it |
| Passphrase forgotten | No recovery in v2 — the vault cannot be unlocked, MLS state is destroyed | Permanently unavailable |
| Browser profile wiped but passphrase known | Create a new device identity and rejoin groups | Permanently unavailable; design choice for v1.0 |
| Local MLS state corrupt | Move the damaged vault aside through an explicit reset flow | Available up to the last good snapshot, subject to MLS epoch validity |
| All devices and keys lost | Create a new device identity after account recovery | Permanently unavailable in v1 |

Account recovery and cryptographic recovery are separate. Password reset
or a recovery code can return control of the account but cannot recreate
a lost DEK or unwrap the MLS state.

## Operational requirements

The caller/UI must:

1. require an explicit unlock action and never cache the unlocked DEK
   longer than the lifetime of the Web Worker session;
2. refuse passphrases shorter than the documented minimum (10 characters);
3. never place the passphrase, the derived KEK, the DEK or any unwrapped
   plaintext in logs, crash reports, analytics, clipboard history, or
   server-side storage;
4. explain that a forgotten passphrase destroys the local MLS state;
5. use an explicit reset flow for a corrupt vault. The client MUST NOT
   silently overwrite it.