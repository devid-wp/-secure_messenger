# Browser compatibility

The supported platform is the browser PWA; there is no Tauri or native desktop
cryptographic runtime. Current stable Chromium and Firefox are release targets.
An installed Chromium PWA and the same application in a normal tab use the same
Worker/WASM/vault implementation. Safari is not a release target until its
IndexedDB, module Worker, service-worker and WebAssembly flows are covered by
the same automated and manual matrix.

Required browser capabilities are WebAssembly, module Workers, WebCrypto
AES-GCM/PBKDF2, IndexedDB, Service Worker, `crypto.getRandomValues`, Blob and
stream/file APIs. Sending fails closed when the MLS runtime or unlocked vault
is unavailable. Private browsing, storage eviction, profile cleanup and a lost
passphrase can permanently remove the only copy of local MLS state.

Test each release in Chromium and Firefox with two tabs, two independent
profiles, offline/reconnect, reload after send, device revocation, a deliberately
corrupt IndexedDB record, and a large encrypted attachment. Clearing site data
is equivalent to losing the local device unless another trusted device can add
a replacement; the server cannot reconstruct old MLS secrets.
