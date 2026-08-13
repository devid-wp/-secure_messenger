# Security model and incident response

## E2EE model

Messages, edits, deletes, reactions, receipts, group events, and attachments
use versioned MLS application payloads in the browser. Attachments are encrypted
client-side before upload. The backend routes opaque MLS envelopes and encrypted
bytes; it must not receive message or file plaintext.

Browser MLS state is held in an IndexedDB vault. A random data-encryption key
is wrapped with a passphrase-derived WebCrypto key. The passphrase is not stored
in IndexedDB, logs, or network requests. Lock/logout clears unlocked key state;
another tab receives lock events through `BroadcastChannel`.

## Important limits

- The vault protects data while locked. It does **not** protect an already
  unlocked application from XSS, a hostile extension, or a compromised browser.
- A forgotten local vault passphrase cannot be recovered by the server or email.
- E2EE does not hide all metadata: the service can observe accounts, devices,
  chat membership/delivery timing, object sizes, and network-level metadata.
- Only Chrome/Edge Chromium PWA are supported for release. Verify safety codes
  before trusting a new or changed contact device.

## Incident response

1. For a lost device, use another unlocked device to revoke it. Confirm the
   resulting MLS Remove Commit and verify the new epoch is active.
2. For a suspected account/session compromise, revoke affected devices, rotate
   service credentials, preserve audit artifacts without payloads, and force
   affected users to authenticate again.
3. For a suspected XSS or frontend supply-chain incident, immediately stop
   deployment, invalidate the affected build, publish a clean signed build,
   and tell users to lock/restart and verify device safety codes.
4. For database or object-storage loss, restore only through the staging-tested
   runbook. Do not overwrite production before a verified staging restore.
5. Preserve timestamps, image digests, CI audit reports, and alert IDs. Never
   paste messages, vault records, keys, tokens, or full encrypted payloads into
   tickets or logs.
