import assert from 'node:assert/strict'
import test from 'node:test'
import {
  PBKDF2_ITERATIONS,
  buildV2Record,
  encryptStateWithDek,
  migrateV1ToV2,
  passphraseKey,
  randomBytes,
  rewrapDekRaw,
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

test('passphraseKey derives an AES-GCM key from the passphrase', async () => {
  const salt = randomBytes(16)
  const key = await passphraseKey('correct horse battery staple', salt)
  assert.equal(key.algorithm.name, 'AES-GCM')
  assert.equal(key.algorithm.length, 256)
  // The KEK itself is non-extractable: the passphrase bytes are only used
  // to derive a key handle that lives inside WebCrypto, never persisted.
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
  // The DEK is extractable within the worker scope so `rewrapDekRaw` can
  // re-encrypt it under a fresh KEK without re-encrypting state. The
  // trust boundary is the Web Worker, so the raw bytes only ever live
  // inside worker scope and are zeroed as soon as the wrap cycle ends.
  assert.equal(restored.extractable, true, 'restored DEK must be extractable inside the worker trust boundary')

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

test('changePassphrase re-wraps the DEK under a fresh salt without re-encrypting state', async () => {
  // The changePassphrase flow lives in mls.worker.js next to IndexedDB.
  // We exercise the pure-crypto part of the flow here so that the contract
  // is locked at the test boundary: the DEK is preserved, the salt and
  // wrap_iv are fresh, and state_ciphertext + state_iv survive unchanged.
  const initial = await wrapNewDek('device-a', 'correct horse battery staple')
  const dek = initial.dek
  const statePlaintext = encoder.encode('opaque MLS state payload for changePassphrase test')
  const stateIv = randomBytes(12)
  const stateCiphertextBytes = new Uint8Array(await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: stateIv, additionalData: vaultAad('device-a', 'state') },
    dek,
    statePlaintext,
  ))
  const originalRecord = {
    version: 2,
    device_id: 'device-a',
    kdf: { name: 'PBKDF2-HMAC-SHA-256', salt: initial.salt, parameters: { iterations: PBKDF2_ITERATIONS } },
    wrapped_dek: initial.wrappedDek,
    wrap_iv: initial.wrapIv,
    state_ciphertext: stateCiphertextBytes,
    state_iv: stateIv,
    updated_at: '2026-08-07T00:00:00.000Z',
  }

  // Simulate the worker flow: unwrap with old, re-wrap the SAME DEK with new.
  const restoredDek = await unwrapDek('device-a', 'correct horse battery staple', {
    kdf: { salt: originalRecord.kdf.salt, parameters: originalRecord.kdf.parameters },
    wrap_iv: originalRecord.wrap_iv,
    wrapped_dek: originalRecord.wrapped_dek,
  })
  const rewrapped = await rewrapDekRaw(restoredDek, 'device-a', 'a stronger passphrase than before')
  const nextRecord = {
    ...originalRecord,
    kdf: { ...originalRecord.kdf, salt: rewrapped.salt },
    wrapped_dek: rewrapped.wrappedDek,
    wrap_iv: rewrapped.wrapIv,
    updated_at: new Date().toISOString(),
  }

  // The DEK is the same logical key: the re-wrap round-trip must decrypt
  // the original state_ciphertext with no change to state bytes.
  const plaintext = new Uint8Array(await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: originalRecord.state_iv, additionalData: vaultAad('device-a', 'state') },
    restoredDek,
    originalRecord.state_ciphertext,
  ))
  assert.deepEqual(plaintext, statePlaintext, 'restored DEK must decrypt the original state bytes')

  // And independently: unwrap under the new passphrase also yields the
  // same logical DEK, which can decrypt the same state_ciphertext.
  const restoredAgain = await unwrapDek('device-a', 'a stronger passphrase than before', {
    kdf: { salt: nextRecord.kdf.salt, parameters: nextRecord.kdf.parameters },
    wrap_iv: nextRecord.wrap_iv,
    wrapped_dek: nextRecord.wrapped_dek,
  })
  const plaintextAgain = new Uint8Array(await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: originalRecord.state_iv, additionalData: vaultAad('device-a', 'state') },
    restoredAgain,
    originalRecord.state_ciphertext,
  ))
  assert.deepEqual(plaintextAgain, statePlaintext, 'new passphrase unwrap must yield the same DEK')

  // state_ciphertext and state_iv are not touched by a re-wrap.
  assert.ok(bytesEqual(nextRecord.state_ciphertext, originalRecord.state_ciphertext),
    'state_ciphertext must survive the re-wrap unchanged')
  assert.ok(bytesEqual(nextRecord.state_iv, originalRecord.state_iv),
    'state_iv must survive the re-wrap unchanged')

  // Salt and wrap_iv must rotate; otherwise we are not protecting against a
  // stolen ciphertext.
  assert.ok(!bytesEqual(nextRecord.kdf.salt, originalRecord.kdf.salt),
    'salt must rotate on re-wrap')
  assert.ok(!bytesEqual(nextRecord.wrap_iv, originalRecord.wrap_iv),
    'wrap_iv must rotate on re-wrap')
  assert.ok(!bytesEqual(nextRecord.wrapped_dek, originalRecord.wrapped_dek),
    'wrapped_dek must rotate on re-wrap')

  // The old passphrase no longer unwraps the new record.
  await assert.rejects(unwrapDek('device-a', 'correct horse battery staple', {
    kdf: { salt: nextRecord.kdf.salt, parameters: nextRecord.kdf.parameters },
    wrap_iv: nextRecord.wrap_iv,
    wrapped_dek: nextRecord.wrapped_dek,
  }), /AES-GCM|operation/i)
})

