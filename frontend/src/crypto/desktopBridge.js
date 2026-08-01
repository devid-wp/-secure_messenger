const NOT_DESKTOP = Object.freeze({
  available: false,
  protocol: 'MLS 1.0',
  implementation: 'OpenMLS 0.8.1',
  reason: 'Native cryptographic service is unavailable in the web client',
})

export function isDesktopRuntime() {
  return '__TAURI_INTERNALS__' in window
}

async function invokeDesktop(command, arguments_ = {}) {
  if (!isDesktopRuntime()) return null
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke(command, arguments_)
}

export async function getCryptoStatus() {
  if (!isDesktopRuntime()) return NOT_DESKTOP

  return invokeDesktop('crypto_status')
}

export async function getVaultStatus() {
  return invokeDesktop('vault_status')
}

export async function saveNativeSession(refreshToken, login) {
  if (!isDesktopRuntime()) return false
  await invokeDesktop('session_set', { refreshToken, login })
  return true
}

export async function readNativeSession() {
  return invokeDesktop('session_current')
}

export async function clearNativeSession() {
  if (!isDesktopRuntime()) return false
  await invokeDesktop('session_clear')
  return true
}
