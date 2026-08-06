import { useEffect, useState } from 'react'
import { createVault, getVaultStatus, migrateVault, unlockVault } from '../crypto/mlsRuntimeBridge'

export default function VaultGate({ deviceId, children }) {
  const [status, setStatus] = useState(null)
  const [passphrase, setPassphrase] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { getVaultStatus(deviceId).then(setStatus).catch((e) => setError(e.message)) }, [deviceId])
  if (status && !status.locked) return children
  const setup = !status?.exists || status?.migrationRequired
  const submit = async (event) => {
    event.preventDefault()
    if (setup && passphrase !== confirm) return setError('Passphrases do not match')
    setBusy(true); setError('')
    try {
      if (status?.migrationRequired) await migrateVault(deviceId, passphrase)
      else if (!status?.exists) await createVault(deviceId, passphrase)
      else await unlockVault(deviceId, passphrase)
      setPassphrase(''); setConfirm('')
      setStatus(await getVaultStatus(deviceId))
    } catch (caught) { setError(caught.message) } finally { setBusy(false) }
  }
  return <form className="login-card" onSubmit={submit}>
    <h1>{setup ? 'Protect this device' : 'Unlock this device'}</h1>
    <p>{setup ? 'Create a local passphrase for MLS keys. It cannot be recovered by the server.' : 'Enter the local vault passphrase.'}</p>
    <input type="password" autoComplete={setup ? 'new-password' : 'current-password'} minLength={10} required value={passphrase} onChange={(e) => setPassphrase(e.target.value)} placeholder="Local passphrase" />
    {setup && <input type="password" autoComplete="new-password" minLength={10} required value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Confirm passphrase" />}
    {error && <p role="alert">{error}</p>}
    <button type="submit" disabled={busy}>{busy ? 'Working…' : setup ? 'Create protected vault' : 'Unlock'}</button>
  </form>
}
