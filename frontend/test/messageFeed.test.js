import assert from 'node:assert/strict'
import { test } from 'vitest'
import { mergeMessageFeed, replacePendingStatus } from '../src/crypto/messageFeed.js'

test('mergeMessageFeed deduplicates a confirmed optimistic message and orders envelopes', () => {
  const confirmed = {
    id: 'mls:12', client_id: 'same', timestamp: '2026-08-13T12:00:00.000Z', status: 'sent', content: 'confirmed',
  }
  const messages = mergeMessageFeed([
    { id: 'mls:13', client_id: 'later', timestamp: '2026-08-13T12:00:01.000Z' },
    confirmed,
  ], [
    { id: 'pending:same', client_id: 'same', timestamp: '2026-08-13T12:00:00.000Z', status: 'sending', content: 'pending' },
    { id: 'pending:earlier', client_id: 'earlier', timestamp: '2026-08-13T11:59:59.000Z' },
  ])

  assert.deepEqual(messages.map((message) => message.client_id), ['earlier', 'same', 'later'])
  assert.equal(messages[1].content, 'confirmed')
})

test('replacePendingStatus only changes the requested optimistic message', () => {
  const result = replacePendingStatus([
    { client_id: 'retry', status: 'sending' },
    { client_id: 'other', status: 'sent' },
  ], 'retry', 'failed')
  assert.deepEqual(result, [
    { client_id: 'retry', status: 'failed' },
    { client_id: 'other', status: 'sent' },
  ])
})
