import initWasm, { WasmMlsClient } from './wasm-generated/mls.js'

const DB_NAME = 'secure-messenger-mls-v1'
const DB_VERSION = 1
const encoder = new TextEncoder()
let client = null
let activeDeviceId = null
let wasmReady = null

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const database = request.result
      if (!database.objectStoreNames.contains('keys')) database.createObjectStore('keys')
      if (!database.objectStoreNames.contains('state')) database.createObjectStore('state')
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function readStore(store, key) {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(store, 'readonly')
    const request = transaction.objectStore(store).get(key)
    request.onsuccess = () => resolve(request.result ?? null)
    request.onerror = () => reject(request.error)
    transaction.oncomplete = () => database.close()
  })
}

async function writeStore(store, key, value) {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(store, 'readwrite')
    transaction.objectStore(store).put(value, key)
    transaction.oncomplete = () => { database.close(); resolve(undefined) }
    transaction.onerror = () => { database.close(); reject(transaction.error) }
  })
}

async function vaultKey() {
  let key = await readStore('keys', 'device-state')
  if (key) return key
  key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
  await writeStore('keys', 'device-state', key)
  return key
}

async function loadState(deviceId) {
  const record = await readStore('state', deviceId)
  if (!record) return null
  if (record.version !== 1 || !(record.iv instanceof Uint8Array) || !(record.ciphertext instanceof ArrayBuffer)) {
    throw new Error('Invalid encrypted MLS vault record')
  }
  const plaintext = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: record.iv, additionalData: encoder.encode(`secure-messenger:${deviceId}:v1`) },
    await vaultKey(), record.ciphertext
  )
  return new Uint8Array(plaintext)
}

async function persist() {
  if (!client || !activeDeviceId) throw new Error('MLS worker is locked')
  const plaintext = client.export_state()
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: encoder.encode(`secure-messenger:${activeDeviceId}:v1`) },
    await vaultKey(), plaintext
  )
  await writeStore('state', activeDeviceId, { version: 1, iv, ciphertext })
  plaintext.fill(0)
}

function parse(value) { return typeof value === 'string' ? JSON.parse(value) : value }
function fromBase64(value) {
  const binary = atob(value)
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

const handlers = {
  async initialize({ deviceId, packageCount }) {
    if (!wasmReady) wasmReady = initWasm()
    await wasmReady
    if (client && activeDeviceId !== deviceId) client = null
    activeDeviceId = deviceId
    if (!client) client = new WasmMlsClient(deviceId, await loadState(deviceId) || new Uint8Array())
    const result = parse(client.bootstrap(packageCount))
    await persist()
    return {
      identityKey: fromBase64(result.identity_key),
      fingerprint: result.fingerprint,
      cipherSuite: result.cipher_suite,
      keyPackages: result.key_packages.map(fromBase64),
    }
  },
  async createGroup({ chatId }) { const value = parse(client.create_group(String(chatId))); await persist(); return value },
  async members({ chatId }) { return parse(client.group_members(String(chatId))) },
  async addMembers({ chatId, keyPackages }) {
    const value = parse(client.add_members(String(chatId), JSON.stringify(keyPackages)))
    await persist()
    return { commit: fromBase64(value.commit), welcome: fromBase64(value.welcome), epoch: value.epoch }
  },
  async join({ welcome }) { const value = parse(client.join_group(welcome)); await persist(); return value },
  async encrypt({ chatId, plaintext }) {
    const value = parse(client.encrypt(String(chatId), plaintext)); await persist()
    return { ciphertext: fromBase64(value.message), epoch: value.epoch }
  },
  async process({ chatId, message }) {
    const value = parse(client.process(String(chatId), message)); await persist()
    if (value.plaintext) value.plaintext = fromBase64(value.plaintext)
    return value
  },
  async cached({ message }) { const value = client.cached_application(message); return value ? fromBase64(value) : null },
  async remove({ chatId, deviceIds }) {
    const value = parse(client.remove_devices(String(chatId), JSON.stringify(deviceIds))); await persist()
    return { commit: fromBase64(value.message), epoch: value.epoch }
  },
  async update({ chatId }) {
    const value = parse(client.self_update(String(chatId))); await persist()
    return { commit: fromBase64(value.message), epoch: value.epoch }
  },
  async lock() { client = null; activeDeviceId = null; return true },
}

self.onmessage = async ({ data }) => {
  const { id, method, arguments: args } = data
  try {
    if (!handlers[method]) throw new Error(`Unknown MLS worker method: ${method}`)
    const result = await handlers[method](args || {})
    self.postMessage({ id, result })
  } catch (caught) {
    self.postMessage({ id, error: caught instanceof Error ? caught.message : String(caught) })
  }
}
