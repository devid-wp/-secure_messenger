import {
  addMlsMembers, cachedMlsApplication, createMlsGroup, encryptMls,
  joinMlsGroup, listMlsMembers, mlsRuntimeAvailable, processMls,
  removeMlsDevices, updateMlsGroup,
} from './mlsRuntimeBridge'
import { synchronizeDeviceMls } from './e2eeBootstrap'
import { assertAuthenticatedPayloadSender, decodeApplicationPayload, encodeApplicationPayload, preflightApplicationPayload as preflightPayload } from './applicationPayload'
import { classifyMlsError, isExpectedMlsError, MLS_ERROR_CODES, MlsEnvelopeError } from './mlsErrors'
import { assertMlsSendingAllowed, blockMlsSending, explicitMlsResync, mlsSendingBlocked } from './mlsSendPolicy'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const deviceOwners = new Map()
const localDevicesByChat = new Map()

function authenticatedSender(envelope) {
  const owner = deviceOwners.get(envelope.sender_device_id)
  if (!owner) {
    throw new MlsEnvelopeError(MLS_ERROR_CODES.UNKNOWN_SENDER_DEVICE, 'MLS sender device is not in the authenticated directory')
  }
  return owner
}

function reportMlsIssue(error, envelope, chatId) {
  const classified = classifyMlsError(error)
  if (!isExpectedMlsError(classified)) blockMlsSending(chatId, classified)
  if (typeof globalThis.dispatchEvent === 'function' && typeof globalThis.CustomEvent === 'function') {
    globalThis.dispatchEvent(new CustomEvent('secure-messenger:mls-error', {
      detail: { code: classified.code, chatId, blocked: mlsSendingBlocked(chatId), envelopeId: envelope?.id ?? null, epoch: envelope?.epoch ?? null },
    }))
  }
  return classified
}

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
  localDevicesByChat.set(chatId, deviceId)
  if (!devices.some((device) => device.device_id === deviceId)) {
    throw new Error('This device has no published MLS identity')
  }

  const envelopes = await api(`/chats/${chatId}/envelopes?after=0`, token)
  const deferred = []
  for (const envelope of envelopes) {
    if (envelope.sender_device_id === deviceId) continue
    if (envelope.content_type === 'application') continue
    try {
      authenticatedSender(envelope)
      const wire = base64ToBytes(envelope.payload)
      if (envelope.content_type === 'welcome') await joinMlsGroup(wire)
      else await processMls(chatId, wire)
    } catch (error) {
      const classified = reportMlsIssue(error, envelope, chatId)
      if (classified.code === MLS_ERROR_CODES.MISSING_COMMIT) deferred.push(envelope)
      else if (!isExpectedMlsError(classified)) throw classified
    }
  }
  for (const envelope of deferred) {
    try {
      const wire = base64ToBytes(envelope.payload)
      if (envelope.content_type === 'welcome') await joinMlsGroup(wire)
      else await processMls(chatId, wire)
    } catch (error) {
      const classified = reportMlsIssue(error, envelope, chatId)
      if (!isExpectedMlsError(classified)) throw classified
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
  const expectedDevices = new Set(devices.map((device) => device.device_id))
  const removedDevices = [...currentMembers].filter((memberDeviceId) => (
    memberDeviceId !== deviceId && !expectedDevices.has(memberDeviceId)
  ))
  if (removedDevices.length) {
    const removed = await removeMlsDevices(chatId, removedDevices)
    await publishEnvelope(token, chatId, 'commit', removed.epoch, removed.commit)
    for (const removedDeviceId of removedDevices) currentMembers.delete(removedDeviceId)
  }
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
  // Check the fail-closed state before serializing application plaintext.
  assertMlsSendingAllowed(chatId)
  const senderDeviceId = localDevicesByChat.get(chatId)
  if (!senderDeviceId) throw new Error('MLS group must be synchronized before publishing')
  const reply = message.reply_to_client_id ? { target_client_id: message.reply_to_client_id } : undefined
  const plaintext = encodeApplicationPayload({ ...message, sender_device_id: senderDeviceId, reply })
  const encrypted = await encryptMls(chatId, plaintext)
  return publishEnvelope(token, chatId, 'application', encrypted.epoch, encrypted.ciphertext)
}

export function preflightApplicationPayload(message, senderDeviceId) {
  return preflightPayload(message, senderDeviceId)
}

export async function decryptEnvelope(chatId, envelope) {
  try {
    const sender = authenticatedSender(envelope)
    const wire = base64ToBytes(envelope.payload)
    if (envelope.content_type !== 'application') {
      await processMls(chatId, wire)
      return null
    }
    const cached = await cachedMlsApplication(wire)
    const plaintext = cached || (await processMls(chatId, wire)).plaintext
    const value = decodeApplicationPayload(Uint8Array.from(plaintext))
    try { assertAuthenticatedPayloadSender(value, envelope.sender_device_id) } catch (error) {
      throw new MlsEnvelopeError(MLS_ERROR_CODES.PROTOCOL_VIOLATION, error.message, error)
    }
    value.sender = sender
    return value
  } catch (error) {
    throw reportMlsIssue(error, envelope, chatId)
  }
}

export function isMlsSendingBlocked(chatId) {
  return mlsSendingBlocked(chatId)
}

export function resynchronizeMlsGroup(token, deviceId, chatId) {
  return explicitMlsResync(chatId, () => synchronizeMlsGroup(token, deviceId, chatId))
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
