# Backend opaque-storage boundary

The backend persists message traffic only in `mls_envelopes.payload`. That
column contains MLS wire bytes and is never parsed by application code.

Migration `20260805_20` permanently removes the legacy `messages` and
`message_receipts` tables, the group-name column and the message sequence from
`chats`. Existing plaintext rows are discarded because server-readable data
cannot be authenticated and converted into MLS ciphertext after the fact.

The server retains only delivery metadata required for routing and abuse
controls: chat membership, sender/recipient device IDs, MLS epoch, envelope
type, payload hash, timestamps and opaque encrypted attachment objects.

Group names, message bodies, mutations, replies, reactions, read receipts,
attachment filenames/MIME types and attachment file keys are MLS application
data. Clients decrypt and interpret them locally. Group creation accepts
membership/routing options only; a `name` property is rejected. Client
WebSocket frames are rejected so the legacy plaintext and receipt channel
cannot be re-enabled accidentally.

Encrypted attachment uploads are scoped to a chat for download authorization.
The AES file key and original file metadata travel inside the MLS application
message and are never submitted to the media endpoint.
