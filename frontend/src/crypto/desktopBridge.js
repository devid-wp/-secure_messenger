const NOT_DESKTOP = Object.freeze({
  available: false,
  protocol: 'MLS 1.0',
  implementation: 'OpenMLS 0.8.1',
  reason: 'Native cryptographic service is unavailable in the web client',
})

export async function getCryptoStatus() {
  if (!('__TAURI_INTERNALS__' in window)) return NOT_DESKTOP

  const { invoke } = await import('@tauri-apps/api/core')
  return invoke('crypto_status')
}
