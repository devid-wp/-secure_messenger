import assert from 'node:assert/strict'
import { test } from 'vitest'
import {
  APPLICATION_PAYLOAD_TYPES,
  APPLICATION_PAYLOAD_VERSION,
  APPLICATION_PAYLOAD_LIMITS,
  MAX_APPLICATION_PAYLOAD_BYTES,
  assertAuthenticatedPayloadSender,
  decodeApplicationPayload,
  encodeApplicationPayload,
  preflightApplicationPayload,
  validateApplicationPayload,
} from '../src/crypto/applicationPayload.js'

const ISO = '2026-08-07T12:34:56.000Z'
const DEVICE_ID = '11111111-1111-4111-8111-111111111111'

function clientId() {
  return crypto.randomUUID()
}

function baseMessage(overrides = {}) {
  return {
    version: APPLICATION_PAYLOAD_VERSION,
    type: 'message',
    client_id: clientId(),
    sender_device_id: DEVICE_ID,
    sent_at: ISO,
    body: { kind: 'text', content: 'hello' },
    ...overrides,
  }
}

function attachmentDescriptor(overrides = {}) {
  return {
    version: 1,
    algorithm: 'AES-256-GCM',
    object_id: clientId(),
    key: btoa(String.fromCharCode(...new Uint8Array(32).fill(1))),
    nonce: btoa(String.fromCharCode(...new Uint8Array(12).fill(2))),
    plaintext_size: 10,
    ciphertext_size: 26,
    sha256: btoa(String.fromCharCode(...new Uint8Array(32).fill(3))),
    ...overrides,
  }
}

test('module exports the protocol constants', () => {
  assert.equal(APPLICATION_PAYLOAD_VERSION, 1)
  assert.equal(MAX_APPLICATION_PAYLOAD_BYTES, 64 * 1024)
  assert.deepEqual(APPLICATION_PAYLOAD_TYPES, [
    'message', 'edit', 'delete', 'reaction', 'receipt',
    'attachment', 'group_metadata', 'device_event',
  ])
})

test('encode then decode round-trips a text message', () => {
  const id = clientId()
  const decoded = decodeApplicationPayload(encodeApplicationPayload({
    client_id: id,
    sender_device_id: DEVICE_ID,
    sent_at: ISO,
    kind: 'text',
    content: 'secret',
  }))
  assert.equal(decoded.client_id, id)
  assert.equal(decoded.sent_at, ISO)
  assert.equal(decoded.content, 'secret')
  assert.equal(decoded.kind, 'text')
  assert.equal(decoded.type, 'message')
})

test('canonical encoding is byte-identical across input field order and rejects alternate JSON', () => {
  const id = clientId()
  const first = encodeApplicationPayload({
    client_id: id, sender_device_id: DEVICE_ID, sent_at: ISO, kind: 'text', content: 'secret',
  })
  const second = encodeApplicationPayload({
    content: 'secret', kind: 'text', sent_at: ISO, sender_device_id: DEVICE_ID, client_id: id,
  })
  assert.deepEqual(first, second)

  const nonCanonical = new TextEncoder().encode(JSON.stringify(baseMessage({ client_id: id })))
  assert.throws(() => decodeApplicationPayload(nonCanonical), /canonically encoded/)
})

test('encode strips local UI fields and survives the forbidden-field check', () => {
  const id = clientId()
  const bytes = encodeApplicationPayload({
    client_id: id,
    sender_device_id: DEVICE_ID,
    sent_at: ISO,
    kind: 'text',
    content: 'hello',
    sender: 'alice',
    sender_login: 'alice',
    timestamp: ISO,
    id: 'pending:abc',
    chat_id: 7,
    server_seq: 12,
    status: 'sending',
    mls_epoch: 0,
    reply_to_server_seq: null,
    reply_to_client_id: null,
    reply_to_sender: null,
    reply_to_content: null,
    reply_preview: 'preview',
    file_name: 'evil.txt',
    mime_type: 'text/plain',
    group_name: 'leak',
  })
  const payload = JSON.parse(new TextDecoder().decode(bytes))
  assert.equal(payload.client_id, id)
  assert.equal(payload.sent_at, ISO)
  assert.equal(payload.body.content, 'hello')
  assert.equal(payload.body.kind, 'text')
  for (const forbidden of [
    'sender', 'sender_login', 'timestamp', 'id', 'chat_id',
    'server_seq', 'status', 'mls_epoch', 'reply_preview',
    'reply_to_server_seq', 'reply_to_client_id', 'reply_to_sender', 'reply_to_content',
    'file_name', 'mime_type', 'group_name',
  ]) {
    assert.ok(!(forbidden in payload.body), `${forbidden} must be stripped`)
  }
})

test('decode rejects payloads carrying forbidden fields', () => {
  const bytes = new TextEncoder().encode(JSON.stringify({
    ...baseMessage(),
    body: { kind: 'text', content: 'hi', sender: 'alice' },
  }))
  assert.throws(() => decodeApplicationPayload(bytes), /forbidden/)
})

