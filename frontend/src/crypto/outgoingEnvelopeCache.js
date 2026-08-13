// Retries must reuse the same randomized MLS ciphertext. This cache is
// deliberately memory-only: locking or reloading destroys it with the worker.
const pending = new Map()

export async function getRetryableEnvelope(key, encrypt) {
  if (pending.has(key)) return pending.get(key)
  const envelope = await encrypt()
  pending.set(key, envelope)
  return envelope
}

export function confirmRetryableEnvelope(key) {
  pending.delete(key)
}

export function clearRetryableEnvelopes() {
  pending.clear()
}
