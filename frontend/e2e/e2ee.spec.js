import { expect, test } from '@playwright/test'
import { Buffer } from 'node:buffer'
import process from 'node:process'

const ACCOUNT_PASSWORD = 'account-password-123'
const VAULT_PASSWORD = 'local-vault-password-123'
const CHANGED_VAULT_PASSWORD = 'changed-local-vault-password-456'
const MESSAGE = 'E2E_SENTINEL_8c36f2b4_message'
const OFFLINE_MESSAGE = 'E2E_SENTINEL_54e2c00a_offline_reconnect'
const FILE_PLAINTEXT = 'E2E_SENTINEL_71db60e9_file'
const GROUP_NAME = 'E2E_SENTINEL_a934e8f1_group_name'
const GROUP_MESSAGE = 'E2E_SENTINEL_f7c4102a_group_message'
const RUN_SUFFIX = Date.now().toString(36).slice(-6)
const API_BASE_URL = (
  process.env.PLAYWRIGHT_API_URL
  || process.env.PLAYWRIGHT_BASE_URL
  || 'http://127.0.0.1:8000'
).replace(/\/$/, '')

function uniqueLogin(base, testInfo) {
  return `${base}${RUN_SUFFIX}${testInfo.repeatEachIndex}${testInfo.retry}`
}

async function registerLoginAndCreateVault(page, login) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.locator('#login').fill(login)
  await page.locator('#password').fill(ACCOUNT_PASSWORD)
  await page.locator('#password-confirmation').fill(ACCOUNT_PASSWORD)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('status')).toContainText('Account created')
  await page.locator('#login').fill(login)
  await page.locator('#password').fill(ACCOUNT_PASSWORD)
  const loginResponse = page.waitForResponse((response) => response.url().endsWith('/api/v1/auth/login') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Sign in' }).click()
  const session = await (await loginResponse).json()
  await expect(page.getByRole('heading', { name: 'Protect this device' })).toBeVisible()
  await page.getByPlaceholder('Local passphrase').fill(VAULT_PASSWORD)
  await page.getByPlaceholder('Confirm passphrase').fill(VAULT_PASSWORD)
  const keyPackagesPublished = page.waitForResponse((response) => (
    response.url().endsWith('/api/v1/e2ee/key-packages')
      && response.request().method() === 'POST'
      && response.ok()
  ))
  await page.getByRole('button', { name: 'Create protected vault' }).click()
  await keyPackagesPublished
  await expect(page.getByText('Local vault unlocked')).toBeVisible()
  return session
}

async function reloadAndUnlock(page) {
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Unlock this device' })).toBeVisible()
  await page.getByPlaceholder('Local passphrase').fill(VAULT_PASSWORD)
  await page.getByRole('button', { name: 'Unlock' }).click()
  await expect(page.getByText('Local vault unlocked')).toBeVisible()
}

async function selectConversation(page, username) {
  await page.getByPlaceholder('Search @username or name').fill(username)
  const conversation = page.locator('.contact-item').filter({ hasText: username }).first()
  await expect(conversation).toBeVisible()
  await conversation.click()
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled()
  await expect(page.locator('.messages-skeleton')).toHaveCount(0)
}

