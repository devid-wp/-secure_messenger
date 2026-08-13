# Secure Messenger

Browser-only FastAPI and React messenger with an OpenMLS WebAssembly
cryptographic boundary. The server stores and routes opaque MLS envelopes and
encrypted attachment bytes; message and attachment plaintext exists only in an
unlocked browser endpoint.

## Open as a Windows application

Double-click:

```text
Secure Messenger.bat
```

On first launch, paste the HTTPS address of the hosted messenger. The address
is stored under `%LOCALAPPDATA%\SecureMessenger\web-app-url.txt`; subsequent
launches open immediately.

The launcher uses Microsoft Edge or Google Chrome application mode, so the
messenger gets its own window without browser tabs or an address bar. If neither
browser is found, it opens in the Windows default browser. Docker, WSL, Python,
Node.js, Rust and administrator rights are not required for users.

To change the saved site, delete:

```text
%LOCALAPPDATA%\SecureMessenger\web-app-url.txt
```

## Installable PWA

The hosted frontend includes a web-app manifest, application icons and a
service worker. On HTTPS deployments, Edge and Chrome can install it directly
from the browser menu. An installed PWA receives its own Start menu entry and
taskbar icon and does not require the BAT launcher afterward.

The PWA runs pinned OpenMLS WebAssembly in a dedicated Worker. Its MLS state is
AES-GCM encrypted in IndexedDB by a random DEK wrapped with a
passphrase-derived, non-extractable WebCrypto key. It uses the same opaque MLS
envelope transport in every supported browser.

## Development

Supported toolchain: Python 3.12.11, Node.js 20.19.0 with npm 10.8.2, and
Rust 1.88.0 with the `wasm32-unknown-unknown` target. Dependency installation
must use the committed lockfiles; do not use unpinned installation commands.

```shell
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
npm test

cd ..
python -m pytest
```

Backend development and deployment use standard FastAPI, Alembic and pytest
commands. Read the current [installation and production runbook](docs/production.md),
[backup/release procedure](docs/backup-and-release.md), and
[security model](docs/security.md) before deployment.
