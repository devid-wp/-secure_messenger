export const PBKDF2_ITERATIONS = 600000
const encoder = new TextEncoder()

export function vaultAad(deviceId, purpose) { return encoder.encode(`secure-messenger:v2:${deviceId}:${purpose}`) }
export function randomBytes(length) { return crypto.getRandomValues(new Uint8Array(length)) }

export async function passphraseKey(passphrase, salt, iterations = PBKDF2_ITERATIONS) {
  if (typeof passphrase !== 'string' || passphrase.length < 10) throw new Error('Vault passphrase must contain at least 10 characters')
  const material = await crypto.subtle.importKey('raw', encoder.encode(passphrase), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations }, material, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
}

export async function wrapNewDek(deviceId, passphrase) {
  const rawDek = randomBytes(32), salt = randomBytes(16), wrapIv = randomBytes(12)
  // The DEK must be extractable inside the worker so `rewrapDekRaw` can
  // export its bytes for re-encryption under a fresh KEK. The trust
  // boundary is the Web Worker itself, not the JS context within it:
  // raw bytes live in worker scope only and are zeroed as soon as the
  // wrap/unwrap cycle finishes. IndexedDB only ever sees the wrapped form.
  const dek = await crypto.subtle.importKey('raw', rawDek, 'AES-GCM', true, ['encrypt', 'decrypt'])
  const kek = await passphraseKey(passphrase, salt)
  const wrappedDek = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: wrapIv, additionalData: vaultAad(deviceId, 'dek') }, kek, rawDek)
  rawDek.fill(0)
  return { dek, salt, wrapIv, wrappedDek }
}

// Re-wrap an existing DEK under a fresh salt and IV. The DEK bytes are
// preserved so the caller does not need to re-encrypt state ciphertext;
// only the wrapped DEK record changes. The raw DEK bytes are exported,
// re-wrapped under the new KEK, and zeroed before this function returns.
// They never leave WebCrypto call frames; callers receive only the new
// salt/IV/wrapped bytes.
export async function rewrapDekRaw(dek, deviceId, newPassphrase) {
  const rawDek = new Uint8Array(await crypto.subtle.exportKey('raw', dek))
  const salt = randomBytes(16), wrapIv = randomBytes(12)
  const kek = await passphraseKey(newPassphrase, salt)
  const wrappedDek = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: wrapIv, additionalData: vaultAad(deviceId, 'dek') }, kek, rawDek)
  rawDek.fill(0)
  return { salt, wrapIv, wrappedDek }
}

export async function unwrapDek(deviceId, passphrase, record) {
  const kek = await passphraseKey(passphrase, record.kdf.salt, record.kdf.parameters.iterations)
  const raw = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: record.wrap_iv, additionalData: vaultAad(deviceId, 'dek') }, kek, record.wrapped_dek))
  // Same extractable=true reasoning as wrapNewDek: the worker is the
  // trust boundary, and `rewrapDekRaw` needs the bytes.
  const dek = await crypto.subtle.importKey('raw', raw, 'AES-GCM', true, ['encrypt', 'decrypt'])
  raw.fill(0)
  return dek
}

// Encrypt opaque MLS state bytes under the v2 DEK with a fresh IV. Returns
// the ciphertext and IV. The AAD binds the device_id so ciphertexts from
// different devices are not interchangeable.
export async function encryptStateWithDek(deviceId, dek, plaintext) {
  const iv = randomBytes(12)
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: vaultAad(deviceId, 'state') },
    dek,
    plaintext,
  )
  return { iv, ciphertext }
}

// Build a v2 record from wrapNewDek + encryptStateWithDek inputs. The
// caller writes the record to IndexedDB and is responsible for deleting
// the v1 key only after independent verification of the v2 record.
export function buildV2Record({ deviceId, wrap, stateIv, stateCiphertext, updatedAt = new Date().toISOString() }) {
  return {
    version: 2,
    device_id: deviceId,
    kdf: { name: 'PBKDF2-HMAC-SHA-256', salt: wrap.salt, parameters: { iterations: PBKDF2_ITERATIONS } },
    wrapped_dek: wrap.wrappedDek,
    wrap_iv: wrap.wrapIv,
    state_ciphertext: stateCiphertext,
    state_iv: stateIv,
    updated_at: updatedAt,
  }
}

// v1 → v2 migration orchestrator. The function takes the v1 plaintext
// state (already decrypted under the v1 CryptoKey by the caller) and the
// new passphrase, then runs the strict order required by the recovery
// policy:
//
//   1. wrapNewDek under the new passphrase
//   2. encrypt the state under the new DEK
//   3. write the v2 record to a separate candidate key
//   4. re-read the v2 record from storage and decrypt it
//   5. byte-compare against the v1 plaintext
//   6. ONLY THEN atomically promote v2 and delete the v1 record/key
//
// The candidate lives under a different IndexedDB key, so v1 stays usable
// throughout verification. commitCandidate must promote the candidate and
// remove the v1 state/key in one IndexedDB transaction. The verified DEK is
// returned for the already-unlocked worker session.
export async function migrateV1ToV2({ deviceId, passphrase, v1Plaintext, writeCandidate, readCandidate, commitCandidate }) {
  // Step 1+2: re-key the state.
  const wrapped = await wrapNewDek(deviceId, passphrase)
  const { iv: stateIv, ciphertext: stateCiphertext } = await encryptStateWithDek(deviceId, wrapped.dek, v1Plaintext)
  const v2Record = buildV2Record({ deviceId, wrap: wrapped, stateIv, stateCiphertext })

  // Step 3: persist a candidate without touching the v1 record or key.
  await writeCandidate(v2Record)

  // Step 4: re-read the v2 record from storage and decrypt it. This
  // catches any subtle corruption between the in-memory write and the
  // persisted form.
  const stored = await readCandidate()
  if (!validV2Record(stored, deviceId)) throw new Error('Browser vault v2 record failed post-write validation')
  const restoredDek = await unwrapDek(deviceId, passphrase, stored)
  const restoredPlaintext = new Uint8Array(await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: stored.state_iv, additionalData: vaultAad(deviceId, 'state') },
    restoredDek, stored.state_ciphertext,
  ))

  // Step 5: byte-compare against the v1 plaintext. A mismatch means
  // the v2 record is corrupt - we must not delete v1 because it is
  // the only chance the user has to recover their state.
  if (!bytesEqual(restoredPlaintext, v1Plaintext)) {
    restoredPlaintext.fill(0)
    throw new Error('Browser vault v2 record does not round-trip the v1 state')
  }
  restoredPlaintext.fill(0)

  // Step 6: atomically promote v2 and remove v1. A failed transaction
  // leaves the original record and CryptoKey intact.
  await commitCandidate(stored)

  return { record: stored, dek: restoredDek }
}

function validV2Record(record, deviceId) {
  return record?.version === 2 && record.device_id === deviceId
    && record.kdf?.name === 'PBKDF2-HMAC-SHA-256'
    && Number.isSafeInteger(record.kdf.parameters?.iterations)
    && record.state_iv instanceof Uint8Array
    && record.state_ciphertext instanceof ArrayBuffer
    && record.wrapped_dek instanceof ArrayBuffer
    && record.wrap_iv instanceof Uint8Array
}

function bytesEqual(a, b) {
  const left = a instanceof Uint8Array ? a : new Uint8Array(a)
  const right = b instanceof Uint8Array ? b : new Uint8Array(b)
  if (left.length !== right.length) return false
  for (let i = 0; i < left.length; i += 1) if (left[i] !== right[i]) return false
  return true
}
