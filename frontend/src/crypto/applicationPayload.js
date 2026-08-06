const VERSION = 1
const MAX_ENCODED_BYTES = 64 * 1024
const TYPES = new Set([
  'message', 'edit', 'delete', 'reaction', 'receipt', 'attachment',
  'group_metadata', 'device_event',
])
const TOP_LEVEL_FIELDS = new Set(['version', 'type', 'client_id', 'sent_at', 'body'])
const encoder = new TextEncoder()

function isUuid(value) {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
}

function payloadType(body) {
  if (body.operation) return body.operation
  return ['image', 'file'].includes(body.kind) ? 'attachment' : 'message'
}

export function encodeApplicationPayload(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('MLS payload body must be an object')
  const value = {
    version: VERSION,
    type: payloadType(body),
    client_id: isUuid(body.client_id) ? body.client_id : crypto.randomUUID(),
    sent_at: body.timestamp || new Date().toISOString(),
    body,
  }
  return encoder.encode(JSON.stringify(validateApplicationPayload(value)))
}

export function decodeApplicationPayload(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.byteLength > MAX_ENCODED_BYTES) throw new Error('Invalid MLS payload size')
  const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
  const payload = validateApplicationPayload(value)
  return { ...payload.body, client_id: payload.body.client_id || payload.client_id, timestamp: payload.body.timestamp || payload.sent_at }
}

export function validateApplicationPayload(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid MLS application payload')
  if (Object.keys(value).some((field) => !TOP_LEVEL_FIELDS.has(field))) throw new Error('Unknown MLS payload field')
  if (value.version !== VERSION) throw new Error('Unsupported MLS payload version')
  if (!TYPES.has(value.type)) throw new Error('Unsupported MLS payload type')
  if (!isUuid(value.client_id)) throw new Error('Invalid MLS payload client_id')
  if (typeof value.sent_at !== 'string' || !Number.isFinite(Date.parse(value.sent_at))) throw new Error('Invalid MLS payload timestamp')
  if (!value.body || typeof value.body !== 'object' || Array.isArray(value.body)) throw new Error('Invalid MLS payload body')
  if (value.type === 'edit' || value.type === 'delete') {
    if (!isUuid(value.body.target_client_id)) throw new Error('MLS mutation requires target_client_id')
  }
  if (value.type === 'attachment') {
    const descriptor = value.body.attachment_descriptor
    if (!descriptor || descriptor.version !== 1 || descriptor.algorithm !== 'AES-256-GCM'
      || !isUuid(descriptor.object_id) || typeof descriptor.key !== 'string'
      || typeof descriptor.nonce !== 'string' || typeof descriptor.name !== 'string'
      || typeof descriptor.media_type !== 'string') throw new Error('Invalid encrypted attachment descriptor')
  }
  if (encoder.encode(JSON.stringify(value)).byteLength > MAX_ENCODED_BYTES) throw new Error('MLS payload is too large')
  return value
}

export const APPLICATION_PAYLOAD_VERSION = VERSION
export const MAX_APPLICATION_PAYLOAD_BYTES = MAX_ENCODED_BYTES
