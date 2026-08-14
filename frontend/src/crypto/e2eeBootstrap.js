import { initializeMls, mlsRuntimeAvailable } from './mlsRuntimeBridge'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
export const KEY_PACKAGE_TARGET = 20
export const BOOTSTRAP_REFRESH_MS = 60_000
const completedBootstrap = new Map()
const pendingBootstrap = new Map()

function bytesToBase64(bytes) {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

async function api(path, token, options = {}) {
  const response = await fetch(`${API_URL}/api/v1/e2ee${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
  if (!response.ok) throw new Error(`E2EE bootstrap failed (${response.status})`)
  return response.status === 204 ? null : response.json()
}

async function performDeviceMlsSync(token, deviceId) {
  if (!mlsRuntimeAvailable() || !token || !deviceId) return null

  const inventory = await api('/key-packages/status', token)
  if (inventory.cipher_suite !== 1) throw new Error('Unsupported MLS ciphersuite')
  const missing = Math.max(0, KEY_PACKAGE_TARGET - inventory.available)
  const material = await initializeMls(deviceId, missing)

  const identity = await api('/identity', token, {
    method: 'PUT',
    body: JSON.stringify({ identity_key: bytesToBase64(material.identityKey) }),
  })
  if (material.keyPackages.length) {
    const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
    await api('/key-packages', token, {
      method: 'POST',
      body: JSON.stringify({
        key_packages: material.keyPackages.map(bytesToBase64),
        cipher_suite: material.cipherSuite,
        expires_at: expiresAt,
      }),
    })
  }
  return { ...identity, available: inventory.available + material.keyPackages.length }
}

export async function synchronizeDeviceMls(token, deviceId) {
  if (!mlsRuntimeAvailable() || !token || !deviceId) return null
  // Device ids are globally unique. Do not retain bearer tokens in the
  // process-wide cache after the session has refreshed or logged out.
  const cacheKey = deviceId
  const completed = completedBootstrap.get(cacheKey)
  if (completed && completed.expiresAt > Date.now()) {
    // A lock terminates the Worker and drops the in-memory WasmMlsClient. The
    // server registration may still be fresh, but the encrypted local state
    // must be restored into the new Worker before any group operation.
    await initializeMls(deviceId, 0)
    return completed.value
  }
  const pending = pendingBootstrap.get(cacheKey)
  if (pending) return pending

  const synchronization = performDeviceMlsSync(token, deviceId)
    .then((value) => {
      completedBootstrap.set(cacheKey, { value, expiresAt: Date.now() + BOOTSTRAP_REFRESH_MS })
      return value
    })
    .finally(() => pendingBootstrap.delete(cacheKey))
  pendingBootstrap.set(cacheKey, synchronization)
  return synchronization
}

export function resetDeviceMlsBootstrapForTests() {
  completedBootstrap.clear()
  pendingBootstrap.clear()
}
