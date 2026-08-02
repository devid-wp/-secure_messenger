# Local vault backup and recovery policy

Status: **v1 policy; encrypted backup is not implemented**

## Protected local data

The desktop `secure-vault` contains three different classes of data:

| File | Purpose | Backup policy |
| --- | --- | --- |
| `master-key.dpapi` | Device master key protected for the Windows user | No standalone restore |
| `openmls-state.dpapi` | Private serialized OpenMLS state protected by DPAPI | No rollback or standalone restore |
| `session.dpapi` | Rotating login refresh session | Never backed up; obtain a new session by signing in |

These files are an integrity unit even where the current implementation does
not yet consume the master key for OpenMLS state encryption. Copying one file
without the others is not a supported backup.

## Current v1 policy

- The application does not create or upload backups of the local vault.
- The server never receives private MLS state, the device master key, or an
  export of either value.
- Generic filesystem or cloud-sync copies are not a supported recovery path.
  DPAPI protection is bound to Windows security context, and restoring an old
  MLS snapshot can roll a group back to an obsolete epoch.
- A refresh session is replaceable authentication state, not user data. It is
  excluded from every future backup format.
- Corrupt, truncated, or unsupported vault files fail closed and remain
  unchanged. The client must not silently create a replacement over them.
- Deleting or resetting cryptographic state requires an explicit user action
  that explains that old encrypted history may become unavailable.

## Recovery outcomes

| Situation | Supported action | Old E2EE history |
| --- | --- | --- |
| Session file lost | Sign in and create a fresh session | Unchanged |
| One device lost | Revoke it from another trusted device and add a replacement through MLS commits | Available only where another device retains it |
| Local MLS state corrupt | Preserve the file, stop using that state, and recover/rejoin from a trusted device | Not promised on the affected device |
| All devices and keys lost | Create a new device identity after account recovery | Permanently unavailable in v1 |
| Unsupported storage schema | Upgrade to software that supports it; never downgrade or rewrite it | Preserved but unavailable to the old client |

Account recovery and cryptographic recovery are separate. Password reset or a
recovery code can return control of the account, but cannot recreate deleted
MLS secrets.

## Requirements before encrypted backup can ship

A future backup feature requires a separate security design and review. At a
minimum it must provide:

1. an independent random recovery secret that is not derived only from the
   account password;
2. client-side authenticated encryption and a versioned manifest;
3. atomic snapshots of all required cryptographic state;
4. rollback detection tied to MLS group epochs;
5. explicit opt-in, recovery-secret confirmation, and rate limiting;
6. restore tests covering corruption, partial snapshots, wrong credentials,
   old schemas, and revoked devices;
7. a rule that neither plaintext keys nor refresh sessions enter logs, crash
   reports, analytics, or server-side storage.

Until all requirements are implemented, the UI must not advertise local file
copies or cloud sync as a way to recover encrypted history.
