import initWasm, { WasmMlsClient } from './wasm-generated/mls.js'
import { PBKDF2_ITERATIONS, randomBytes, rewrapDekRaw, unwrapDek, vaultAad, wrapNewDek } from './vaultCrypto.js'

const DB_NAME = 'secure-messenger-mls-v1'
const DB_VERSION = 1
const encoder = new TextEncoder()
let client = null
let activeDeviceId = null
let activeDek = null
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

async function deleteStore(store, key) {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(store, 'readwrite')
    transaction.objectStore(store).delete(key)
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

async function loadLegacyState(deviceId) {
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

async function createV2Record(deviceId, passphrase, state = new Uint8Array()) {
  const { dek, salt, wrapIv, wrappedDek } = await wrapNewDek(deviceId, passphrase)
  const stateIv = randomBytes(12)
  const stateCiphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: stateIv, additionalData: vaultAad(deviceId, 'state') }, dek, state)
  const record = {
    version: 2, device_id: deviceId,
    kdf: { name: 'PBKDF2-HMAC-SHA-256', salt, parameters: { iterations: PBKDF2_ITERATIONS } },
    wrapped_dek: wrappedDek, wrap_iv: wrapIv,
    state_ciphertext: stateCiphertext, state_iv: stateIv,
    updated_at: new Date().toISOString(),
  }
  await writeStore('state', deviceId, record)
  activeDek = dek
  return record
}

async function rewrapDek(deviceId, oldPassphrase, newPassphrase) {
  const record = await readStore('state', deviceId)
  if (!validV2(record, deviceId)) throw new Error('Invalid browser vault record')
  const dek = await unwrapDek(deviceId, oldPassphrase, record)
  // Re-wrap the same DEK under a fresh salt and IV. The DEK is preserved
  // so the state_ciphertext on the record stays valid; only the wrap
  // (kdf salt + wrapped_dek + wrap_iv) rotates.
  const wrapped = await rewrapDekRaw(dek, deviceId, newPassphrase)
  const previousWrapped = record.wrapped_dek
  const previousWrapIv = record.wrap_iv
  const previousSalt = record.kdf.salt
  const next = {
    ...record,
    kdf: { ...record.kdf, salt: wrapped.salt },
    wrapped_dek: wrapped.wrappedDek,
    wrap_iv: wrapped.wrapIv,
    updated_at: new Date().toISOString(),
  }
  try {
    await writeStore('state', deviceId, next)
  } catch (error) {
    activeDek = null
    throw error
  }
  activeDek = dek
  zeroBytes(previousWrapped)
  zeroBytes(previousWrapIv)
  zeroBytes(previousSalt)
  return next
}

function zeroBytes(view) {
  if (!view) return
  if (view instanceof Uint8Array) view.fill(0)
  else if (view instanceof ArrayBuffer) new Uint8Array(view).fill(0)
  else if (ArrayBuffer.isView(view)) view.buffer && new Uint8Array(view.buffer, view.byteOffset, view.byteLength).fill(0)
}

function requireUnlocked() {
  if (!activeDek) throw new Error('Browser vault is locked')
  if (!activeDeviceId) throw new Error('Browser vault has no active device')
}

function validV2(record, deviceId) {
  return record?.version === 2 && record.device_id === deviceId
    && record.kdf?.name === 'PBKDF2-HMAC-SHA-256'
    && Number.isSafeInteger(record.kdf.parameters?.iterations)
}

async function unlockV2(deviceId, passphrase) {
  const record = await readStore('state', deviceId)
  if (!validV2(record, deviceId)) throw new Error('Invalid browser vault record')
  try {
    activeDek = await unwrapDek(deviceId, passphrase, record)
    return new Uint8Array(await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: record.state_iv, additionalData: vaultAad(deviceId, 'state') }, activeDek, record.state_ciphertext,
    ))
  } catch {
    activeDek = null
    throw new Error('Incorrect passphrase or corrupted browser vault')
  }
}

async function loadState(deviceId) {
  const record = await readStore('state', deviceId)
  if (!record) return null
  if (record.version === 1) throw new Error('Browser vault migration is required')
  if (!activeDek) throw new Error('Browser vault is locked')
  return new Uint8Array(await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: record.state_iv, additionalData: vaultAad(deviceId, 'state') }, activeDek, record.state_ciphertext,
  ))
}

