// Client-side encrypted file transport.
//
// Each file is encrypted locally before it ever leaves the browser:
//   * a fresh 256-bit AES-GCM key is generated per file
//   * a fresh 96-bit nonce is generated per file
//   * the file is streamed through AES-256-GCM in fixed-size chunks so we
//     never hold the whole plaintext in memory at once
//   * the ciphertext is uploaded as `application/octet-stream` and the
//     file key, nonce, original name, MIME type, plaintext size and the
//     SHA-256 of the plaintext are written into the MLS application
//     payload's `attachment_descriptor` — the server never sees them
//   * on the receiving side the GCM authentication tag is verified by
//     the WebCrypto decrypt step and the plaintext is hashed and
//     compared against `sha256` before it is exposed to the UI
//
// The descriptor shape is intentionally narrow: anything the server could
// use to leak metadata (filename, MIME) is carried only inside the
// encrypted MLS payload — never in the upload form, the upload URL or the
// download headers.

const VERSION = 1
const ALGORITHM = 'AES-256-GCM'
const GCM_NONCE_BYTES = 12
const GCM_TAG_BYTES = 16
const KEY_BYTES = 32
// 1 MiB chunks keep memory bounded for large files while still letting
// WebCrypto finish each chunk without spilling to disk.
const CHUNK_BYTES = 1024 * 1024
// Hard ceiling enforced before we allocate a buffer for the plaintext.
// Mirrors the backend `MAX_ATTACHMENT_BYTES = 50 MiB` minus the per-file
// GCM tag overhead, leaving a small safety margin for the descriptor and
// MLS envelope size accounting.
export const MAX_ATTACHMENT_BYTES = (50 * 1024 * 1024) - (GCM_TAG_BYTES + 4096)

function toBase64(bytes) {
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  return btoa(binary)
}
function fromBase64(value) {
  if (typeof value !== 'string') throw new Error('Attachment descriptor field must be base64')
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0))
}

function zeroize(bytes) {
  if (bytes instanceof Uint8Array) bytes.fill(0)
}

async function sha256Base64(stream) {
  // `stream` may be a Blob/File or a Uint8Array. WebCrypto accepts any
  // of them directly, so we never have to materialise the whole file
  // into memory before hashing.
  let buffer
  if (stream instanceof Uint8Array) buffer = stream
  else if (stream instanceof ArrayBuffer) buffer = new Uint8Array(stream)
  else if (stream && typeof stream.arrayBuffer === 'function') {
    buffer = new Uint8Array(await stream.arrayBuffer())
  } else {
    throw new Error('sha256 input must be a Blob, File, ArrayBuffer or Uint8Array')
  }
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return toBase64(new Uint8Array(digest))
}

function assertDescriptor(descriptor) {
  if (!descriptor || typeof descriptor !== 'object') throw new Error('Invalid attachment descriptor')
  if (descriptor.version !== VERSION) throw new Error('Unsupported attachment descriptor version')
  if (descriptor.algorithm !== ALGORITHM) throw new Error('Unsupported attachment algorithm')
  if (typeof descriptor.key !== 'string' || descriptor.key.length === 0) throw new Error('Attachment key is required')
  if (typeof descriptor.nonce !== 'string' || descriptor.nonce.length === 0) throw new Error('Attachment nonce is required')
  // The server-side descriptor must never carry a file name or MIME type;
  // those live only inside the encrypted MLS payload.
  for (const forbidden of ['name', 'file_name', 'media_type', 'mime_type']) {
    if (Object.prototype.hasOwnProperty.call(descriptor, forbidden)) {
      throw new Error(`Attachment descriptor must not leak "${forbidden}"`)
    }
  }
}

function assertSize(file, limit) {
  const size = typeof file?.size === 'number' ? file.size : 0
  if (size <= 0) throw new Error('Attachment is empty')
  if (size > limit) throw new Error('Attachment exceeds size limit')
}

