import assert from 'node:assert/strict'
import test from 'node:test'
import { decryptAttachment, encryptAttachment } from '../src/crypto/attachmentCrypto.js'

test('attachment descriptor decrypts and detects ciphertext tampering', async () => {
  const source = new TextEncoder().encode('private attachment')
  const expected = source.slice()
  const file = { name: 'secret.txt', type: 'text/plain', arrayBuffer: async () => source.buffer }
  const { ciphertext, descriptor } = await encryptAttachment(file)
  assert.deepEqual(await decryptAttachment(ciphertext, descriptor), expected)
  const changed = ciphertext.slice(); changed[0] ^= 1
  await assert.rejects(decryptAttachment(changed, descriptor))
})