test('rejects unknown top-level fields', () => {
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), critical: true }), /Unknown/)
})

test('rejects unknown versions and unknown types', () => {
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), version: 2 }), /version/)
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), type: 'broadcast' }), /type/)
  assert.throws(() => validateApplicationPayload({ ...baseMessage({ type: 'message' }), type: 'draft' }), /type/)
})

test('rejects invalid client_id UUIDs', () => {
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), client_id: 'not-a-uuid' }), /UUID/)
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), client_id: 42 }), /UUID/)
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), client_id: '00000000-0000-0000-0000-000000000000' }), /UUID/)
})

test('rejects non ISO-8601 sent_at', () => {
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), sent_at: 'tomorrow' }), /ISO-8601/)
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), sent_at: '2026-08-07' }), /ISO-8601/)
  assert.throws(() => validateApplicationPayload({ ...baseMessage(), sent_at: 123 }), /ISO-8601/)
})

test('edit and delete require a UUID target_client_id', () => {
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'edit',
    body: { target_client_id: 'not-uuid', content: 'x' },
  }), /target_client_id/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'delete',
    body: { target_client_id: clientId().replace(/-/g, 'x') },
  }), /target_client_id/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'edit',
    body: { target_client_id: clientId() }, // missing content
  }), /content/)
})

test('reaction and receipt validate emoji and state', () => {
  const tid = clientId()
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'reaction',
    body: { target_client_id: tid, emoji: '' },
  }), /emoji/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'receipt',
    body: { target_client_id: tid, state: 'pending' },
  }), /state/)
  const ok = validateApplicationPayload({
    ...baseMessage(),
    type: 'receipt',
    body: { target_client_id: tid, state: 'read' },
  })
  assert.equal(ok.body.state, 'read')
})

test('group_metadata requires a non-empty string name', () => {
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'group_metadata',
    body: { name: '' },
  }), /name/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'group_metadata',
    body: { name: 5 },
  }), /name/)
})

test('attachment descriptor must not carry filename or MIME type', () => {
  const descriptor = attachmentDescriptor()
  assert.doesNotThrow(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'attachment',
    body: { attachment_descriptor: descriptor },
  }))
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'attachment',
    body: { attachment_descriptor: { ...descriptor, name: 'leak.txt' } },
  }), /Unknown attachment descriptor field/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'attachment',
    body: { attachment_descriptor: { ...descriptor, media_type: 'image/png' } },
  }), /Unknown attachment descriptor field/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'attachment',
    body: { attachment_descriptor: { ...descriptor, algorithm: 'AES-256-CBC' } },
  }), /algorithm/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(),
    type: 'attachment',
    body: { attachment_descriptor: { ...descriptor, object_id: 'not-uuid' } },
  }), /object_id/)
})

test('encode strips optimistic UI fields from an attachment', () => {
  const descriptor = attachmentDescriptor()
  const payload = JSON.parse(new TextDecoder().decode(encodeApplicationPayload({
    id: 'pending:attachment',
    chat_id: 7,
    sender: 'alice',
    content: '',
    kind: 'file',
    attachment: { content_url: '/opaque/ciphertext' },
    attachment_descriptor: descriptor,
    client_id: clientId(),
    sender_device_id: DEVICE_ID,
    timestamp: ISO,
    status: 'sending',
  })))
  assert.equal(payload.type, 'attachment')
  assert.deepEqual(payload.body, { attachment_descriptor: descriptor })
})

test('text schema rejects wrong types, cross-kind fields, extras and limits', () => {
  assert.throws(() => validateApplicationPayload(baseMessage({ body: { kind: 1, content: 'x' } })), /kind/)
  assert.throws(() => validateApplicationPayload(baseMessage({ body: { kind: 'text', content: 7 } })), /string/)
  assert.throws(() => validateApplicationPayload(baseMessage({ body: { kind: 'text', content: 'x', sticker: {} } })), /another message kind/)
  assert.throws(() => validateApplicationPayload(baseMessage({ body: { kind: 'text', content: 'x', extra: true } })), /not allowed/)
  assert.throws(() => validateApplicationPayload(baseMessage({
    body: { kind: 'text', content: 'x'.repeat(APPLICATION_PAYLOAD_LIMITS.textBytes + 1) },
  })), /size limit/)
})

test('receipt schema rejects wrong types and extra fields', () => {
  const target = clientId()
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(), type: 'receipt', body: { target_client_id: target, state: 1 },
  }), /state/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(), type: 'receipt', body: { target_client_id: target, state: 'read', read_at: ISO },
  }), /forbidden/)
})

test('attachment schema rejects missing, extra, mistyped and oversized descriptor fields', () => {
  const payload = (descriptor) => ({ ...baseMessage(), type: 'attachment', body: { attachment_descriptor: descriptor } })
  const missing = attachmentDescriptor()
  delete missing.sha256
  assert.throws(() => validateApplicationPayload(payload(missing)), /required/)
  assert.throws(() => validateApplicationPayload(payload(attachmentDescriptor({ extension: 'png' }))), /Unknown/)
  assert.throws(() => validateApplicationPayload(payload(attachmentDescriptor({ plaintext_size: '10' }))), /plaintext_size/)
  assert.throws(() => validateApplicationPayload(payload(attachmentDescriptor({
    plaintext_size: APPLICATION_PAYLOAD_LIMITS.attachmentBytes + 1,
    ciphertext_size: APPLICATION_PAYLOAD_LIMITS.attachmentBytes + 17,
  }))), /size limit/)
  assert.throws(() => validateApplicationPayload(payload(attachmentDescriptor({ key: btoa('short') }))), /wrong length/)
})

