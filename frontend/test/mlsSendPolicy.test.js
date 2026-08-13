import { beforeEach, test } from 'vitest'
import assert from 'node:assert/strict'
import { MLS_ERROR_CODES } from '../src/crypto/mlsErrors.js'
import {
  assertMlsSendingAllowed, blockMlsSending, explicitMlsResync,
  mlsSendingBlocked, resetMlsSendPolicyForTests,
} from '../src/crypto/mlsSendPolicy.js'

beforeEach(resetMlsSendPolicyForTests)

test('an ambiguous cryptographic failure blocks sending before plaintext work begins', () => {
  let plaintextTouched = false
  blockMlsSending(41, new Error('transcript mismatch'))

  assert.throws(() => {
    assertMlsSendingAllowed(41)
    plaintextTouched = true
  }, (error) => error.code === MLS_ERROR_CODES.RESYNC_REQUIRED)
  assert.equal(plaintextTouched, false)
  assert.equal(mlsSendingBlocked(41), true)
})

test('only a successful explicit resync clears the fail-closed state', async () => {
  blockMlsSending('group-a', new Error('corrupted ciphertext'))

  await assert.rejects(
    explicitMlsResync('group-a', async () => { throw new Error('resync failed') }),
    /resync failed/,
  )
  assert.equal(mlsSendingBlocked('group-a'), true)

  await explicitMlsResync('group-a', async () => 'synchronized')
  assert.equal(mlsSendingBlocked('group-a'), false)
  assert.doesNotThrow(() => assertMlsSendingAllowed('group-a'))
})
