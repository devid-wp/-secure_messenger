# Local vault backup and recovery policy

Status: **encrypted native backup v1 implemented**

## Protected local data

The desktop `secure-vault` contains three different classes of data:

| File | Purpose | Backup policy |
| --- | --- | --- |
| `master-key.dpapi` | Device master key protected for the Windows user | Included in encrypted backup |
| `openmls-state.dpapi` | Private serialized OpenMLS state protected by DPAPI | Included in encrypted backup |
| `mls-signature-key.dpapi` | MLS device signing key protected by DPAPI | Included in encrypted backup |
| `session.dpapi` | Rotating login refresh session | Never backed up; obtain a new session by signing in |

These files are an integrity unit even where the current implementation does
not yet consume the master key for OpenMLS state encryption. Copying one file
without the others is not a supported backup.

## Backup format and recovery

- `vault_backup` creates a versioned `SMBACKUP` envelope encrypted and
  authenticated with XChaCha20-Poly1305 and returns a fresh 256-bit recovery
  key as 64 hexadecimal characters. The backup file and recovery key must be
  stored separately.
- Backup creation uses atomic create-new semantics and never overwrites an
  existing destination.
- `vault_restore` authenticates and fully parses the backup before writing
  secrets. It accepts only an empty cryptographic vault, preventing silent
  rollback over active MLS state.
- Restored secrets are protected again with DPAPI for the current Windows user.
- The application does not upload backups or recovery keys. The server never
  receives private MLS state, the device master key, or an export of either.
- A refresh session is replaceable authentication state, not user data. It is
  excluded from the backup format; the user signs in again after recovery.
- Corrupt, truncated, or unsupported vault files fail closed and remain
  unchanged. The client must not silently create a replacement over them.
- Deleting or resetting cryptographic state requires an explicit user action
  that explains that old encrypted history may become unavailable.

## Recovery outcomes

| Situation | Supported action | Old E2EE history |
| --- | --- | --- |
| Session file lost | Sign in and create a fresh session | Unchanged |
| One device lost | Revoke it from another trusted device and add a replacement through MLS commits | Available only where another device retains it |
| Local MLS state corrupt | Preserve the file, move the damaged vault aside through an explicit reset flow, then restore a known-good backup or rejoin from a trusted device | Available up to the restored snapshot, subject to MLS epoch validity |
| All devices and keys lost | Create a new device identity after account recovery | Permanently unavailable in v1 |
| Unsupported storage schema | Upgrade to software that supports it; never downgrade or rewrite it | Preserved but unavailable to the old client |

Account recovery and cryptographic recovery are separate. Password reset or a
recovery code can return control of the account, but cannot recreate deleted
MLS secrets.

## Operational requirements

The caller/UI must:

1. require explicit backup and restore actions;
2. make the user confirm that the recovery key was stored separately;
3. never place the recovery key, plaintext keys, or refresh sessions in logs,
   crash reports, analytics, clipboard history, or server-side storage;
4. explain that restoring an old MLS snapshot can require rejoining groups and
   cannot recover messages newer than the snapshot;
5. use an explicit reset/move-aside flow for a corrupt existing vault. The
   restore command deliberately refuses to overwrite it.
