import assert from 'node:assert/strict'
import { test } from 'vitest'
import { decryptAttachment, encryptAttachment, MAX_ATTACHMENT_BYTES } from '../src/crypto/attachmentCrypto.js'

function makeFile(name, bytes, type) {
  // Real Blob so `crypto.subtle.digest` accepts the file in tests.
  return new File([bytes], name, { type })
}

test('attachment descriptor decrypts and detects ciphertext tampering', async () => {
  const source = new TextEncoder().encode('private attachment')
  const file = makeFile('secret.txt', source, 'text/plain')
  const { ciphertext, descriptor } = await encryptAttachment(file)
  const expected = new Uint8Array(await decryptAttachment(ciphertext, descriptor))
  assert.deepEqual(expected, source)
  const changed = ciphertext.slice(); changed[0] ^= 1
  await assert.rejects(decryptAttachment(changed, descriptor))
})

test('encrypting a file that exceeds the size limit fails before allocation', async () => {
  const tooBig = { size: MAX_ATTACHMENT_BYTES + 1, name: 'huge.bin', type: 'application/octet-stream' }
  await assert.rejects(encryptAttachment(tooBig))
})

test('an attachment exactly at the production size limit round-trips', async () => {
  const source = new Uint8Array(MAX_ATTACHMENT_BYTES)
  source[0] = 0x51
  source[source.length - 1] = 0xa7
  const { ciphertext, descriptor } = await encryptAttachment(
    makeFile('maximum.bin', source, 'application/octet-stream'),
  )
  assert.equal(descriptor.plaintext_size, MAX_ATTACHMENT_BYTES)
  assert.equal(ciphertext.byteLength, MAX_ATTACHMENT_BYTES + 16)
  const recovered = await decryptAttachment(ciphertext, descriptor)
  assert.equal(recovered[0], 0x51)
  assert.equal(recovered[recovered.length - 1], 0xa7)
})

test('descriptor must not carry leaked plaintext metadata', async () => {
  const source = new TextEncoder().encode('hello')
  const file = makeFile('hello.txt', source, 'text/plain')
  const { descriptor } = await encryptAttachment(file)
  for (const forbidden of ['name', 'file_name', 'media_type', 'mime_type']) {
    assert.equal(Object.prototype.hasOwnProperty.call(descriptor, forbidden), false,
      `descriptor leaked ${forbidden}`)
  }
  assert.equal(descriptor.version, 1)
  assert.equal(descriptor.algorithm, 'AES-256-GCM')
  assert.equal(descriptor.plaintext_size, source.byteLength)
})

test('decrypt rejects descriptors that smuggle metadata fields', async () => {
  const source = new TextEncoder().encode('private')
  const file = makeFile('private.bin', source, 'application/octet-stream')
  const { ciphertext, descriptor } = await encryptAttachment(file)
  const tampered = { ...descriptor, name: 'leak.txt' }
  await assert.rejects(decryptAttachment(ciphertext, tampered))
})

test('decrypt rejects a forged sha256 even if the GCM tag verifies', async () => {
  // AES-GCM authenticates the ciphertext, but the descriptor itself is
  // attacker-controlled. A swapped sha256 must surface as a hard failure
  // rather than letting the UI render bytes that don't match what the
  // sender claimed.
  const source = new TextEncoder().encode('hello, world!')
  const file = makeFile('note.txt', source, 'text/plain')
  const { ciphertext, descriptor } = await encryptAttachment(file)
  const tampered = { ...descriptor, sha256: 'a'.repeat(44) }
  await assert.rejects(decryptAttachment(ciphertext, tampered))
})

test('decrypt rejects a forged plaintext_size', async () => {
  const source = new TextEncoder().encode('hello')
  const file = makeFile('note.txt', source, 'text/plain')
  const { ciphertext, descriptor } = await encryptAttachment(file)
  const tampered = { ...descriptor, plaintext_size: descriptor.plaintext_size + 1 }
  await assert.rejects(decryptAttachment(ciphertext, tampered))
})

test('files larger than the former chunk boundary use one GCM authentication tag', async () => {
  const source = new Uint8Array((1024 * 1024) + 17).fill(0x5a)
  const file = makeFile('large.bin', source, 'application/octet-stream')
  const { ciphertext, descriptor } = await encryptAttachment(file)
  assert.equal(ciphertext.byteLength, source.byteLength + 16)
  assert.deepEqual(await decryptAttachment(ciphertext, descriptor), source)
})

test('decrypt rejects a ciphertext shorter than the GCM tag', async () => {
  const source = new TextEncoder().encode('tiny')
  const file = makeFile('tiny.txt', source, 'text/plain')
  const { descriptor } = await encryptAttachment(file)
  const tooShort = new Uint8Array(8) // smaller than the 16-byte tag
  await assert.rejects(decryptAttachment(tooShort, descriptor))
})

test('descriptor key and nonce match the published sizes', async () => {
  const source = new TextEncoder().encode('size check')
  const file = makeFile('size.bin', source, 'application/octet-stream')
  const { descriptor } = await encryptAttachment(file)
  // 32 bytes raw key -> 44-char base64
  assert.equal(descriptor.key.length, 44)
  // 12 bytes nonce -> 16-char base64
  assert.equal(descriptor.nonce.length, 16)
})
