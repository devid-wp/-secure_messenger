import assert from 'node:assert/strict'
import { afterEach, test, vi } from 'vitest'
import { clearRetryableEnvelopes, confirmRetryableEnvelope, getRetryableEnvelope } from '../src/crypto/outgoingEnvelopeCache.js'

afterEach(clearRetryableEnvelopes)

test('retryable envelope cache reuses randomized ciphertext until confirmed', async () => {
  const encrypt = vi.fn().mockResolvedValue({ ciphertext: new Uint8Array([1, 2]), epoch: 4 })
  const first = await getRetryableEnvelope('chat:client', encrypt)
  const retry = await getRetryableEnvelope('chat:client', encrypt)
  assert.strictEqual(retry, first)
  assert.equal(encrypt.mock.calls.length, 1)

  confirmRetryableEnvelope('chat:client')
  await getRetryableEnvelope('chat:client', encrypt)
  assert.equal(encrypt.mock.calls.length, 2)
})
