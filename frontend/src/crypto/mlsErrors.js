export const MLS_ERROR_CODES = Object.freeze({
  DUPLICATE: 'duplicate',
  STALE_EPOCH: 'stale_epoch',
  MISSING_COMMIT: 'missing_commit',
  CORRUPTED_CIPHERTEXT: 'corrupted_ciphertext',
  UNKNOWN_SENDER_DEVICE: 'unknown_sender_device',
  PROTOCOL_VIOLATION: 'protocol_violation',
  RESYNC_REQUIRED: 'resync_required',
})

export class MlsEnvelopeError extends Error {
  constructor(code, message, cause) {
    super(message, { cause })
    this.name = 'MlsEnvelopeError'
    this.code = code
  }
}

export function classifyMlsError(error) {
  if (error instanceof MlsEnvelopeError) return error
  const detail = String(error?.message || error || '').toLowerCase()
  if (/duplicate|replay|already (?:processed|consumed|exists)|secret.?reuse|no matching key.?package/.test(detail)) {
    return new MlsEnvelopeError(MLS_ERROR_CODES.DUPLICATE, 'Duplicate MLS envelope', error)
  }
  if (/stale|past epoch|too old|too.?distant.?in.?the.?past|epoch.*(?:past|old)/.test(detail)) {
    return new MlsEnvelopeError(MLS_ERROR_CODES.STALE_EPOCH, 'Stale MLS epoch', error)
  }
  if (/future epoch|epoch.*future|wrong.?epoch|missing.*commit|secret tree.*not found|generation.*out of bounds/.test(detail)) {
    return new MlsEnvelopeError(MLS_ERROR_CODES.MISSING_COMMIT, 'MLS Commit has not arrived yet', error)
  }
  if (/aead|ciphertext|decrypt|invalid signature|confirmation tag|malformed|tls codec|tls.*deserial/.test(detail)) {
    return new MlsEnvelopeError(MLS_ERROR_CODES.CORRUPTED_CIPHERTEXT, 'Corrupted MLS ciphertext', error)
  }
  return new MlsEnvelopeError(MLS_ERROR_CODES.PROTOCOL_VIOLATION, 'MLS protocol violation', error)
}

export function isExpectedMlsError(error) {
  const code = classifyMlsError(error).code
  return code === MLS_ERROR_CODES.DUPLICATE || code === MLS_ERROR_CODES.STALE_EPOCH
}