test('group membership delivers encrypted metadata and application messages', async ({ browser, request }, testInfo) => {
  const ownerContext = await browser.newContext()
  const memberContext = await browser.newContext()
  const owner = await ownerContext.newPage()
  const member = await memberContext.newPage()
  const observedBodies = []
  const ownerLogin = uniqueLogin('e2egroupowner', testInfo)
  const memberLogin = uniqueLogin('e2egroupmember', testInfo)

  for (const page of [owner, member]) {
    page.on('request', (networkRequest) => {
      if (networkRequest.method() !== 'GET') observedBodies.push(networkRequest.postData() || '')
    })
  }

  const ownerSession = await registerLoginAndCreateVault(owner, ownerLogin)
  const memberSession = await registerLoginAndCreateVault(member, memberLogin)

  // Membership can only be granted to a known direct contact.
  await selectConversation(owner, memberLogin)
  const groupResponse = owner.waitForResponse((response) => (
    response.url().endsWith('/api/v1/chats/groups') && response.request().method() === 'POST'
  ))
  await owner.getByRole('button', { name: 'Create group', exact: true }).click()
  await owner.getByPlaceholder('Name your group').fill(GROUP_NAME)
  await owner.getByRole('button', { name: 'Create group', exact: true }).last().click()
  const group = await (await groupResponse).json()

  await expect(owner.getByRole('dialog', { name: 'New group' })).toHaveCount(0)
  await expect(owner.getByRole('button', { name: 'Conversation menu' })).toBeVisible()
  await owner.getByRole('button', { name: 'Conversation menu' }).click()
  await owner.getByRole('button', { name: 'Add member', exact: true }).click()
  await owner.getByPlaceholder('Exact login').fill(memberLogin)
  await owner.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(owner.getByRole('dialog', { name: 'Add member' })).toHaveCount(0)
  await expect(owner.getByText('2 members · online')).toBeVisible()

  // Sending after the membership update synchronizes the MLS group, producing
  // an Add Commit and Welcome before the application envelope.
  await owner.getByRole('textbox', { name: 'Message', exact: true }).fill(GROUP_MESSAGE)
  await owner.getByRole('button', { name: 'Send message' }).click()
  await expect(owner.getByText(GROUP_MESSAGE)).toBeVisible()

  let envelopes = []
  await expect.poll(async () => {
    const ownerEnvelopes = await (await request.get(
      `${API_BASE_URL}/api/v1/e2ee/chats/${group.id}/envelopes?after=0`,
      { headers: { Authorization: `Bearer ${ownerSession.access_token}` } },
    )).json()
    const memberEnvelopes = await (await request.get(
      `${API_BASE_URL}/api/v1/e2ee/chats/${group.id}/envelopes?after=0`,
      { headers: { Authorization: `Bearer ${memberSession.access_token}` } },
    )).json()
    envelopes = [...ownerEnvelopes, ...memberEnvelopes]
    const types = new Set(envelopes.map((item) => item.content_type))
    return ['commit', 'welcome', 'application'].every((type) => types.has(type))
  }).toBeTruthy()

  await reloadAndUnlock(member)
  const groupConversation = member.locator('.contact-item').filter({ hasText: GROUP_NAME }).first()
  await expect(groupConversation).toBeVisible()
  await groupConversation.click()
  await expect(member.getByText(GROUP_MESSAGE)).toBeVisible()

  expect(observedBodies.join('\n')).not.toContain(GROUP_NAME)
  expect(observedBodies.join('\n')).not.toContain(GROUP_MESSAGE)

  await ownerContext.close()
  await memberContext.close()
})