async function persist() {
  if (!client || !activeDeviceId) throw new Error('MLS worker is locked')
  requireUnlocked()
  const plaintext = client.export_state()
  const iv = randomBytes(12)
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: vaultAad(activeDeviceId, 'state') }, activeDek, plaintext
  )
  const record = await readStore('state', activeDeviceId)
  await writeStore('state', activeDeviceId, { ...record, state_ciphertext: ciphertext, state_iv: iv, updated_at: new Date().toISOString() })
  plaintext.fill(0)
}

function parse(value) { return typeof value === 'string' ? JSON.parse(value) : value }
function fromBase64(value) {
  const binary = atob(value)
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

const handlers = {
  async vaultStatus({ deviceId }) {
    const record = await readStore('state', deviceId)
    return { exists: Boolean(record), version: record?.version || null, locked: !activeDek || activeDeviceId !== deviceId, migrationRequired: record?.version === 1 }
  },
  async createVault({ deviceId, passphrase }) {
    if (await readStore('state', deviceId)) throw new Error('Browser vault already exists')
    activeDeviceId = deviceId
    await createV2Record(deviceId, passphrase)
    return true
  },
  async migrateVault({ deviceId, passphrase }) {
    const record = await readStore('state', deviceId)
    if (record?.version !== 1) throw new Error('No legacy browser vault found')
    const state = await loadLegacyState(deviceId)
    activeDeviceId = deviceId
    try {
      await createV2Record(deviceId, passphrase, state)
      await unlockV2(deviceId, passphrase)
      await deleteStore('keys', 'device-state')
    } catch (error) {
      activeDek = null
      await writeStore('state', deviceId, record)
      throw error
    } finally {
      state?.fill(0)
    }
    return true
  },
  async unlockVault({ deviceId, passphrase }) {
    activeDeviceId = deviceId
    await unlockV2(deviceId, passphrase)
    return true
  },
  async changePassphrase({ deviceId, oldPassphrase, newPassphrase }) {
    if (typeof oldPassphrase !== 'string' || typeof newPassphrase !== 'string') {
      throw new Error('Both old and new passphrases are required')
    }
    if (oldPassphrase.length < 10 || newPassphrase.length < 10) {
      throw new Error('Vault passphrase must contain at least 10 characters')
    }
    activeDeviceId = deviceId
    return rewrapDek(deviceId, oldPassphrase, newPassphrase)
  },
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
  async createGroup({ chatId }) {
    requireUnlocked()
    const value = parse(client.create_group(String(chatId))); await persist(); return value
  },
  async members({ chatId }) { return parse(client.group_members(String(chatId))) },
  async addMembers({ chatId, keyPackages }) {
    requireUnlocked()
    const value = parse(client.add_members(String(chatId), JSON.stringify(keyPackages)))
    await persist()
    return { commit: fromBase64(value.commit), welcome: fromBase64(value.welcome), epoch: value.epoch }
  },
  async join({ welcome }) {
    requireUnlocked()
    const value = parse(client.join_group(welcome)); await persist(); return value
  },
  async encrypt({ chatId, plaintext }) {
    requireUnlocked()
    const value = parse(client.encrypt(String(chatId), plaintext)); await persist()
    return { ciphertext: fromBase64(value.message), epoch: value.epoch }
  },
  async process({ chatId, message }) {
    requireUnlocked()
    const value = parse(client.process(String(chatId), message)); await persist()
    if (value.plaintext) value.plaintext = fromBase64(value.plaintext)
    return value
  },
  async cached({ message }) { const value = client.cached_application(message); return value ? fromBase64(value) : null },
  async remove({ chatId, deviceIds }) {
    requireUnlocked()
    const value = parse(client.remove_devices(String(chatId), JSON.stringify(deviceIds))); await persist()
    return { commit: fromBase64(value.message), epoch: value.epoch }
  },
  async update({ chatId }) {
    requireUnlocked()
    const value = parse(client.self_update(String(chatId))); await persist()
    return { commit: fromBase64(value.message), epoch: value.epoch }
  },
  async lock() {
    // Best-effort: tell the WASM client to drop its state, then null every
    // in-memory reference so the only way to use the vault again is to
    // unlock it. The Worker is terminated by the bridge; once it is gone,
    // WebAssembly linear memory is released by the runtime.
    if (client && typeof client.destroy === 'function') {
      try { client.destroy() } catch { /* best-effort */ }
    }
    client = null
    activeDek = null
    activeDeviceId = null
    return true
  },
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