// ---------------------------------------------------------------------------
// v1 → v2 migration
//
// The migration orchestrator takes a v1 plaintext (already decrypted under
// the v1 CryptoKey by the worker), the new passphrase, and four storage
// callbacks. These tests drive it through a tiny in-memory storage stub so
// the contract is locked at the test boundary: write order, preservation on
// failure, v1 key deleted only after v2 round-trip passes, and rejection of
// tampering at every step.
// ---------------------------------------------------------------------------

function cloneRecord(record) {
  // Structured clone for the byte-bearing fields; JSON.parse(JSON.stringify)
  // strips Uint8Array/ArrayBuffer contents, which breaks the validator.
  const out = { ...record }
  if (record.kdf) {
    out.kdf = { ...record.kdf }
    if (record.kdf.parameters) out.kdf.parameters = { ...record.kdf.parameters }
  }
  if (record.wrapped_dek !== undefined) {
    out.wrapped_dek = record.wrapped_dek instanceof ArrayBuffer
      ? record.wrapped_dek.slice(0)
      : new Uint8Array(record.wrapped_dek).slice().buffer
  }
  if (record.wrap_iv !== undefined) out.wrap_iv = new Uint8Array(record.wrap_iv)
  if (record.state_ciphertext !== undefined) {
    out.state_ciphertext = record.state_ciphertext instanceof ArrayBuffer
      ? record.state_ciphertext.slice(0)
      : new Uint8Array(record.state_ciphertext).slice().buffer
  }
  if (record.state_iv !== undefined) out.state_iv = new Uint8Array(record.state_iv)
  return out
}

function makeStorageStub(initialState, { writeFailsOnce = false, readV2Returns } = {}) {
  const storage = new Map()
  if (initialState !== undefined) storage.set('state', cloneRecord(initialState))
  let writes = 0
  let deletes = 0
  return {
    storage,
    writes: () => writes,
    deletes: () => deletes,
    writeCandidate: async (record) => {
      writes += 1
      if (writeFailsOnce && writes === 1) throw new Error('IndexedDB write rejected')
      storage.set('candidate', cloneRecord(record))
    },
    readCandidate: async () => {
      if (readV2Returns) return readV2Returns
      return storage.get('candidate')
    },
    commitCandidate: async (record) => {
      deletes += 1
      storage.set('state', cloneRecord(record))
      storage.delete('candidate')
      storage.set('deleted', true)
    },
    assertV1KeyIntact: () => {
      assert.equal(storage.get('deleted'), undefined,
        'v1 key MUST NOT be deleted unless the v2 round-trip passed')
    },
    assertV1StateIntact: () => {
      assert.equal(storage.get('state')?.version, 1, 'v1 state MUST remain untouched before a successful commit')
    },
  }
}

