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
