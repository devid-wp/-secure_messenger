import assert from 'node:assert/strict'
import { test } from 'vitest'
import { applyMessageLifecycle } from '../src/crypto/messageLifecycle.js'
import { classifyMlsError, MLS_ERROR_CODES } from '../src/crypto/mlsErrors.js'

const DEVICE_A = '11111111-1111-4111-8111-111111111111'
const DEVICE_B = '22222222-2222-4222-8222-222222222222'
const id = () => crypto.randomUUID()
const event = (item, sequence = 1) => ({ item, envelope: { id: `mls:${sequence}`, timestamp: `2026-08-08T00:00:0${sequence}.000Z`, mls_epoch: 4 } })

test('message lifecycle applies out-of-order edit/delete only from the original device', () => {
  const target = id()
  const events = [
    event({ type: 'edit', client_id: id(), target_client_id: target, content: 'edited', sender: 'alice', sender_device_id: DEVICE_A }, 1),
    event({ type: 'message', client_id: target, kind: 'text', content: 'original', sender: 'alice', sender_device_id: DEVICE_A }, 2),
    event({ type: 'delete', client_id: id(), target_client_id: target, sender: 'bob', sender_device_id: DEVICE_B }, 3),
  ]
  const messages = applyMessageLifecycle(events)
  assert.equal(messages.length, 1)
  assert.equal(messages[0].content, 'edited')
  assert.equal(messages[0].deleted_at, undefined, 'another device cannot impersonate the original author')
})

test('replay and duplicate client ids never create a second message', () => {
  const clientId = id()
  const message = { type: 'message', client_id: clientId, kind: 'text', content: 'once', sender_device_id: DEVICE_A }
  assert.equal(applyMessageLifecycle([event(message, 1), event({ ...message }, 2)]).length, 1)
})

test('reply, reaction and receipts are resolved after out-of-order delivery', () => {
  const target = id()
  const replyId = id()
  const messages = applyMessageLifecycle([
    event({ type: 'message', client_id: replyId, kind: 'text', content: 'reply', reply: { target_client_id: target }, sender_device_id: DEVICE_B }, 1),
    event({ type: 'reaction', client_id: id(), target_client_id: target, emoji: '👍', sender: 'bob', sender_device_id: DEVICE_B }, 2),
    event({ type: 'receipt', client_id: id(), target_client_id: target, state: 'read', sender_device_id: DEVICE_B }, 3),
    event({ type: 'message', client_id: target, kind: 'text', content: 'base', sender: 'alice', sender_device_id: DEVICE_A }, 4),
  ])
  const base = messages.find((message) => message.client_id === target)
  const reply = messages.find((message) => message.client_id === replyId)
  assert.equal(reply.reply_to_content, 'base')
  assert.equal(base.reactions[0].emoji, '👍')
  assert.equal(base.receipts[DEVICE_B], 'read')
})

test('MLS errors are classified without exposing cryptographic internals to UI', () => {
  assert.equal(classifyMlsError(new Error('Duplicate message')).code, MLS_ERROR_CODES.DUPLICATE)
  assert.equal(classifyMlsError(new Error('message from a future epoch')).code, MLS_ERROR_CODES.MISSING_COMMIT)
  assert.equal(classifyMlsError(new Error('AEAD decryption failed')).code, MLS_ERROR_CODES.CORRUPTED_CIPHERTEXT)
  assert.equal(classifyMlsError(new Error('unexpected MLS message')).code, MLS_ERROR_CODES.PROTOCOL_VIOLATION)
})