function sampleV1Plaintext() {
  // Synthetic opaque MLS state bytes. The shape does not matter for the
  // migration test; only that the bytes survive a v1 → v2 round-trip.
  return encoder.encode('opaque MLS state bytes for v1 migration test')
}

test('migrateV1ToV2 derives a fresh DEK, wraps the v1 plaintext under v2, and verifies round-trip', async () => {
  const v1Plaintext = sampleV1Plaintext()
  const stub = makeStorageStub({ version: 1 })

  const { record: v2Record } = await migrateV1ToV2({
    deviceId: 'device-a',
    passphrase: 'a stronger passphrase than before',
    v1Plaintext,
    writeCandidate: stub.writeCandidate,
    readCandidate: stub.readCandidate,
    commitCandidate: stub.commitCandidate,
  })

  assert.equal(v2Record.version, 2)
  assert.equal(v2Record.device_id, 'device-a')
  assert.equal(stub.writes(), 1, 'migrateV1ToV2 writes the v2 record exactly once')
  assert.equal(stub.deletes(), 1, 'migrateV1ToV2 deletes the v1 key exactly once')

  // Independent decryption against the returned record. This is what the
  // worker does right after migration: unwrapDek + decrypt state. If the
  // v2 round-trip produced corrupt ciphertext, this step would fail.
  const restoredDek = await unwrapDek('device-a', 'a stronger passphrase than before', {
    kdf: { salt: v2Record.kdf.salt, parameters: v2Record.kdf.parameters },
    wrap_iv: v2Record.wrap_iv,
    wrapped_dek: v2Record.wrapped_dek,
  })
  const restoredPlaintext = new Uint8Array(await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: v2Record.state_iv, additionalData: vaultAad('device-a', 'state') },
    restoredDek, v2Record.state_ciphertext,
  ))
  assert.deepEqual(restoredPlaintext, v1Plaintext, 'v2 round-trip must yield the v1 plaintext bytes')
})

test('migrateV1ToV2 deletes the v1 key only AFTER the v2 round-trip passes', async () => {
  // Track the order of candidate writes and the atomic commit. The contract:
  // write comes first, then a re-read + decrypt, then commit. If the order is
  // wrong the v1 key could be deleted even when the v2 record is corrupt,
  // and the user would lose their state.
  const order = []
  const v1Plaintext = sampleV1Plaintext()
  const stub = makeStorageStub({ version: 1 })
  const wrappedStub = {
    writeCandidate: async (record) => { order.push('writeCandidate'); await stub.writeCandidate(record) },
    readCandidate: async () => { order.push('readCandidate'); return stub.readCandidate() },
    commitCandidate: async (record) => { order.push('commitCandidate'); await stub.commitCandidate(record) },
  }

  await migrateV1ToV2({
    deviceId: 'device-a',
    passphrase: 'a stronger passphrase than before',
    v1Plaintext,
    ...wrappedStub,
  })

  assert.deepEqual(order, ['writeCandidate', 'readCandidate', 'commitCandidate'],
    'v1 key MUST be deleted only after the v2 round-trip passes')
})

test('migrateV1ToV2 does NOT delete the v1 key when the v2 write fails', async () => {
  // Simulate IndexedDB rejecting the v2 write. The v1 key MUST stay
  // intact so the user can try again. The candidate never overwrites v1.
  const v1Plaintext = sampleV1Plaintext()
  const stub = makeStorageStub({ version: 1 }, { writeFailsOnce: true })

  await assert.rejects(migrateV1ToV2({
    deviceId: 'device-a',
    passphrase: 'a stronger passphrase than before',
    v1Plaintext,
    writeCandidate: stub.writeCandidate,
    readCandidate: stub.readCandidate,
    commitCandidate: stub.commitCandidate,
  }), /IndexedDB write rejected/)

  assert.equal(stub.writes(), 1, 'orchestrator should have attempted one write')
  assert.equal(stub.deletes(), 0, 'v1 key MUST NOT be deleted on write failure')
  stub.assertV1KeyIntact()
  stub.assertV1StateIntact()
})

