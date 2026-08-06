function hex(bytes) { return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('') }

export async function createSafetyCode(identitySets) {
  const identities = identitySets.flat().map(({ login, device_id, fingerprint }) => ({ login, device_id, fingerprint }))
    .sort((a, b) => `${a.login}:${a.device_id}`.localeCompare(`${b.login}:${b.device_id}`))
  if (identities.length < 2 || identities.some((item) => !/^[0-9a-f]{64}$/i.test(item.fingerprint))) throw new Error('Complete device fingerprints are required')
  const canonical = identities.map((item) => `${item.login}:${item.device_id}:${item.fingerprint.toLowerCase()}`).join('\n')
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`secure-messenger-safety-v1\n${canonical}`)))
  const digits = [...digest].map((byte) => byte.toString().padStart(3, '0')).join('').slice(0, 60)
  return {
    display: digits.match(/.{1,5}/g).join(' '),
    qrPayload: JSON.stringify({ version: 1, digest: hex(digest), identities }),
  }
}
