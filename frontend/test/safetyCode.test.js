import assert from 'node:assert/strict'
import { test } from 'vitest'
import { createSafetyCode } from '../src/crypto/safetyCode.js'

const base64 = (bytes) => btoa(String.fromCharCode(...bytes))
const credential = async (login, deviceId, byte) => {
  const identityKey = base64(new Uint8Array(32).fill(byte))
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new Uint8Array(32).fill(byte)))
  const fingerprint = [...digest].map((value) => value.toString(16).padStart(2, '0')).join('')
  return {
    identity: { login, device_id: deviceId, identity_key: identityKey, fingerprint },
    verified: { device_id: deviceId, identity_key: identityKey, fingerprint },
  }
}

test('safety code is stable regardless of participant order after MLS credential verification', async () => {
  const alice = await credential('alice', 'a', 0x11)
  const bob = await credential('bob', 'b', 0x22)
  assert.deepEqual(
    await createSafetyCode([[alice.identity], [bob.identity]], [alice.verified, bob.verified]),
    await createSafetyCode([[bob.identity], [alice.identity]], [bob.verified, alice.verified]),
  )
})

test('safety code rejects a server fingerprint or key that differs from the verified MLS leaf', async () => {
  const alice = await credential('alice', 'a', 0x11)
  const bob = await credential('bob', 'b', 0x22)
  const forged = { ...bob.identity, fingerprint: 'f'.repeat(64) }

  await assert.rejects(
    createSafetyCode([[alice.identity], [forged]], [alice.verified, bob.verified]),
    /credential verification failed/,
  )
})

test('safety code rejects any mismatch in the active device set', async () => {
  const alice = await credential('alice', 'a', 0x11)
  const bob = await credential('bob', 'b', 0x22)
  const bobPhone = await credential('bob', 'b-phone', 0x33)

  await assert.rejects(
    createSafetyCode([[alice.identity], [bob.identity, bobPhone.identity]], [alice.verified, bob.verified]),
    /device set does not match/,
  )
})
