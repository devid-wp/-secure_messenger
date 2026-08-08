export const VAULT_CHANNEL = 'secure-messenger-vault-v1'
export const DEFAULT_IDLE_TIMEOUT_MS = 15 * 60 * 1000

export function publishVaultEvent(type, deviceId) {
  if (typeof BroadcastChannel === 'undefined') return
  const channel = new BroadcastChannel(VAULT_CHANNEL)
  channel.postMessage({ type, deviceId, sentAt: Date.now() })
  channel.close()
}

export function subscribeVaultEvents(handler) {
  if (typeof BroadcastChannel === 'undefined') return () => {}
  const channel = new BroadcastChannel(VAULT_CHANNEL)
  channel.onmessage = ({ data }) => {
    if (data?.type === 'lock' || data?.type === 'logout') handler(data)
  }
  return () => channel.close()
}
