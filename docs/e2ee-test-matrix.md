# E2EE security test matrix

This matrix is the release-gate inventory for the MLS scenarios. A scenario is
not complete merely because it is implemented: its listed automated test must
run in `.github/workflows/release-security.yml`.

| Scenario | Unit / integration coverage | Independent-profile browser E2E |
|---|---|---|
| Add, Update and Remove Commit for every participant device | `frontend/src-wasm/src/lib.rs::add_update_and_remove_commits_cover_every_participant_device` | `frontend/e2e/e2ee.spec.js`: Alice, Bob and Alice's second device execute Add → Update → Remove |
| Epoch advances after add, revoke and participant leave | `epoch_changes_after_add_device_revocation_and_participant_leave` | Exact consecutive Add, Update and Remove envelope epochs are asserted |
| Replay and duplicate | `replay_and_duplicate_application_messages_are_rejected` | — |
| Reordered application delivery | `application_messages_can_be_delivered_out_of_order_once` | — |
| Delayed old epoch | `delayed_old_epoch_application_is_rejected_after_commit` | Revoked offline profile rejects the post-removal application |
| Future epoch and missing Commit | `future_epoch_application_waits_for_the_missing_commit` | — |
| Reordered Commit | `reordered_commit_is_rejected_then_applies_after_the_missing_commit` | — |
| Corrupted ciphertext produces no plaintext | `corrupted_ciphertext_is_rejected_without_plaintext` | — |
| Fork / transcript mismatch | `forked_commit_with_mismatched_transcript_is_rejected` | — |
| Ambiguous error blocks send until successful explicit resync | `frontend/test/mlsSendPolicy.test.js` | — |
| Safety code uses the exact verified MLS credential/device set | `frontend/test/safetyCode.test.js`; identity immutability in `tests/test_e2ee_delivery.py` | New independent device produces the persistent credential/device-set alert |
| Application payload versions, strict fields, types and limits | `frontend/test/applicationPayload.test.js` | — |
| Canonical encoding and preflight before UI state | `frontend/test/applicationPayload.test.js` | — |
| Unauthenticated envelope fields cannot change rendered content | `frontend/test/messageLifecycle.test.js` | Network-body sentinels verify plaintext never enters delivery requests |
| Device revocation removes access to later epochs | Rust membership tests and `tests/test_e2ee_delivery.py` | Offline revoked profile rejects ciphertext from the Remove-Commit epoch |

The browser E2E uses separate Playwright `BrowserContext` instances. They have
independent cookies, IndexedDB vaults, MLS state and device credentials. The
same test runs in Chromium and Firefox with one worker to avoid sharing backend
fixtures between cases.

## Gate commands

The release workflow must pass all of the following without skipped security
jobs:

```text
python -m pytest
npm test
cargo test --locked
npm run test:e2e
```

The E2E gate additionally builds the production WASM application before
running both configured browser projects.
