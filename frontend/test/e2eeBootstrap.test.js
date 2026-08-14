import assert from 'node:assert/strict'
import { afterEach, test, vi } from 'vitest'

const initializeMls = vi.fn(async () => ({
  identityKey: Uint8Array.of(1, 2, 3),
  fingerprint: 'device-fingerprint',
  cipherSuite: 1,
  keyPackages: [],
}))

vi.mock('../src/crypto/mlsRuntimeBridge.js', () => ({
  initializeMls,
  mlsRuntimeAvailable: () => true,
}))

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

test('concurrent and repeated MLS bootstrap calls share one successful refresh', async () => {
  const fetch = vi.fn(async (url) => {
    if (String(url).endsWith('/key-packages/status')) {
      return { ok: true, status: 200, json: async () => ({ cipher_suite: 1, available: 20 }) }
    }
    return { ok: true, status: 200, json: async () => ({ device_id: 'device-1' }) }
  })
  vi.stubGlobal('fetch', fetch)
  const { resetDeviceMlsBootstrapForTests, synchronizeDeviceMls } = await import('../src/crypto/e2eeBootstrap.js')
  resetDeviceMlsBootstrapForTests()

  const calls = Array.from({ length: 5 }, () => synchronizeDeviceMls('token-1', 'device-1'))
  const results = await Promise.all(calls)
  const repeated = await synchronizeDeviceMls('token-1', 'device-1')

  assert.equal(initializeMls.mock.calls.length, 2)
  assert.equal(fetch.mock.calls.length, 2)
  assert.deepEqual(results[0], repeated)
})
