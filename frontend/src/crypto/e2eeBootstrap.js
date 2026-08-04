import { initializeMls, mlsRuntimeAvailable } from './mlsRuntimeBridge'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
export const KEY_PACKAGE_TARGET = 20

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

export async function synchronizeDeviceMls(token, deviceId) {
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
