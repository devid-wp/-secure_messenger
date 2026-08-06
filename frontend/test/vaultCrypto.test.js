import assert from 'node:assert/strict'
import test from 'node:test'
import { PBKDF2_ITERATIONS, unwrapDek, wrapNewDek } from '../src/crypto/vaultCrypto.js'

test('wrapped DEK rejects a wrong passphrase and different device AAD', async () => {
  const wrapped = await wrapNewDek('device-a', 'correct horse battery staple')
  const record = { kdf: { salt: wrapped.salt, parameters: { iterations: PBKDF2_ITERATIONS } }, wrap_iv: wrapped.wrapIv, wrapped_dek: wrapped.wrappedDek }
  await assert.rejects(unwrapDek('device-a', 'incorrect password', record))
  await assert.rejects(unwrapDek('device-b', 'correct horse battery staple', record))
  assert.ok(await unwrapDek('device-a', 'correct horse battery staple', record))
})
