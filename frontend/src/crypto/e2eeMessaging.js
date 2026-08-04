import {
  addMlsMembers, cachedMlsApplication, createMlsGroup, encryptMls,
  joinMlsGroup, listMlsMembers, mlsRuntimeAvailable, processMls,
  removeMlsDevices, updateMlsGroup,
} from './mlsRuntimeBridge'
import { synchronizeDeviceMls } from './e2eeBootstrap'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const encoder = new TextEncoder()
const decoder = new TextDecoder('utf-8', { fatal: true })
const deviceOwners = new Map()

function bytesToBase64(bytes) {
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.slice(offset, offset + 0x8000))
  }
  return btoa(binary)
}

function base64ToBytes(value) {
  const binary = atob(value)
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
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
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || `MLS request failed (${response.status})`)
  return response.status === 204 ? null : response.json()
}

export function e2eeAvailable() {
  return mlsRuntimeAvailable()
}

export async function publishEnvelope(token, chatId, contentType, epoch, bytes, recipientDeviceId = null) {
  return api(`/chats/${chatId}/envelopes`, token, {
    method: 'POST',
    body: JSON.stringify({
      content_type: contentType,
      epoch,
      payload: bytesToBase64(bytes),
      recipient_device_id: recipientDeviceId,
    }),
  })
}

export async function synchronizeMlsGroup(token, deviceId, chatId) {
  if (!mlsRuntimeAvailable()) throw new Error('Sending is disabled: this runtime has no MLS vault')
  await synchronizeDeviceMls(token, deviceId)
  const directory = await api(`/chats/${chatId}/devices`, token)
  const devices = directory.devices
  for (const device of devices) deviceOwners.set(device.device_id, device.login)
  if (!devices.some((device) => device.device_id === deviceId)) {
    throw new Error('This device has no published MLS identity')
  }

  const envelopes = await api(`/chats/${chatId}/envelopes?after=0`, token)
  for (const envelope of envelopes) {
    if (envelope.sender_device_id === deviceId) continue
    if (envelope.content_type === 'application') continue
    const wire = base64ToBytes(envelope.payload)
    try {
      if (envelope.content_type === 'welcome') await joinMlsGroup(wire)
      else await processMls(chatId, wire)
    } catch {
      // OpenMLS rejects duplicates, stale epochs and already-consumed Welcome
      // messages. Continue so a later, valid envelope can repair ordering.
    }
  }

  if (directory.coordinator_device_id !== deviceId) return
  let created = false
  try {
    await createMlsGroup(deviceId, chatId)
    created = true
  } catch (error) {
    if (!String(error).includes('already exists')) throw error
  }
  const currentMembers = new Set(await listMlsMembers(chatId))
  const missingDevices = devices.filter((device) => device.device_id !== deviceId && !currentMembers.has(device.device_id))
  if (!missingDevices.length) return
  const packages = []
  for (const device of missingDevices) {
    const claimed = await api(`/devices/${encodeURIComponent(device.device_id)}/key-package/claim`, token, { method: 'POST' })
    packages.push(claimed)
  }
  if (!packages.length) return
  const added = await addMlsMembers(chatId, packages.map((item) => base64ToBytes(item.key_package)))
  if (!created) await publishEnvelope(token, chatId, 'commit', added.epoch, added.commit)
  for (const target of packages) {
    await publishEnvelope(token, chatId, 'welcome', added.epoch, added.welcome, target.device_id)
  }
}

export async function encryptAndPublish(token, chatId, message) {
  const plaintext = encoder.encode(JSON.stringify(message))
  const encrypted = await encryptMls(chatId, plaintext)
  return publishEnvelope(token, chatId, 'application', encrypted.epoch, encrypted.ciphertext)
}

export async function decryptEnvelope(chatId, envelope) {
  if (envelope.content_type !== 'application') {
    await processMls(chatId, base64ToBytes(envelope.payload))
    return null
  }
  const wire = base64ToBytes(envelope.payload)
  const cached = await cachedMlsApplication(wire)
  if (cached) {
    const value = JSON.parse(decoder.decode(Uint8Array.from(cached)))
    value.sender = deviceOwners.get(envelope.sender_device_id)
    if (!value.sender) throw new Error('MLS sender device is not in the authenticated directory')
    return value
  }
  const processed = await processMls(chatId, wire)
  if (processed.kind !== 'application') return null
  const value = JSON.parse(decoder.decode(Uint8Array.from(processed.plaintext)))
  value.sender = deviceOwners.get(envelope.sender_device_id)
  if (!value.sender) throw new Error('MLS sender device is not in the authenticated directory')
  return value
}

export async function removeRevokedDevice(token, chatIds, deviceId) {
  const results = []
  for (const chatId of chatIds) {
    try {
      const commit = await removeMlsDevices(chatId, [deviceId])
      await publishEnvelope(token, chatId, 'commit', commit.epoch, commit.commit)
      results.push(chatId)
    } catch (error) {
      if (!String(error).includes('not an MLS group member') && !String(error).includes('not initialized')) throw error
    }
  }
  return results
}

export async function removeMlsMembers(token, chatId, deviceIds) {
  if (!deviceIds.length) return null
  const commit = await removeMlsDevices(chatId, deviceIds)
  await publishEnvelope(token, chatId, 'commit', commit.epoch, commit.commit)
  return commit.epoch
}

export async function rotateMlsEpoch(token, chatId) {
  const commit = await updateMlsGroup(chatId)
  await publishEnvelope(token, chatId, 'commit', commit.epoch, commit.commit)
  return commit.epoch
}
