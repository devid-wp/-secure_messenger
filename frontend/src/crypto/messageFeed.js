// Presentation-only helpers for the decrypted message feed. Keeping this
// outside ChatApp makes duplicate/reconnect ordering independently testable.

function sequence(message) {
  const id = String(message.id ?? '')
  const mlsId = id.match(/^mls:(\d+)$/)
  if (mlsId) return Number(mlsId[1])
  return Number.isSafeInteger(message.server_seq) ? message.server_seq : Number.MAX_SAFE_INTEGER
}

function timestamp(message) {
  const value = Date.parse(message.timestamp || '')
  return Number.isFinite(value) ? value : 0
}

export function mergeMessageFeed(decrypted, pending) {
  const messages = new Map()
  for (const message of decrypted) {
    if (message?.client_id) messages.set(message.client_id, message)
  }
  for (const message of pending) {
    if (!message?.client_id || messages.has(message.client_id)) continue
    messages.set(message.client_id, message)
  }
  return [...messages.values()].sort((left, right) => (
    timestamp(left) - timestamp(right)
    || sequence(left) - sequence(right)
    || String(left.client_id).localeCompare(String(right.client_id))
  ))
}

export function replacePendingStatus(messages, clientId, status) {
  return messages.map((message) => (
    message.client_id === clientId ? { ...message, status } : message
  ))
}
