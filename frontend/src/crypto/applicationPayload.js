// Versioned MLS application payload.
//
// Every application message that leaves the device MUST pass through
// encodeApplicationPayload before MLS encryption and through
// decodeApplicationPayload after MLS decryption. The canonical shape is:
//
//   {
//     "version": 1,
//     "type": "message" | "edit" | "delete" | "reaction" | "receipt"
//           | "attachment" | "group_metadata" | "device_event",
//     "client_id": "<uuid v1-v8>",
//     "sent_at": "<ISO-8601>",
//     "body": { ...per-type body... }
//   }
//
// The server only ever sees the encrypted ciphertext in the outer MLS envelope;
// it MUST NOT parse, store or interpret this object. Validation happens after
// authenticated MLS decryption on the receiving device.

const VERSION = 1
const MAX_ENCODED_BYTES = 64 * 1024
const TYPES = Object.freeze([
  'message', 'edit', 'delete', 'reaction', 'receipt',
  'attachment', 'group_metadata', 'device_event',
])
const TYPE_SET = new Set(TYPES)
const TOP_LEVEL_FIELDS = Object.freeze(['version', 'type', 'client_id', 'sender_device_id', 'sent_at', 'body'])
const TOP_LEVEL_FIELDS_SET = new Set(TOP_LEVEL_FIELDS)
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const ISO_8601_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/
const encoder = new TextEncoder()

// Body fields that the UI fills in but that the server MUST never see. The
// wire body is the strict subset below; everything else is stripped before
// encryption and rejected after decryption. The list is enforced both ways.
const FORBIDDEN_BODY_FIELDS = new Set([
  // Identity / addressing
  'sender', 'sender_login', 'sender_device_id', 'username', 'display_name',
  // Replies and threads
  'reply_to', 'reply_preview', 'reply_to_server_seq', 'reply_to_client_id',
  'reply_to_sender', 'reply_to_content', 'thread_id', 'parent_client_id',
  // Attachments
  'attachment', 'file_name', 'mime_type', 'media_type', 'media_url', 'object_url',
  // Group metadata
  'group_name', 'chat_name', 'topic',
  // Timestamps that belong outside the encrypted body
  'edited_at', 'deleted_at', 'read_at', 'timestamp',
  // Local-only UI bookkeeping (outbox state)
  'id', 'chat_id', 'server_seq', 'status', 'mls_epoch',
  // Reaction convenience
  'reaction_emoji',
])

const BODY_SCHEMAS = Object.freeze({
  message: Object.freeze({
    required: ['kind'],
    optional: Object.freeze(['text', 'content', 'sticker', 'reply']),
    allowed: Object.freeze(['kind', 'text', 'content', 'sticker', 'reply']),
  }),
  edit: Object.freeze({
    required: ['target_client_id', 'content'],
    allowed: Object.freeze(['target_client_id', 'content']),
  }),
  delete: Object.freeze({
    required: ['target_client_id'],
    allowed: Object.freeze(['target_client_id']),
  }),
  reaction: Object.freeze({
    required: ['target_client_id', 'emoji'],
    allowed: Object.freeze(['target_client_id', 'emoji']),
  }),
  receipt: Object.freeze({
    required: ['target_client_id', 'state'],
    allowed: Object.freeze(['target_client_id', 'state']),
  }),
  attachment: Object.freeze({
    required: ['attachment_descriptor'],
    allowed: Object.freeze(['attachment_descriptor']),
  }),
  group_metadata: Object.freeze({
    required: ['name'],
    allowed: Object.freeze(['name']),
  }),
  device_event: Object.freeze({
    required: ['event'],
    allowed: Object.freeze(['event']),
  }),
})

function isUuid(value) {
  return typeof value === 'string' && UUID_RE.test(value)
}

