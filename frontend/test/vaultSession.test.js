import assert from 'node:assert/strict'
import test from 'node:test'
import { publishVaultEvent, subscribeVaultEvents, VAULT_CHANNEL } from '../src/crypto/vaultSession.js'

test('vault lock and logout events are shared without secrets', () => {
  const original = globalThis.BroadcastChannel
  const messages = []
  class FakeChannel {
    constructor(name) { this.name = name }
    postMessage(message) { messages.push({ name: this.name, message }) }
    close() {}
  }
  globalThis.BroadcastChannel = FakeChannel
  try {
    publishVaultEvent('lock', 'device-a')
    publishVaultEvent('logout', 'device-a')
    assert.deepEqual(messages.map(({ name }) => name), [VAULT_CHANNEL, VAULT_CHANNEL])
    assert.deepEqual(messages.map(({ message }) => message.type), ['lock', 'logout'])
    assert.ok(!JSON.stringify(messages).includes('passphrase'))
  } finally { globalThis.BroadcastChannel = original }
})

test('subscription ignores unknown cross-tab event types', () => {
  const original = globalThis.BroadcastChannel
  let channel
  class FakeChannel {
    constructor() { channel = this }
    close() { this.closed = true }
  }
  globalThis.BroadcastChannel = FakeChannel
  try {
    const received = []
    const unsubscribe = subscribeVaultEvents((event) => received.push(event.type))
    channel.onmessage({ data: { type: 'passphrase', deviceId: 'device-a' } })
    channel.onmessage({ data: { type: 'lock', deviceId: 'device-a' } })
    assert.deepEqual(received, ['lock'])
    unsubscribe()
    assert.equal(channel.closed, true)
  } finally { globalThis.BroadcastChannel = original }
})
