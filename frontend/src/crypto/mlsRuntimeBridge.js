let worker = null
let nextRequestId = 1
const pending = new Map()

function browserSupported() {
  return typeof Worker !== 'undefined' && typeof WebAssembly !== 'undefined'
    && typeof indexedDB !== 'undefined' && Boolean(globalThis.crypto?.subtle)
}

function getWorker() {
  if (!browserSupported()) throw new Error('This browser cannot provide the required MLS vault')
  if (worker) return worker
  worker = new Worker(new URL('./mls.worker.js', import.meta.url), { type: 'module', name: 'secure-messenger-mls' })
  worker.onmessage = ({ data }) => {
    const request = pending.get(data.id)
    if (!request) return
    pending.delete(data.id)
    if (data.error) request.reject(new Error(data.error))
    else request.resolve(data.result)
  }
  worker.onerror = (event) => {
    for (const request of pending.values()) request.reject(new Error(event.message || 'MLS worker crashed'))
    pending.clear()
    worker?.terminate()
    worker = null
  }
  return worker
}

function invokeWorker(method, arguments_ = {}) {
  const target = getWorker()
  const id = nextRequestId++
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    target.postMessage({ id, method, arguments: arguments_ })
  })
}

export function mlsRuntimeAvailable() { return browserSupported() }
export const initializeMls = (deviceId, packageCount) => invokeWorker('initialize', { deviceId, packageCount })
export const createMlsGroup = (_deviceId, chatId) => invokeWorker('createGroup', { chatId })
export const addMlsMembers = (chatId, keyPackages) => invokeWorker('addMembers', { chatId, keyPackages: keyPackages.map(bytesToBase64) })
export const joinMlsGroup = (welcome) => invokeWorker('join', { welcome })
export const encryptMls = (chatId, plaintext) => invokeWorker('encrypt', { chatId, plaintext })
export const processMls = (chatId, message) => invokeWorker('process', { chatId, message })
export const cachedMlsApplication = (message) => invokeWorker('cached', { message })
export const listMlsMembers = (chatId) => invokeWorker('members', { chatId })
export const removeMlsDevices = (chatId, deviceIds) => invokeWorker('remove', { chatId, deviceIds })
export const updateMlsGroup = (chatId) => invokeWorker('update', { chatId })
export const getVaultStatus = (deviceId) => invokeWorker('vaultStatus', { deviceId })
export const createVault = (deviceId, passphrase) => invokeWorker('createVault', { deviceId, passphrase })
export const migrateVault = (deviceId, passphrase) => invokeWorker('migrateVault', { deviceId, passphrase })
export const unlockVault = (deviceId, passphrase) => invokeWorker('unlockVault', { deviceId, passphrase })

export async function lockMlsRuntime() {
  if (!worker) return
  await invokeWorker('lock').catch(() => {})
  worker.terminate()
  worker = null
}

function bytesToBase64(bytes) {
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.slice(offset, offset + 0x8000))
  }
  return btoa(binary)
}
