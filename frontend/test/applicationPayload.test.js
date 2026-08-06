import assert from 'node:assert/strict'
import test from 'node:test'
import { decodeApplicationPayload, encodeApplicationPayload, validateApplicationPayload } from '../src/crypto/applicationPayload.js'

test('round trips a versioned message payload', () => {
  const clientId = crypto.randomUUID()
  const decoded = decodeApplicationPayload(encodeApplicationPayload({ client_id: clientId, kind: 'text', content: 'secret' }))
  assert.equal(decoded.client_id, clientId)
  assert.equal(decoded.content, 'secret')
})

test('rejects unknown versions, fields and invalid mutation targets', () => {
  const base = { version: 1, type: 'message', client_id: crypto.randomUUID(), sent_at: new Date().toISOString(), body: {} }
  assert.throws(() => validateApplicationPayload({ ...base, version: 2 }))
  assert.throws(() => validateApplicationPayload({ ...base, critical: true }))
  assert.throws(() => validateApplicationPayload({ ...base, type: 'edit' }))
})
