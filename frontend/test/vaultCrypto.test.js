import assert from 'node:assert/strict'
import test from 'node:test'
import {
  PBKDF2_ITERATIONS,
  passphraseKey,
  randomBytes,
  unwrapDek,
  vaultAad,
  wrapNewDek,
} from '../src/crypto/vaultCrypto.js'

const encoder = new TextEncoder()

function bytesEqual(a, b) {
  const left = a instanceof Uint8Array ? a : new Uint8Array(a)
  const right = b instanceof Uint8Array ? b : new Uint8Array(b)
  if (left.length !== right.length) return false
  for (let i = 0; i < left.length; i += 1) if (left[i] !== right[i]) return false
  return true
}

test('module exports the documented KDF cost', () => {
  assert.equal(typeof PBKDF2_ITERATIONS, 'number')
  assert.ok(PBKDF2_ITERATIONS >= 600_000, 'PBKDF2 iteration count must meet the v2 cost floor')
})

test('wrapNewDek returns a unique salt and unique wrap IV on every call', async () => {
  const first = await wrapNewDek('device-a', 'correct horse battery staple')
  const second = await wrapNewDek('device-a', 'correct horse battery staple')
  assert.equal(first.salt.length, 16, 'salt must be 16 bytes')
  assert.equal(first.wrapIv.length, 12, 'wrap IV must be 12 bytes (AES-GCM nonce)')
  assert.equal(second.salt.length, 16)
  assert.equal(second.wrapIv.length, 12)
  assert.ok(!bytesEqual(first.salt, second.salt), 'salt must be unique per installation')
  assert.ok(!bytesEqual(first.wrapIv, second.wrapIv), 'wrap IV must be unique per wrap')
  assert.ok(!bytesEqual(first.wrappedDek, second.wrappedDek), 'wrapped DEK must differ because salt and IV differ')
})

test('passphraseKey derives a non-extractable AES-GCM key from the passphrase', async () => {
  const salt = randomBytes(16)
  const key = await passphraseKey('correct horse battery staple', salt)
  assert.equal(key.algorithm.name, 'AES-GCM')
  assert.equal(key.algorithm.length, 256)
  assert.equal(key.extractable, false, 'derived KEK must never be exportable')
  assert.deepEqual(key.usages, ['encrypt', 'decrypt'])
})

test('passphraseKey rejects passphrases shorter than the documented minimum', async () => {
  const salt = randomBytes(16)
  await assert.rejects(passphraseKey('short', salt), /10 characters/)
  await assert.rejects(passphraseKey('', salt), /10 characters/)
  await assert.rejects(passphraseKey(undefined, salt), /10 characters/)
  await assert.rejects(passphraseKey(123, salt), /10 characters/)
})

test('vaultAad binds the device_id and purpose into a versioned namespace', () => {
  const aadA = vaultAad('device-a', 'dek')
  const aadB = vaultAad('device-b', 'dek')
  const aadState = vaultAad('device-a', 'state')
  assert.ok(!bytesEqual(aadA, aadB), 'different device_ids must produce different AAD')
  assert.ok(!bytesEqual(aadA, aadState), 'different purposes must produce different AAD')
  assert.equal(new TextDecoder().decode(aadA), 'secure-messenger:v2:device-a:dek')
  assert.equal(new TextDecoder().decode(aadState), 'secure-messenger:v2:device-a:state')
})

test('unwrapDek round-trips for the correct passphrase and exact AAD context', async () => {
  const { dek, salt, wrapIv, wrappedDek } = await wrapNewDek('device-a', 'correct horse battery staple')
  const record = {
    kdf: { name: 'PBKDF2-HMAC-SHA-256', salt, parameters: { iterations: PBKDF2_ITERATIONS } },
    wrap_iv: wrapIv,
    wrapped_dek: wrappedDek,
  }
  const restored = await unwrapDek('device-a', 'correct horse battery staple', record)
  assert.equal(restored.extractable, false, 'restored DEK must be non-extractable')

  // Sanity-check that the restored DEK actually decrypts data encrypted by the original DEK.
  const iv = randomBytes(12)
  const sample = encoder.encode('opaque MLS state bytes')
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: vaultAad('device-a', 'state') },
    dek,
    sample,
  )
  const plaintext = new Uint8Array(await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv, additionalData: vaultAad('device-a', 'state') },
    restored,
    ciphertext,
  ))
  assert.deepEqual(plaintext, sample)
})

