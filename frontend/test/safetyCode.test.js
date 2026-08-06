import assert from 'node:assert/strict'
import test from 'node:test'
import { createSafetyCode } from '../src/crypto/safetyCode.js'

test('safety code is stable regardless of participant order', async () => {
  const alice = [{ login: 'alice', device_id: 'a', fingerprint: 'a'.repeat(64) }]
  const bob = [{ login: 'bob', device_id: 'b', fingerprint: 'b'.repeat(64) }]
  assert.deepEqual(await createSafetyCode([alice, bob]), await createSafetyCode([bob, alice]))
})
