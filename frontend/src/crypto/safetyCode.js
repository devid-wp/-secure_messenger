function hex(bytes) { return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('') }

async function fingerprint(identityKey) {
  if (typeof identityKey !== 'string' || !identityKey) throw new Error('Complete device credentials are required')
  let bytes
  try {
    const binary = atob(identityKey)
    bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
  } catch {
    throw new Error('Invalid device credential encoding')
  }
  return hex(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
}

export async function createSafetyCode(identitySets, verifiedCredentials) {
  if (!Array.isArray(verifiedCredentials)) throw new Error('Verified MLS device credentials are required')
  const identities = identitySets.flat().map(({ login, device_id, identity_key, fingerprint: claimedFingerprint }) => ({
    login, device_id, identity_key, claimedFingerprint,
  }))
    .sort((a, b) => `${a.login}:${a.device_id}`.localeCompare(`${b.login}:${b.device_id}`))
  const credentials = new Map(verifiedCredentials.map((item) => [item.device_id, item]))
  if (identities.length < 2 || credentials.size !== identities.length || credentials.size !== verifiedCredentials.length) {
    throw new Error('MLS device set does not match the identity directory')
  }
  const seen = new Set()
  for (const identity of identities) {
    if (!identity.login || !identity.device_id || seen.has(identity.device_id)) throw new Error('Invalid or duplicate device identity')
    seen.add(identity.device_id)
    const derived = await fingerprint(identity.identity_key)
    const credential = credentials.get(identity.device_id)
    if (!credential || derived !== identity.claimedFingerprint?.toLowerCase()
      || identity.identity_key !== credential.identity_key || derived !== credential.fingerprint?.toLowerCase()) {
      throw new Error('Device credential verification failed')
    }
    identity.fingerprint = derived
    delete identity.identity_key
    delete identity.claimedFingerprint
  }
  const canonical = identities.map((item) => `${item.login}:${item.device_id}:${item.fingerprint.toLowerCase()}`).join('\n')
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`secure-messenger-safety-v1\n${canonical}`)))
  const digits = [...digest].map((byte) => byte.toString().padStart(3, '0')).join('').slice(0, 60)
  return {
    display: digits.match(/.{1,5}/g).join(' '),
    qrPayload: JSON.stringify({ version: 1, digest: hex(digest), identities }),
  }
}