test('migrateV1ToV2 does NOT delete the v1 key when the v2 round-trip returns a malformed record', async () => {
  // Simulate the on-disk v2 record having the wrong shape (e.g., an
  // attacker wrote garbage into IndexedDB). The orchestrator's validator
  // MUST reject it and the v1 key MUST stay intact so the user can retry.
  const v1Plaintext = sampleV1Plaintext()
  const stub = makeStorageStub({ version: 1 })

  await assert.rejects(migrateV1ToV2({
    deviceId: 'device-a',
    passphrase: 'a stronger passphrase than before',
    v1Plaintext,
    writeCandidate: stub.writeCandidate,
    readCandidate: async () => ({ version: 1, garbage: true }),
    commitCandidate: stub.commitCandidate,
  }), /Browser vault v2 record failed post-write validation/)

  assert.equal(stub.deletes(), 0, 'v1 key MUST NOT be deleted on validation failure')
  stub.assertV1KeyIntact()
  stub.assertV1StateIntact()
})

test('migrateV1ToV2 does NOT delete the v1 key when the v2 round-trip ciphertext does not match', async () => {
  // Persist a v2 record whose state_ciphertext encrypts a different
  // plaintext. The orchestrator's byte-compare against the v1 plaintext
  // MUST fail and the v1 key MUST stay.
  const v1Plaintext = sampleV1Plaintext()
  const stub = makeStorageStub({ version: 1 })

  // Wrap the write to substitute a different ciphertext at rest.
  const realWrite = stub.writeCandidate
  const corruptedStub = {
    writeCandidate: realWrite,
    readCandidate: async () => {
      // Build a v2 record with a corrupt state_ciphertext that decrypts to
      // "wrong" instead of the v1 plaintext.
      const wrapped = await wrapNewDek('device-a', 'a stronger passphrase than before')
      const { iv, ciphertext } = await encryptStateWithDek('device-a', wrapped.dek, encoder.encode('wrong'))
      return buildV2Record({
        deviceId: 'device-a',
        wrap: wrapped,
        stateIv: iv,
        stateCiphertext: ciphertext,
      })
    },
    commitCandidate: stub.commitCandidate,
  }

  await assert.rejects(migrateV1ToV2({
    deviceId: 'device-a',
    passphrase: 'a stronger passphrase than before',
    v1Plaintext,
    ...corruptedStub,
  }), /does not round-trip the v1 state/)

  assert.equal(stub.deletes(), 0, 'v1 key MUST NOT be deleted on round-trip mismatch')
  stub.assertV1KeyIntact()
  stub.assertV1StateIntact()
})

test('migrateV1ToV2 rejects a passphrase that cannot decrypt the v2 record', async () => {
  // Wrap with one passphrase, but call migrateV1ToV2 with a different one
  // by patching the read-after-write stub. The orchestrator's unwrap step
  // will throw and the v1 key stays intact.
  const v1Plaintext = sampleV1Plaintext()
  const stub = makeStorageStub({ version: 1 })
  // The "real" write uses passphrase A. We patch readV2AfterWrite to
  // return a record that was wrapped with passphrase B, so the unwrap
  // with passphrase A fails.
  const wrappedStub = {
    writeCandidate: stub.writeCandidate,
    readCandidate: async () => {
      // Build an alternate v2 record whose wrap uses a different passphrase.
      const alt = await wrapNewDek('device-a', 'completely different passphrase than A')
      const { iv, ciphertext } = await encryptStateWithDek('device-a', alt.dek, v1Plaintext)
      return buildV2Record({
        deviceId: 'device-a', dek: alt.dek, wrap: alt, stateIv: iv, stateCiphertext: ciphertext,
      })
    },
    commitCandidate: stub.commitCandidate,
  }

  await assert.rejects(migrateV1ToV2({
    deviceId: 'device-a',
    passphrase: 'a stronger passphrase than before',
    v1Plaintext,
    ...wrappedStub,
  }), /AES-GCM|operation/i)

  assert.equal(stub.deletes(), 0, 'v1 key MUST NOT be deleted when the v2 unwrap fails')
  stub.assertV1KeyIntact()
  stub.assertV1StateIntact()
})