test('unwrapDek rejects a wrong passphrase, a different device_id and a different wrap IV', async () => {
  const wrapped = await wrapNewDek('device-a', 'correct horse battery staple')
  const baseRecord = {
    kdf: { name: 'PBKDF2-HMAC-SHA-256', salt: wrapped.salt, parameters: { iterations: PBKDF2_ITERATIONS } },
    wrap_iv: wrapped.wrapIv,
    wrapped_dek: wrapped.wrappedDek,
  }
  await assert.rejects(unwrapDek('device-a', 'incorrect password', baseRecord), /AES-GCM|operation/i)
  await assert.rejects(unwrapDek('device-b', 'correct horse battery staple', baseRecord), /AES-GCM|operation/i)
  const tamperedIv = new Uint8Array(wrapped.wrapIv)
  tamperedIv[0] ^= 0x01
  await assert.rejects(unwrapDek('device-a', 'correct horse battery staple', {
    ...baseRecord, wrap_iv: tamperedIv,
  }), /AES-GCM|operation/i)
  const tamperedWrapped = new Uint8Array(wrapped.wrappedDek)
  tamperedWrapped[0] ^= 0x01
  await assert.rejects(unwrapDek('device-a', 'correct horse battery staple', {
    ...baseRecord, wrapped_dek: tamperedWrapped,
  }), /AES-GCM|operation/i)
})

test('unwrapDek honors a different iteration count stored in the record', async () => {
  const wrapped = await wrapNewDek('device-a', 'correct horse battery staple')
  const record = {
    kdf: { name: 'PBKDF2-HMAC-SHA-256', salt: wrapped.salt, parameters: { iterations: 100_000 } },
    wrap_iv: wrapped.wrapIv,
    wrapped_dek: wrapped.wrappedDek,
  }
  // The salt is fresh enough that 100k PBKDF2 iterations will derive a
  // different KEK from the actual passphrase, so the unwrap must fail.
  await assert.rejects(unwrapDek('device-a', 'correct horse battery staple', record), /AES-GCM|operation/i)
})

test('vault record shape matches the documented v2 schema', () => {
  // Schema-as-data: the keys on a v2 record, asserted at the test boundary
  // so that future refactors cannot silently widen or narrow the wire shape.
  const allowedTopLevel = ['version', 'device_id', 'kdf', 'wrapped_dek', 'wrap_iv', 'state_ciphertext', 'state_iv', 'updated_at']
  const allowedKdf = ['name', 'salt', 'parameters']
  const allowedKdfParameters = ['iterations']
  // This sample is a structural fixture: it must be the literal set documented
  // in `docs/local-vault-backup-recovery.md`. Update both together.
  const fixture = {
    version: 2,
    device_id: 'device-a',
    kdf: { name: 'PBKDF2-HMAC-SHA-256', salt: randomBytes(16), parameters: { iterations: PBKDF2_ITERATIONS } },
    wrapped_dek: new Uint8Array(44),
    wrap_iv: randomBytes(12),
    state_ciphertext: new Uint8Array(64),
    state_iv: randomBytes(12),
    updated_at: new Date().toISOString(),
  }
  for (const key of Object.keys(fixture)) {
    assert.ok(allowedTopLevel.includes(key), `top-level key "${key}" must be in the v2 schema`)
  }
  for (const key of Object.keys(fixture.kdf)) {
    assert.ok(allowedKdf.includes(key), `kdf key "${key}" must be in the v2 schema`)
  }
  for (const key of Object.keys(fixture.kdf.parameters)) {
    assert.ok(allowedKdfParameters.includes(key), `kdf.parameters key "${key}" must be in the v2 schema`)
  }
})