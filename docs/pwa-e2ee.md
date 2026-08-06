# PWA E2EE runtime

The installable PWA uses the MLS 1.0 ciphersuite and pinned OpenMLS 0.8.1.
It does not use a JavaScript cryptographic fallback or a native desktop runtime.

## Boundary

`mls.worker.js` is the only browser component that imports the generated
OpenMLS WebAssembly module. React communicates with it through request/response
messages. Signature keys, KeyPackage private material, epoch secrets and the
serialized provider state are never returned to React.

The worker persists a versioned OpenMLS state envelope in IndexedDB. Before a
state write it encrypts the complete envelope with AES-256-GCM and binds it to
the server-issued device ID using additional authenticated data. A random
256-bit DEK is wrapped by a key derived from the local passphrase using
PBKDF2-HMAC-SHA-256 (600,000 iterations and a random 128-bit salt). Neither the
passphrase nor its derived key is stored. Every mutation is persisted before the worker
acknowledges the operation. Logout drops the WASM instance and terminates the
worker.

Vault v2 uses independent random nonces for DEK wrapping and state encryption.
Legacy v1 records are retained until the migrated v2 record has been decrypted
successfully.

This protects at-rest browser storage and prevents ordinary application code
from reading the vault key. It does not protect against a compromised browser,
same-origin script execution or an attacker controlling the unlocked profile.
The production CSP therefore permits only same-origin scripts and workers and
contains no third-party font or script resources.

## Reproducible build

The wrapper pins OpenMLS, its provider and wasm-bindgen in
`frontend/src-wasm/Cargo.lock`. Build it with:

```powershell
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.126 --locked
cd frontend
npm ci
npm run build
```

The Docker build and `pwa-mls-wasm.yml` CI workflow compile the WASM artifact
from source. Generated glue is deliberately not committed.

## Offline behavior

The service worker may cache same-origin immutable JS, Worker and WASM assets.
It never intercepts or caches `/api/` requests. Decrypted message content is
held by the renderer only for display; persistent plaintext outbox/history
storage is not used.
