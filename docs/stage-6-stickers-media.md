# Stage 6: stickers and encrypted media

## Implemented

- Typed messages: `text`, `sticker`, `image`, `file`, and `system`.
- Existing `user` messages migrate safely to `text`.
- Public and private sticker packs with ownership and subscriptions.
- A Sticker Studio for creating packs and changing visibility.
- PNG/WebP validation, a 5 MB source limit, square preview, crop/scale control,
  and server-side normalization to a 512x512 lossless WebP.
- Sticker delivery through the idempotent WebSocket path.
- A 50 MB encrypted-attachment upload API.
- Local object storage for native development and S3-compatible storage for
  production. The Docker stack uses MinIO.
- Authenticated media download. Attachment ciphertext is available only to its
  owner and members of the chat containing the attachment message.

## File-key boundary

The attachment table never stores a file key. An attachment message has an
opaque `key_envelope`, intended to be an MLS application ciphertext containing
the random file key and encrypted client-side metadata.

The current browser client cannot create that envelope because the OpenMLS/WASM
application-encryption layer from Stage 5 is not complete. Consequently, the
attachment button remains disabled. Sending a plaintext file key as a temporary
shortcut would defeat the E2EE design and is explicitly rejected.

The backend contract is covered by integration tests using an opaque test
envelope. This proves ciphertext-at-rest and access control, not end-to-end
secrecy of the current browser application.

## Metadata visible to the server

For attachment routing and limits, the server currently sees:

- uploader account;
- ciphertext byte length and SHA-256 digest;
- declared plaintext MIME family;
- optional image dimensions;
- cipher identifier and public nonce;
- chat membership after attachment to a message.

The original filename and file key are not stored. Once MLS application
encryption is connected, sensitive metadata should move inside `key_envelope`.

## Storage configuration

Native development:

```text
MEDIA_STORAGE_BACKEND=local
MEDIA_DIR=./media
```

S3-compatible production:

```text
MEDIA_STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://s3.example.com
S3_REGION=us-east-1
S3_BUCKET=secure-messenger-media
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
```

The bucket must remain private; downloads are proxied through the authenticated
API.

## Limits

| Object | Accepted input | Limit | Stored form |
|---|---|---:|---|
| Sticker | PNG or WebP | 5 MB | 512x512 lossless WebP |
| Attachment | client-produced ciphertext | 50 MB | opaque binary object |

Pillow fully decodes sticker input before conversion. Extensions alone are not
trusted.

## Remaining work

- OpenMLS/WASM application encryption and decryption in a Web Worker.
- Random AES-256-GCM file-key generation in the browser.
- MLS wrapping of the file key and private metadata.
- Streaming/chunked encryption for large files.
- Encrypted thumbnail generation for image messages.
- S3 lifecycle cleanup for abandoned uploads.
- Security review and test vectors for the browser-to-MLS boundary.
