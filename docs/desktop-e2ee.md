# Desktop E2EE implementation

Secure Messenger is introducing a Tauri 2 desktop client around the existing
React interface. The native Rust boundary lives in `frontend/src-tauri`; the web
client remains available for UI development but must not claim E2EE.

## Current milestone

- Tauri desktop shell and a minimal capability policy.
- A lazy JavaScript bridge that does not load Tauri APIs in a browser.
- A Rust `crypto_status` command that deliberately returns `available: false`.
- No fallback encryption. Sending must be gated when the MLS service is added.

The current milestone does **not** encrypt messages and is not an E2EE release.

## Windows prerequisites

1. Rust stable through rustup.
2. Microsoft C++ Build Tools with **Desktop development with C++** and a Windows
   SDK. This supplies the MSVC `link.exe` required by Tauri.
3. Microsoft Edge WebView2 (normally already present on supported Windows).

Run the desktop development shell from `frontend`:

```powershell
npm run desktop:dev
```

## Next cryptographic milestone

Add an isolated Rust `mls` module pinned to OpenMLS 0.8.1. Its first vertical
slice must create a device credential and KeyPackage, persist private state only
in native protected storage, create a two-device MLS group, and round-trip one
application message. FastAPI receives only the serialized MLS message.

Do not add a home-grown AES fallback and do not expose private key material over
Tauri IPC.
