# Browser and PWA support

The release target is a modern desktop or mobile browser with WebCrypto,
IndexedDB, Web Workers and WebAssembly enabled. JavaScript must be enabled.

| Browser | Secure Messenger in browser | Installable PWA | Release status |
| --- | --- | --- | --- |
| Chromium / Chrome / Edge (current stable) | Supported | Supported | Release target |
| Firefox (current stable) | Not release-supported | Not release-supported | Compatibility work required |
| Safari / iOS browsers | Not yet release-supported | Not release-supported | Do not advertise |
| Embedded webviews, legacy Chromium, private mode with disabled IndexedDB | Unsupported | Unsupported | Blocked by required browser storage/runtime |

The browser suite runs the core E2EE lifecycle in Chromium. Firefox is excluded
from release support until its vault reload/unlock lifecycle passes the same
suite. PWA installation is promised only where the browser exposes its own
installation UI; the cryptographic protocol and vault do not depend on
installation.

## Responsive baseline

The UI is release-tested at desktop width and a 390px mobile viewport. The
conversation list and composer must remain usable without horizontal scrolling.

## Privacy diagnostics

Production frontend code does not transmit telemetry or third-party analytics.
It must not write message plaintext, attachment plaintext, tokens, vault state,
keys, or component stacks to the browser console. Backend API errors return
stable user-facing messages and must not include request bodies, tokens, keys,
or ciphertext in logs.