function isStrictIso(value) {
  return typeof value === 'string' && ISO_8601_RE.test(value) && Number.isFinite(Date.parse(value))
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function inferType(body) {
  if (!isPlainObject(body)) return null
  if (body.operation === 'edit') return 'edit'
  if (body.operation === 'delete') return 'delete'
  if (body.operation === 'reaction') return 'reaction'
  if (body.operation === 'receipt') return 'receipt'
  if (body.operation === 'group_metadata') return 'group_metadata'
  if (body.operation === 'device_event') return 'device_event'
  if (body.attachment_descriptor) return 'attachment'
  return 'message'
}

function validateAttachmentDescriptor(descriptor) {
  if (!isPlainObject(descriptor)) throw new Error('Invalid attachment descriptor')
  if (descriptor.version !== 1) throw new Error('Unsupported attachment descriptor version')
  if (descriptor.algorithm !== 'AES-256-GCM') throw new Error('Unsupported attachment algorithm')
  if (!isUuid(descriptor.object_id)) throw new Error('Attachment object_id must be a UUID')
  if (typeof descriptor.key !== 'string' || descriptor.key.length === 0) throw new Error('Attachment key is required')
  if (typeof descriptor.nonce !== 'string' || descriptor.nonce.length === 0) throw new Error('Attachment nonce is required')
  // The server-side descriptor must never carry a file name or MIME type;
  // those live only inside the encrypted attachment itself or are derived
  // locally by the receiving device.
  if (Object.prototype.hasOwnProperty.call(descriptor, 'name')
    || Object.prototype.hasOwnProperty.call(descriptor, 'media_type')
    || Object.prototype.hasOwnProperty.call(descriptor, 'mime_type')
    || Object.prototype.hasOwnProperty.call(descriptor, 'file_name')) {
    throw new Error('Attachment descriptor must not leak filename or MIME type')
  }
}

function validateBody(type, body) {
  if (!isPlainObject(body)) throw new Error('Invalid MLS payload body')
  const schema = BODY_SCHEMAS[type]
  if (!schema) throw new Error('Unsupported MLS payload type')
  for (const field of Object.keys(body)) {
    if (FORBIDDEN_BODY_FIELDS.has(field)) {
      throw new Error(`Field "${field}" is forbidden in MLS application payload`)
    }
    if (!schema.allowed.includes(field)) {
      throw new Error(`Field "${field}" is not allowed for payload type "${type}"`)
    }
  }
  for (const required of schema.required) {
    if (!Object.prototype.hasOwnProperty.call(body, required)) {
      throw new Error(`Field "${required}" is required for payload type "${type}"`)
    }
  }
  if (type === 'edit' || type === 'delete' || type === 'reaction' || type === 'receipt') {
    if (!isUuid(body.target_client_id)) throw new Error('Mutation target_client_id must be a UUID')
  }
  if (type === 'edit' && (typeof body.content !== 'string' || body.content.length === 0)) {
    throw new Error('Edit body.content must be a non-empty string')
  }
  if (type === 'group_metadata' && (typeof body.name !== 'string' || body.name.length === 0)) {
    throw new Error('group_metadata body.name must be a non-empty string')
  }
  if (type === 'reaction' && (typeof body.emoji !== 'string' || body.emoji.length === 0)) {
    throw new Error('Reaction body.emoji must be a non-empty string')
  }
  if (type === 'receipt' && !['delivered', 'read'].includes(body.state)) {
    throw new Error('Receipt body.state must be "delivered" or "read"')
  }
  if (type === 'attachment') validateAttachmentDescriptor(body.attachment_descriptor)
  if (type === 'message' && body.reply !== undefined) {
    if (!isPlainObject(body.reply) || !isUuid(body.reply.target_client_id)
      || Object.keys(body.reply).some((field) => field !== 'target_client_id')) {
      throw new Error('Message reply must contain only a UUID target_client_id')
    }
  }
}

export function encodeApplicationPayload(body) {
  if (!isPlainObject(body)) throw new Error('MLS payload body must be an object')
  const type = inferType(body)
  if (!type || !TYPE_SET.has(type)) throw new Error('Cannot infer MLS payload type')
  if (!isUuid(body.client_id)) {
    throw new Error('MLS payload requires a UUID client_id')
  }
  if (!isUuid(body.sender_device_id)) {
    throw new Error('MLS payload requires a UUID sender_device_id')
  }
  const sentAt = body.sent_at ?? body.timestamp
  if (!isStrictIso(sentAt)) {
    throw new Error('MLS payload requires an ISO-8601 sent_at')
  }
  const value = {
    version: VERSION,
    type,
    client_id: body.client_id,
    sender_device_id: body.sender_device_id,
    sent_at: sentAt,
    body: Object.fromEntries(
      BODY_SCHEMAS[type].allowed
        .filter((field) => Object.prototype.hasOwnProperty.call(body, field))
        .map((field) => [field, body[field]]),
    ),
  }
  // Outbound payloads are built from the per-type allowlist. Local UI state,
  // type-inference markers and future fields therefore cannot cross the MLS
  // boundary by accident. Inbound payloads remain strict and reject extras.
  return encoder.encode(JSON.stringify(validateApplicationPayload(value)))
}

export function decodeApplicationPayload(bytes) {
  if (!(bytes instanceof Uint8Array)) throw new Error('Invalid MLS payload bytes')
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_ENCODED_BYTES) {
    throw new Error('Invalid MLS payload size')
  }
  let text
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    throw new Error('MLS payload is not valid UTF-8')
  }
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('MLS payload is not valid JSON')
  }
  const payload = validateApplicationPayload(parsed)
  // Return the body fields flat so the existing call sites can render
  // message text, edits and reactions without an extra `.body` hop. The
  // canonical wire shape (validateApplicationPayload) is still strictly
  // versioned and unknown-field free.
  return {
    ...payload.body,
    type: payload.type,
    client_id: payload.client_id,
    sender_device_id: payload.sender_device_id,
    sent_at: payload.sent_at,
  }
}

export function assertAuthenticatedPayloadSender(payload, envelopeSenderDeviceId) {
  if (!isUuid(envelopeSenderDeviceId) || payload?.sender_device_id !== envelopeSenderDeviceId) {
    throw new Error('Authenticated MLS sender does not match routed device')
  }
  return payload
}

export function validateApplicationPayload(value) {
  if (!isPlainObject(value)) throw new Error('Invalid MLS application payload')
  for (const field of Object.keys(value)) {
    if (!TOP_LEVEL_FIELDS_SET.has(field)) {
      throw new Error(`Unknown MLS payload field "${field}"`)
    }
  }
  if (value.version !== VERSION) {
    throw new Error(`Unsupported MLS payload version ${value.version}`)
  }
  if (!TYPE_SET.has(value.type)) {
    throw new Error(`Unsupported MLS payload type "${value.type}"`)
  }
  if (!isUuid(value.client_id)) {
    throw new Error('MLS payload client_id must be a UUID')
  }
  if (!isUuid(value.sender_device_id)) {
    throw new Error('MLS payload sender_device_id must be a UUID')
  }
  if (!isStrictIso(value.sent_at)) {
    throw new Error('MLS payload sent_at must be ISO-8601')
  }
  validateBody(value.type, value.body)
  if (encoder.encode(JSON.stringify(value)).byteLength > MAX_ENCODED_BYTES) {
    throw new Error('MLS payload exceeds 64 KiB limit')
  }
  return value
}

export const APPLICATION_PAYLOAD_VERSION = VERSION
export const APPLICATION_PAYLOAD_TYPES = TYPES
export const MAX_APPLICATION_PAYLOAD_BYTES = MAX_ENCODED_BYTES
