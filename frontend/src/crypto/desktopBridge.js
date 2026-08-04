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

export async function initializeNativeMls(deviceId, packageCount) {
  if (!isDesktopRuntime()) return null
  return invokeDesktop('mls_initialize', { deviceId, packageCount })
}

export async function createNativeMlsGroup(deviceId, chatId) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_group_create', { deviceId, chatId: String(chatId) })
}

export async function addNativeMlsMembers(chatId, keyPackages) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_group_add', { chatId: String(chatId), keyPackages })
}

export async function joinNativeMlsGroup(welcome) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_group_join', { welcome })
}

export async function encryptNativeMls(chatId, plaintext) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_encrypt', { chatId: String(chatId), plaintext })
}

export async function processNativeMls(chatId, message) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_process', { chatId: String(chatId), message })
}

export async function readCachedMlsApplication(message) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_cached_application', { message })
}

export async function listNativeMlsMembers(chatId) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_group_members', { chatId: String(chatId) })
}

export async function removeNativeMlsDevices(chatId, deviceIds) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_remove_devices', { chatId: String(chatId), deviceIds })
}

export async function updateNativeMlsGroup(chatId) {
  if (!isDesktopRuntime()) throw new Error('MLS requires the desktop client')
  return invokeDesktop('mls_self_update', { chatId: String(chatId) })
}
