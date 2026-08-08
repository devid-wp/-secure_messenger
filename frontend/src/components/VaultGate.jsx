import { useCallback, useEffect, useRef, useState } from 'react'
import {
  changePassphrase,
  createVault,
  getVaultStatus,
  lockMlsRuntime,
  migrateVault,
  unlockVault,
} from '../crypto/mlsRuntimeBridge'
import { DEFAULT_IDLE_TIMEOUT_MS, publishVaultEvent, subscribeVaultEvents } from '../crypto/vaultSession'
import './VaultGate.css'

const genericError = 'The local vault could not be opened. Check the passphrase or local data.'

export default function VaultGate({ deviceId, children, onRemoteLogout, idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS }) {
  const [phase, setPhase] = useState('checking')
  const [passphrase, setPassphrase] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [changing, setChanging] = useState(false)
  const [oldPassphrase, setOldPassphrase] = useState('')
  const [newPassphrase, setNewPassphrase] = useState('')
  const [newConfirm, setNewConfirm] = useState('')
  const idleTimer = useRef(null)

  const refresh = useCallback(async () => {
    setPhase('checking')
    try {
      const status = await getVaultStatus(deviceId)
      if (status.migrationRequired) setPhase('migration_required')
      else if (!status.exists) setPhase('not_created')
      else setPhase(status.locked ? 'locked' : 'unlocked')
    } catch {
      setError(genericError)
      setPhase('error')
    }
  }, [deviceId])

  const lock = useCallback(async ({ broadcast = true } = {}) => {
    window.clearTimeout(idleTimer.current)
    await lockMlsRuntime()
    setChanging(false)
    setPassphrase('')
    setConfirm('')
    setPhase('locked')
    if (broadcast) publishVaultEvent('lock', deviceId)
  }, [deviceId])

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh() }, 0)
    return () => window.clearTimeout(timer)
  }, [refresh])

  useEffect(() => subscribeVaultEvents(async (event) => {
    if (event.deviceId !== deviceId) return
    await lock({ broadcast: false })
    if (event.type === 'logout') onRemoteLogout?.()
  }), [deviceId, lock, onRemoteLogout])

  useEffect(() => {
    if (phase !== 'unlocked') return undefined
    const reset = () => {
      window.clearTimeout(idleTimer.current)
      idleTimer.current = window.setTimeout(() => { void lock() }, idleTimeoutMs)
    }
    const events = ['pointerdown', 'keydown', 'touchstart']
    events.forEach((event) => window.addEventListener(event, reset, { passive: true }))
    reset()
    return () => {
      window.clearTimeout(idleTimer.current)
      events.forEach((event) => window.removeEventListener(event, reset))
    }
  }, [idleTimeoutMs, lock, phase])

  const submit = async (event) => {
    event.preventDefault()
    const setup = phase === 'not_created' || phase === 'migration_required'
    const migrationRequired = phase === 'migration_required'
    if (setup && passphrase !== confirm) return setError('Passphrases do not match.')
    setError('')
    setPhase('unlocking')
    try {
      if (migrationRequired) await migrateVault(deviceId, passphrase)
      else if (setup) await createVault(deviceId, passphrase)
      else await unlockVault(deviceId, passphrase)
      setPassphrase('')
      setConfirm('')
      setPhase('unlocked')
    } catch {
      setError(genericError)
      await refresh()
    }
  }

  const submitChange = async (event) => {
    event.preventDefault()
    if (newPassphrase !== newConfirm) return setError('New passphrases do not match.')
    setError('')
    try {
      await changePassphrase(deviceId, oldPassphrase, newPassphrase)
      setOldPassphrase('')
      setNewPassphrase('')
      setNewConfirm('')
      setChanging(false)
    } catch { setError('The local passphrase could not be changed.') }
  }

  if (phase === 'unlocked') return <>
    <div className="vault-toolbar" aria-label="Local vault controls">
      <span>Local vault unlocked</span>
      <button type="button" onClick={() => setChanging((value) => !value)}>Change passphrase</button>
      <button type="button" onClick={() => void lock()}>Lock</button>
    </div>
    {changing && <form className="vault-change" onSubmit={submitChange}>
      <h2>Change local passphrase</h2>
      <input type="password" autoComplete="current-password" required value={oldPassphrase} onChange={(e) => setOldPassphrase(e.target.value)} placeholder="Current passphrase" />
      <input type="password" autoComplete="new-password" minLength={10} required value={newPassphrase} onChange={(e) => setNewPassphrase(e.target.value)} placeholder="New passphrase" />
      <input type="password" autoComplete="new-password" minLength={10} required value={newConfirm} onChange={(e) => setNewConfirm(e.target.value)} placeholder="Confirm new passphrase" />
      {error && <p role="alert">{error}</p>}
      <button type="submit">Save passphrase</button>
    </form>}
    {children}
  </>

  const setup = phase === 'not_created' || phase === 'migration_required'
  return <form className="vault-gate" onSubmit={submit} aria-busy={phase === 'checking' || phase === 'unlocking'}>
    <h1>{setup ? (phase === 'migration_required' ? 'Upgrade local vault' : 'Protect this device') : 'Unlock this device'}</h1>
    <p>{setup ? 'Create a local passphrase for MLS keys. The server cannot recover it if you forget it.' : 'Enter the local vault passphrase to open encrypted chats.'}</p>
    <p className="vault-warning">The vault protects data while locked. It cannot protect an already unlocked app from XSS or a malicious browser extension.</p>
    <input type="password" autoComplete={setup ? 'new-password' : 'current-password'} minLength={10} required value={passphrase} onChange={(e) => setPassphrase(e.target.value)} placeholder="Local passphrase" />
    {setup && <input type="password" autoComplete="new-password" minLength={10} required value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Confirm passphrase" />}
    {error && <p role="alert">{error}</p>}
    <button type="submit" disabled={phase === 'checking' || phase === 'unlocking'}>{phase === 'unlocking' ? 'Working…' : setup ? 'Create protected vault' : 'Unlock'}</button>
  </form>
}