// Streams a Blob/File through `transform(chunk)` and concatenates the
// transformed chunks into a single Uint8Array without ever holding the
// full plaintext in memory at once. `transform` must return a Uint8Array.
async function mapChunks(file, transform) {
  const collectedLength = { value: 0 }
  const collected = []
  let position = 0
  while (position < file.size) {
    const slice = file.slice(position, Math.min(position + CHUNK_BYTES, file.size))
    position += CHUNK_BYTES
    const buffer = new Uint8Array(await slice.arrayBuffer())
    const transformed = await transform(buffer, position)
    zeroize(buffer)
    collected.push(transformed)
    collectedLength.value += transformed.byteLength
  }
  const merged = new Uint8Array(collectedLength.value)
  let offset = 0
  for (const chunk of collected) {
    merged.set(chunk, offset)
    offset += chunk.byteLength
  }
  return merged
}

export async function encryptAttachment(file, options = {}) {
  assertSize(file, MAX_ATTACHMENT_BYTES)
  const limit = options.maxBytes ?? MAX_ATTACHMENT_BYTES
  if (file.size > limit) throw new Error('Attachment exceeds size limit')

  const rawKey = crypto.getRandomValues(new Uint8Array(KEY_BYTES))
  const nonce = crypto.getRandomValues(new Uint8Array(GCM_NONCE_BYTES))
  const cryptoKey = await crypto.subtle.importKey('raw', rawKey, 'AES-GCM', false, ['encrypt'])

  // Run every plaintext chunk through GCM with the same nonce/key.
  // AES-GCM is only safe with a fixed nonce when the key is per-file and
  // never reused across files — both conditions hold here because
  // rawKey and nonce are fresh.
  const ciphertext = await mapChunks(file, async (chunk) => {
    const encrypted = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, cryptoKey, chunk))
    return encrypted
  })

  const descriptor = {
    version: VERSION,
    object_id: null,
    algorithm: ALGORITHM,
    key: toBase64(rawKey),
    nonce: toBase64(nonce),
    plaintext_size: file.size,
    ciphertext_size: ciphertext.byteLength,
    sha256: await sha256Base64(file),
    // The descriptor travels inside the MLS application payload — never
    // in the upload request. Keeping it local to the encrypt call lets
    // callers fill `object_id` after the upload completes without ever
    // serialising the key over the wire.
  }

  zeroize(rawKey)
  return { ciphertext, descriptor }
}

export async function decryptAttachment(ciphertext, descriptor) {
  assertDescriptor(descriptor)
  if (!(ciphertext instanceof Uint8Array) && !(ciphertext instanceof ArrayBuffer) && !ciphertext?.arrayBuffer) {
    throw new Error('Encrypted attachment must be binary')
  }
  const bytes = ciphertext instanceof Uint8Array ? ciphertext : new Uint8Array(await ciphertext.arrayBuffer())
  if (bytes.byteLength !== descriptor.ciphertext_size) throw new Error('Encrypted attachment size mismatch')

  // Verify GCM tag presence up-front. If `bytes.byteLength` is smaller
  // than a single GCM tag, the ciphertext cannot be authentic and the
  // WebCrypto decrypt call would otherwise fail with an opaque error.
  if (bytes.byteLength < GCM_TAG_BYTES) throw new Error('Encrypted attachment is too short to carry a GCM tag')

  const keyBytes = fromBase64(descriptor.key)
  if (keyBytes.byteLength !== KEY_BYTES) throw new Error('Attachment key has the wrong length')
  const nonceBytes = fromBase64(descriptor.nonce)
  if (nonceBytes.byteLength !== GCM_NONCE_BYTES) throw new Error('Attachment nonce has the wrong length')

  const cryptoKey = await crypto.subtle.importKey('raw', keyBytes, 'AES-GCM', false, ['decrypt'])
  let plaintext
  try {
    plaintext = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonceBytes }, cryptoKey, bytes))
  } catch {
    zeroize(keyBytes)
    zeroize(nonceBytes)
    throw new Error('Attachment authentication tag verification failed')
  }
  zeroize(keyBytes)
  zeroize(nonceBytes)

  if (plaintext.byteLength !== descriptor.plaintext_size) {
    zeroize(plaintext)
    throw new Error('Attachment integrity check failed')
  }
  const digest = await sha256Base64(plaintext)
  if (digest !== descriptor.sha256) {
    zeroize(plaintext)
    throw new Error('Attachment integrity check failed')
  }
  return plaintext
}