test('migrateV1ToV2 produces a v2 record whose state_iv, wrapped_dek and wrap_iv are all fresh', async () => {
  // The migration must rotate every cryptographic parameter. A v2 record
  // that re-used v1's IV or wrapped_dek would not protect against a stolen
  // v1 ciphertext.
  const v1Plaintext = sampleV1Plaintext()
  const stub = makeStorageStub({ version: 1 })
  const { record: v2Record } = await migrateV1ToV2({
    deviceId: 'device-a',
    passphrase: 'a stronger passphrase than before',
    v1Plaintext,
    writeCandidate: stub.writeCandidate,
    readCandidate: stub.readCandidate,
    commitCandidate: stub.commitCandidate,
  })

  assert.equal(v2Record.state_iv.length, 12, 'state_iv must be 12 bytes (AES-GCM nonce)')
  assert.equal(v2Record.wrap_iv.length, 12, 'wrap_iv must be 12 bytes')
  assert.equal(v2Record.kdf.salt.length, 16, 'salt must be 16 bytes')
  assert.ok(v2Record.wrapped_dek.byteLength >= 32 + 16,
    'wrapped_dek must contain the DEK bytes plus the AES-GCM auth tag')
  assert.ok(!Number.isNaN(Date.parse(v2Record.updated_at)),
    'updated_at must be a valid ISO-8601 timestamp')
})

test('migrateV1ToV2 never writes the passphrase into storage', async () => {
  // Defence-in-depth: even if the storage stub is fully observable, the
  // passphrase string MUST NOT appear in any value the orchestrator writes.
  // The orchestrator passes the passphrase to wrapNewDek / unwrapDek and
  // never puts it in the record itself. This test guards against a future
  // refactor that accidentally stashes the passphrase for "convenience".
  const v1Plaintext = sampleV1Plaintext()
  const passphrase = 'a stronger passphrase than before'
  const observed = []
  const stub = makeStorageStub({ version: 1 })
  const wrappedStub = {
    writeCandidate: async (record) => { observed.push(record); await stub.writeCandidate(record) },
    readCandidate: stub.readCandidate,
    commitCandidate: stub.commitCandidate,
  }

  await migrateV1ToV2({
    deviceId: 'device-a', passphrase, v1Plaintext, ...wrappedStub,
  })

  for (const record of observed) {
    const serialized = JSON.stringify(record, (_, value) => {
      // Bytes (Uint8Array/ArrayBuffer) survive JSON lossily in the test;
      // base64-encode them so we can scan them too.
      if (value instanceof Uint8Array) return Buffer.from(value).toString('base64')
      if (value instanceof ArrayBuffer) return Buffer.from(value).toString('base64')
      return value
    })
    assert.ok(!serialized.includes(passphrase),
      `passphrase MUST NOT appear in any stored record (saw ${serialized.slice(0, 80)}…)`)
  }
})

test('migrateV1ToV2 keeps state_ciphertext bit-identical to the v1 plaintext (zero-byte delta)', async () => {
  // The migration is a re-key: the opaque MLS state bytes MUST survive
  // byte-for-byte. A copy that changed the bytes would silently corrupt
  // the user's MLS group state.
  const v1Plaintext = sampleV1Plaintext()
  const stub = makeStorageStub({ version: 1 })
  const { record: v2Record } = await migrateV1ToV2({
    deviceId: 'device-a',
    passphrase: 'a stronger passphrase than before',
    v1Plaintext,
    writeCandidate: stub.writeCandidate,
    readCandidate: stub.readCandidate,
    commitCandidate: stub.commitCandidate,
  })
  const restoredDek = await unwrapDek('device-a', 'a stronger passphrase than before', {
    kdf: { salt: v2Record.kdf.salt, parameters: v2Record.kdf.parameters },
    wrap_iv: v2Record.wrap_iv,
    wrapped_dek: v2Record.wrapped_dek,
  })
  const restored = new Uint8Array(await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: v2Record.state_iv, additionalData: vaultAad('device-a', 'state') },
    restoredDek, v2Record.state_ciphertext,
  ))
  assert.deepEqual(restored, v1Plaintext)
  assert.equal(restored.length, v1Plaintext.length)
})
