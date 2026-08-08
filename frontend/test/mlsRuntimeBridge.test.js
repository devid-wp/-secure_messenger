import assert from 'node:assert/strict'
import { afterEach, beforeEach, test, vi } from 'vitest'
import 'fake-indexeddb/auto'

let workers

class FakeWorker {
  constructor() {
    this.calls = []
    this.terminated = false
    workers.push(this)
  }

  postMessage(request) {
    this.calls.push(request)
    queueMicrotask(() => {
      const result = request.method === 'vaultStatus'
        ? { exists: true, version: 2, locked: true, migrationRequired: false }
        : true
      this.onmessage?.({ data: { id: request.id, result } })
    })
  }

  terminate() { this.terminated = true }
}

beforeEach(() => {
  workers = []
  vi.stubGlobal('Worker', FakeWorker)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

test('browser vault create, unlock and explicit lock stay inside the MLS worker', async () => {
  const bridge = await import('../src/crypto/mlsRuntimeBridge.js')
  const deviceId = crypto.randomUUID()
  await bridge.createVault(deviceId, 'correct horse battery staple')
  await bridge.unlockVault(deviceId, 'correct horse battery staple')
  await bridge.lockMlsRuntime()

  assert.deepEqual(workers[0].calls.map(({ method }) => method), ['createVault', 'unlockVault', 'lock'])
  assert.equal(workers[0].terminated, true)
  assert.ok(!JSON.stringify(workers[0].calls).includes('token'))

  await bridge.getVaultStatus(deviceId)
  assert.equal(workers.length, 2, 'post-lock access must create a fresh worker with no unlocked runtime')
})
