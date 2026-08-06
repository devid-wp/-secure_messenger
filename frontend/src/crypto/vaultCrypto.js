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
  const dek = await crypto.subtle.importKey('raw', rawDek, 'AES-GCM', false, ['encrypt', 'decrypt'])
  const kek = await passphraseKey(passphrase, salt)
  const wrappedDek = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: wrapIv, additionalData: vaultAad(deviceId, 'dek') }, kek, rawDek)
  rawDek.fill(0)
  return { dek, salt, wrapIv, wrappedDek }
}

export async function unwrapDek(deviceId, passphrase, record) {
  const kek = await passphraseKey(passphrase, record.kdf.salt, record.kdf.parameters.iterations)
  const raw = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: record.wrap_iv, additionalData: vaultAad(deviceId, 'dek') }, kek, record.wrapped_dek))
  const dek = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt', 'decrypt'])
  raw.fill(0)
  return dek
}
