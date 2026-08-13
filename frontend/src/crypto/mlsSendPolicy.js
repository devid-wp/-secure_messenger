import { MLS_ERROR_CODES, MlsEnvelopeError } from './mlsErrors'

const blockedChats = new Map()

export function blockMlsSending(chatId, cause) {
  if (chatId === null || chatId === undefined) return
  blockedChats.set(String(chatId), cause)
}

export function mlsSendingBlocked(chatId) {
  return blockedChats.has(String(chatId))
}

export function assertMlsSendingAllowed(chatId) {
  const cause = blockedChats.get(String(chatId))
  if (!cause) return
  throw new MlsEnvelopeError(
    MLS_ERROR_CODES.RESYNC_REQUIRED,
    'Encrypted sending is blocked until an explicit MLS resync succeeds',
    cause,
  )
}

export async function explicitMlsResync(chatId, synchronize) {
  const result = await synchronize()
  blockedChats.delete(String(chatId))
  return result
}

export function resetMlsSendPolicyForTests() {
  blockedChats.clear()
}
