function toBase64(bytes) {
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  return btoa(binary)
}
function fromBase64(value) { return Uint8Array.from(atob(value), (character) => character.charCodeAt(0)) }
async function sha256(bytes) { return toBase64(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))) }

export async function encryptAttachment(file) {
  const plaintext = new Uint8Array(await file.arrayBuffer())
  const rawKey = crypto.getRandomValues(new Uint8Array(32))
  const nonce = crypto.getRandomValues(new Uint8Array(12))
  const key = await crypto.subtle.importKey('raw', rawKey, 'AES-GCM', false, ['encrypt'])
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, key, plaintext))
  const descriptor = {
    version: 1, object_id: null, algorithm: 'AES-256-GCM', key: toBase64(rawKey), nonce: toBase64(nonce),
    plaintext_size: plaintext.byteLength, ciphertext_size: ciphertext.byteLength,
    sha256: await sha256(plaintext), name: file.name, media_type: file.type || 'application/octet-stream',
  }
  plaintext.fill(0); rawKey.fill(0)
  return { ciphertext, descriptor }
}

export async function decryptAttachment(ciphertext, descriptor) {
  if (descriptor?.version !== 1 || descriptor.algorithm !== 'AES-256-GCM') throw new Error('Unsupported attachment descriptor')
  if (ciphertext.byteLength !== descriptor.ciphertext_size) throw new Error('Encrypted attachment size mismatch')
  const key = await crypto.subtle.importKey('raw', fromBase64(descriptor.key), 'AES-GCM', false, ['decrypt'])
  const plaintext = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromBase64(descriptor.nonce) }, key, ciphertext))
  if (plaintext.byteLength !== descriptor.plaintext_size || await sha256(plaintext) !== descriptor.sha256) {
    plaintext.fill(0); throw new Error('Attachment integrity check failed')
  }
  return plaintext
}