test('two browser devices keep messages, files, vault and post-removal epochs opaque', async ({ browser, request }, testInfo) => {
  const aliceContext = await browser.newContext()
  const bobContext = await browser.newContext()
  const aliceLostContext = await browser.newContext()
  const alice = await aliceContext.newPage()
  const bob = await bobContext.newPage()
  const aliceLost = await aliceLostContext.newPage()
  const observedBodies = []
  let uploadedMedia = null
  let newestApplication = null
  let aliceAccessToken
  let bobAccessToken
  const aliceLogin = uniqueLogin('e2ealice', testInfo)
  const bobLogin = uniqueLogin('e2ebob', testInfo)

  for (const page of [alice, bob, aliceLost]) {
    page.on('request', (networkRequest) => {
      if (networkRequest.method() !== 'GET') observedBodies.push(networkRequest.postData() || '')
    })
  }
  alice.on('response', async (response) => {
    if (/\/api\/v1\/auth\/(?:login|refresh)$/.test(response.url()) && response.ok()) {
      aliceAccessToken = (await response.json()).access_token
    }
    if (response.url().includes('/api/v1/media/attachments') && response.request().method() === 'POST' && response.ok()) uploadedMedia = await response.json()
    if (response.url().includes('/api/v1/e2ee/chats/') && response.url().endsWith('/envelopes') && response.request().method() === 'POST' && response.ok()) {
      const body = await response.json()
      if (body.content_type === 'application') newestApplication = body
    }
  })
  bob.on('response', async (response) => {
    if (/\/api\/v1\/auth\/(?:login|refresh)$/.test(response.url()) && response.ok()) {
      bobAccessToken = (await response.json()).access_token
    }
  })

  const aliceSession = await registerLoginAndCreateVault(alice, aliceLogin)
  const bobSession = await registerLoginAndCreateVault(bob, bobLogin)
  aliceAccessToken = aliceSession.access_token
  bobAccessToken = bobSession.access_token

  await selectConversation(alice, bobLogin)
  await reloadAndUnlock(bob)
  await selectConversation(bob, aliceLogin)
  await reloadAndUnlock(alice)
  await selectConversation(alice, bobLogin)
  await reloadAndUnlock(bob)
  await selectConversation(bob, aliceLogin)

  await alice.getByRole('textbox', { name: 'Message', exact: true }).fill(MESSAGE)
  await alice.getByRole('button', { name: 'Send message' }).click()
  await expect(alice.getByText(MESSAGE)).toBeVisible()
  await reloadAndUnlock(bob)
  await selectConversation(bob, aliceLogin)
  await expect(bob.getByText(MESSAGE)).toBeVisible()

  // An application composed while disconnected must remain in the encrypted
  // outbox. Reconnecting retries MLS synchronization and encryption; there is
  // no plaintext transport fallback while the API and WebSocket are offline.
  await aliceContext.setOffline(true)
  await expect(alice.getByText('Connection interrupted. Queued messages will retry automatically.')).toBeVisible()
  const applicationBeforeOffline = newestApplication?.id
  await alice.getByRole('textbox', { name: 'Message', exact: true }).fill(OFFLINE_MESSAGE)
  await alice.getByRole('button', { name: 'Send message' }).click()
  await expect(alice.getByText(OFFLINE_MESSAGE)).toBeVisible()
  expect(newestApplication?.id).toBe(applicationBeforeOffline)

  await aliceContext.setOffline(false)
  await expect.poll(() => newestApplication?.id, { timeout: 45_000 }).not.toBe(applicationBeforeOffline)
  await expect(alice.getByText('Connection interrupted. Queued messages will retry automatically.')).toHaveCount(0)
  await reloadAndUnlock(bob)
  await selectConversation(bob, aliceLogin)
  await expect(bob.getByText(OFFLINE_MESSAGE)).toBeVisible()

  await alice.route('**/api/v1/media/attachments', (route) => route.abort('connectionreset'), { times: 1 })
  const attachmentFixture = {
    name: 'secret.txt', mimeType: 'text/plain', buffer: Buffer.from(FILE_PLAINTEXT),
  }
  await alice.locator('input[type="file"].visually-hidden').setInputFiles(attachmentFixture)
  await expect(alice.locator('.attachment-progress')).toHaveCount(0)
  expect(uploadedMedia, 'an interrupted upload must not publish attachment metadata').toBeNull()

  // Selecting the same file again is an explicit retry. The input is reset
  // after every selection, so browsers must dispatch this second change.
  const applicationBeforeAttachment = newestApplication?.id
  await alice.locator('input[type="file"].visually-hidden').setInputFiles(attachmentFixture)
  await expect.poll(() => uploadedMedia).not.toBeNull()
  // Upload completion is not enough: MinIO can return before the browser has
  // encrypted and published the attachment descriptor as an MLS application
  // envelope.  Wait for the whole UI operation so a slow staging stack cannot
  // reload the recipient between those two durable writes.
  await expect(alice.locator('.attachment-progress')).toHaveCount(0)
  await expect.poll(() => newestApplication?.id).not.toBe(applicationBeforeAttachment)
  await reloadAndUnlock(bob)
  await selectConversation(bob, aliceLogin)
  const download = bob.getByText('Download decrypted file')
  await expect(download).toBeVisible()
  const recovered = await bob.evaluate(async () => {
    const link = document.querySelector('.message__file-download')
    return link ? await (await fetch(link.href)).text() : null
  })
  expect(recovered).toBe(FILE_PLAINTEXT)
  const stored = await request.get(`${API_BASE_URL}${uploadedMedia.content_url}`, {
    headers: { Authorization: `Bearer ${aliceAccessToken}` },
  })
  expect(stored.ok()).toBeTruthy()
  expect((await stored.body()).toString()).not.toContain(FILE_PLAINTEXT)

  await alice.getByRole('button', { name: 'Lock' }).click()
  await expect(alice.getByRole('heading', { name: 'Unlock this device' })).toBeVisible()
  await expect(alice.getByText(MESSAGE)).toHaveCount(0)
  await alice.getByPlaceholder('Local passphrase').fill(VAULT_PASSWORD)
  await alice.getByRole('button', { name: 'Unlock' }).click()
  await selectConversation(alice, bobLogin)
  await expect(alice.getByText(MESSAGE)).toBeVisible()

  await alice.getByRole('button', { name: 'Change passphrase' }).click()
  await alice.getByPlaceholder('Current passphrase').fill(VAULT_PASSWORD)
  await alice.getByPlaceholder('New passphrase', { exact: true }).fill(CHANGED_VAULT_PASSWORD)
  await alice.getByPlaceholder('Confirm new passphrase').fill(CHANGED_VAULT_PASSWORD)
  await alice.getByRole('button', { name: 'Save passphrase' }).click()
  await expect(alice.getByRole('heading', { name: 'Change local passphrase' })).toHaveCount(0)
  await alice.getByRole('button', { name: 'Lock' }).click()
  await alice.getByPlaceholder('Local passphrase').fill(VAULT_PASSWORD)
  await alice.getByRole('button', { name: 'Unlock' }).click()
  await expect(alice.getByRole('alert')).toContainText('local vault could not be opened')
  await alice.getByPlaceholder('Local passphrase').fill(CHANGED_VAULT_PASSWORD)
  await alice.getByRole('button', { name: 'Unlock' }).click()
  await selectConversation(alice, bobLogin)
  await expect(alice.getByText(MESSAGE)).toBeVisible()

  // Restore the fixture passphrase so subsequent reload checks continue to
  // exercise the shared reloadAndUnlock helper.
  await alice.getByRole('button', { name: 'Change passphrase' }).click()
  await alice.getByPlaceholder('Current passphrase').fill(CHANGED_VAULT_PASSWORD)
  await alice.getByPlaceholder('New passphrase', { exact: true }).fill(VAULT_PASSWORD)
  await alice.getByPlaceholder('Confirm new passphrase').fill(VAULT_PASSWORD)
  await alice.getByRole('button', { name: 'Save passphrase' }).click()

  const lostSession = await (async () => {
    await aliceLost.goto('/')
    await aliceLost.locator('#login').fill(aliceLogin)
    await aliceLost.locator('#password').fill(ACCOUNT_PASSWORD)
    const response = aliceLost.waitForResponse((item) => item.url().endsWith('/api/v1/auth/login') && item.request().method() === 'POST')
    await aliceLost.getByRole('button', { name: 'Sign in' }).click()
    const session = await (await response).json()
    await aliceLost.getByPlaceholder('Local passphrase').fill(VAULT_PASSWORD)
    await aliceLost.getByPlaceholder('Confirm passphrase').fill(VAULT_PASSWORD)
    await aliceLost.getByRole('button', { name: 'Create protected vault' }).click()
    return session
  })()
  await reloadAndUnlock(alice)
  let lostWelcome = null
  await expect.poll(async () => {
    const response = await request.get(`${API_BASE_URL}/api/v1/e2ee/chats/${newestApplication.chat_id}/envelopes?after=0`, {
      headers: { Authorization: `Bearer ${lostSession.access_token}` },
    })
    const envelopes = await response.json()
    lostWelcome = envelopes.find((item) => item.content_type === 'welcome' && item.recipient_device_id === lostSession.device_id) || null
    return Boolean(lostWelcome)
  }).toBeTruthy()
  const membershipEnvelopes = await (await request.get(
    `${API_BASE_URL}/api/v1/e2ee/chats/${newestApplication.chat_id}/envelopes?after=0`,
    { headers: { Authorization: `Bearer ${aliceAccessToken}` } },
  )).json()
  const addCommit = membershipEnvelopes.find((item) => (
    item.content_type === 'commit' && item.epoch === lostWelcome.epoch
  ))
  expect(addCommit, 'adding the independent lost-device profile publishes an Add Commit').toBeTruthy()
  expect(addCommit.epoch).toBeGreaterThan(newestApplication.epoch)
  await reloadAndUnlock(aliceLost)
  const lostJoined = await aliceLost.evaluate(async ({ chatId, deviceId, payload }) => {
    const bridge = await import('/src/crypto/mlsRuntimeBridge.js')
    await bridge.initializeMls(deviceId, 0)
    let members = await bridge.listMlsMembers(chatId).catch(() => [])
    if (!members.includes(deviceId)) {
      const bytes = Uint8Array.from(atob(payload), (value) => value.charCodeAt(0))
      await bridge.joinMlsGroup(bytes)
      members = await bridge.listMlsMembers(chatId)
    }
    return members.includes(deviceId)
  }, { chatId: newestApplication.chat_id, deviceId: lostSession.device_id, payload: lostWelcome.payload })
  expect(lostJoined).toBeTruthy()

  await reloadAndUnlock(bob)
  await selectConversation(bob, aliceLogin)
  await expect(bob.getByText(MESSAGE)).toBeVisible()
  await expect(bob.getByText('Contact credential or device set changed')).toBeVisible()
  const updateEpoch = await bob.evaluate(async ({ chatId, token }) => {
    const bridge = await import('/src/crypto/mlsRuntimeBridge.js')
    const messaging = await import('/src/crypto/e2eeMessaging.js')
    const update = await bridge.updateMlsGroup(chatId)
    const envelope = await messaging.publishEnvelope(token, chatId, 'commit', update.epoch, update.commit)
    return envelope.epoch
  }, { chatId: newestApplication.chat_id, token: bobAccessToken })
  expect(updateEpoch, 'Update Commit advances the epoch in an independent profile').toBe(addCommit.epoch + 1)
  await reloadAndUnlock(alice)
  await expect(alice.getByText(MESSAGE)).toBeVisible()
  await aliceLostContext.setOffline(true)

  await alice.getByRole('button', { name: 'Main menu' }).click()
  await alice.getByRole('menuitem', { name: 'Devices' }).click()
  const lostRow = alice.locator('.device-row').filter({ hasNotText: 'This device' }).filter({ hasText: 'ACTIVE' }).last()
  const revokeResponse = alice.waitForResponse((response) => (
    response.url().endsWith(`/api/v1/auth/devices/${lostSession.device_id}`)
      && response.request().method() === 'DELETE'
  ))
  alice.once('dialog', (dialog) => dialog.accept())
  await lostRow.getByRole('button', { name: 'Revoke' }).click()
  expect((await revokeResponse).ok()).toBeTruthy()
  const revokedRow = alice.locator('.device-row').filter({ hasNotText: 'This device' }).filter({ hasText: 'REVOKED' }).last()
  await expect(revokedRow).toBeVisible()
  await alice.getByRole('dialog', { name: 'Trusted devices' }).getByRole('button', { name: 'Close' }).click()

  let afterRevokeEnvelopes = []
  await expect.poll(async () => {
    afterRevokeEnvelopes = await (await request.get(
      `${API_BASE_URL}/api/v1/e2ee/chats/${newestApplication.chat_id}/envelopes?after=0`,
      { headers: { Authorization: `Bearer ${aliceAccessToken}` } },
    )).json()
    return afterRevokeEnvelopes.some((item) => (
      item.content_type === 'commit' && item.epoch > updateEpoch
    ))
  }, { timeout: 45_000 }).toBeTruthy()
  const removeCommit = afterRevokeEnvelopes
    .filter((item) => item.content_type === 'commit' && item.epoch > updateEpoch)
    .sort((left, right) => right.epoch - left.epoch)[0]
  expect(removeCommit, 'revoking the offline profile publishes a Remove Commit').toBeTruthy()
  expect(removeCommit.epoch).toBe(updateEpoch + 1)

  const afterRemoval = 'E2E_SENTINEL_after_device_removal'
  const previousApplicationId = newestApplication?.id
  await alice.getByRole('textbox', { name: 'Message', exact: true }).fill(afterRemoval)
  await alice.getByRole('button', { name: 'Send message' }).click()
  await expect.poll(() => newestApplication?.id).not.toBe(previousApplicationId)
  expect(newestApplication.epoch).toBe(removeCommit.epoch)
  const rejected = await aliceLost.evaluate(async ({ chatId, payload }) => {
    try {
      const bridge = await import('/src/crypto/mlsRuntimeBridge.js')
      const bytes = Uint8Array.from(atob(payload), (value) => value.charCodeAt(0))
      await bridge.processMls(chatId, bytes)
      return false
    } catch { return true }
  }, { chatId: newestApplication.chat_id, payload: newestApplication.payload })
  expect(rejected).toBeTruthy()
  expect(lostSession.device_id).not.toBe(aliceSession.device_id)

  expect(observedBodies.join('\n')).not.toContain(MESSAGE)
  expect(observedBodies.join('\n')).not.toContain(OFFLINE_MESSAGE)
  expect(observedBodies.join('\n')).not.toContain(FILE_PLAINTEXT)
  expect(observedBodies.join('\n')).not.toContain(afterRemoval)

  // Corrupt the authenticated state ciphertext at rest. Unlock must fail
  // closed and the locked UI must not render any previously decrypted text.
  await alice.getByRole('button', { name: 'Lock' }).click()
  await alice.evaluate(async (deviceId) => {
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open('secure-messenger-mls-v1', 1)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    await new Promise((resolve, reject) => {
      const transaction = database.transaction('state', 'readwrite')
      const store = transaction.objectStore('state')
      const request = store.get(deviceId)
      request.onsuccess = () => {
        const record = request.result
        const corrupted = new Uint8Array(record.state_ciphertext.slice(0))
        corrupted[corrupted.length - 1] ^= 0x01
        record.state_ciphertext = corrupted.buffer
        store.put(record, deviceId)
      }
      transaction.oncomplete = resolve
      transaction.onerror = () => reject(transaction.error)
    })
    database.close()
  }, aliceSession.device_id)
  await alice.getByPlaceholder('Local passphrase').fill(VAULT_PASSWORD)
  await alice.getByRole('button', { name: 'Unlock' }).click()
  await expect(alice.getByRole('alert')).toContainText('local vault could not be opened')
  await expect(alice.getByText(MESSAGE)).toHaveCount(0)

  await aliceContext.close()
  await bobContext.close()
  await aliceLostContext.close()
})