test('membership event schema is an explicit bounded enum', () => {
  for (const event of ['member_added', 'member_removed', 'member_left', 'device_added', 'device_removed', 'credential_changed']) {
    assert.doesNotThrow(() => validateApplicationPayload({
      ...baseMessage(), type: 'device_event', body: { event },
    }))
  }
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(), type: 'device_event', body: { event: 'made_admin' },
  }), /membership event/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(), type: 'device_event', body: { event: 42 },
  }), /string/)
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(), type: 'device_event', body: { event: 'member_added', actor: 'alice' },
  }), /not allowed/)
})

test('encode rejects unknown outbound fields instead of silently downgrading schema', () => {
  assert.throws(() => encodeApplicationPayload({
    client_id: clientId(), sender_device_id: DEVICE_ID, sent_at: ISO,
    kind: 'text', content: 'hello', future_option: true,
  }), /Unknown outbound/)
})

test('payload limit is rejected before the caller mutates UI state', () => {
  let uiStateChanged = false
  assert.throws(() => {
    preflightApplicationPayload({
      client_id: clientId(), sent_at: ISO, kind: 'text',
      content: 'x'.repeat(APPLICATION_PAYLOAD_LIMITS.textBytes + 1),
    }, DEVICE_ID)
    uiStateChanged = true
  }, /size limit/)
  assert.equal(uiStateChanged, false)
})

test('decode rejects non-UTF-8 and non-JSON corruption', () => {
  assert.throws(() => decodeApplicationPayload(new Uint8Array([0xff, 0xfe, 0xfd])), /UTF-8|JSON|valid|bytes/)
  assert.throws(() => decodeApplicationPayload(new TextEncoder().encode('not-json')), /JSON/)
  assert.throws(() => decodeApplicationPayload(null), /bytes/)
  assert.throws(() => decodeApplicationPayload(new Uint8Array(0)), /size/)
})

test('decode rejects oversized payloads', () => {
  const huge = new Uint8Array(MAX_APPLICATION_PAYLOAD_BYTES + 1)
  assert.throws(() => decodeApplicationPayload(huge), /size/)
})

test('encode rejects missing client_id and missing sent_at', () => {
  assert.throws(() => encodeApplicationPayload({ kind: 'text', content: 'hi' }), /client_id/)
  assert.throws(() => encodeApplicationPayload({
    client_id: clientId(),
    sender_device_id: DEVICE_ID,
    kind: 'text',
    content: 'hi',
  }), /sent_at/)
})

test('encode strips forbidden fields instead of failing', () => {
  const bytes = encodeApplicationPayload({
    client_id: clientId(),
    sender_device_id: DEVICE_ID,
    sent_at: ISO,
    kind: 'text',
    content: 'hello',
    sender: 'alice',
    file_name: 'evil.txt',
    reply_preview: 'preview',
  })
  const payload = JSON.parse(new TextDecoder().decode(bytes))
  assert.equal(payload.body.kind, 'text')
  assert.equal(payload.body.content, 'hello')
  for (const forbidden of ['sender', 'file_name', 'reply_preview']) {
    assert.ok(!(forbidden in payload.body), `${forbidden} must be stripped`)
  }
})

test('encode accepts the older `timestamp` field as a fallback for sent_at', () => {
  const bytes = encodeApplicationPayload({
    client_id: clientId(),
    sender_device_id: DEVICE_ID,
    timestamp: ISO,
    kind: 'text',
    content: 'hi',
  })
  const payload = JSON.parse(new TextDecoder().decode(bytes))
  assert.equal(payload.sent_at, ISO)
  assert.ok(!('timestamp' in payload.body))
})

test('reply target and sender device are authenticated inside MLS payload', () => {
  const target = clientId()
  const payload = JSON.parse(new TextDecoder().decode(encodeApplicationPayload({
    client_id: clientId(), sender_device_id: DEVICE_ID, sent_at: ISO,
    kind: 'text', content: 'reply', reply: { target_client_id: target },
  })))
  assert.equal(payload.sender_device_id, DEVICE_ID)
  assert.doesNotThrow(() => assertAuthenticatedPayloadSender(payload, DEVICE_ID))
  assert.throws(() => assertAuthenticatedPayloadSender(payload, crypto.randomUUID()), /does not match/)
  assert.deepEqual(payload.body.reply, { target_client_id: target })
  assert.throws(() => validateApplicationPayload({
    ...baseMessage(), body: { kind: 'text', content: 'x', reply: { target_client_id: target, preview: 'leak' } },
  }), /reply/)
})
