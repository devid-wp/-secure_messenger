import { useEffect, useState } from 'react'
import LoginForm from './components/LoginForm'
import ChatApp from './components/ChatApp'
import VaultGate from './components/VaultGate'
import { lockMlsRuntime } from './crypto/mlsRuntimeBridge'
import { publishVaultEvent } from './crypto/vaultSession'
import './App.css'

function App() {
  const [token, setToken] = useState(null)
  const [login, setLogin] = useState(null)
  const [accessExpiresAt, setAccessExpiresAt] = useState(null)
  const [deviceId, setDeviceId] = useState(null)
  const [sessionReady, setSessionReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    localStorage.removeItem('token')
    localStorage.removeItem('login')
    const restore = async () => {
      const response = await fetch(
        `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/api/v1/auth/refresh`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            client_type: 'web',
            refresh_token: null,
          }),
        }
      )
      if (!response.ok) throw new Error('Session is unavailable')
      const data = await response.json()
      if (!cancelled) {
        setToken(data.access_token)
        setLogin(data.login)
        setAccessExpiresAt(Date.now() + data.expires_in * 1000)
        setDeviceId(data.device_id)
      }
    }
    restore()
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setSessionReady(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!token || !accessExpiresAt) return
    const delay = Math.max(1000, accessExpiresAt - Date.now() - 60_000)
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(
          `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/api/v1/auth/refresh`,
          {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              client_type: 'web',
              refresh_token: null,
            }),
          }
        )
        if (!response.ok) throw new Error('Session expired')
        const data = await response.json()
        setToken(data.access_token)
        setAccessExpiresAt(Date.now() + data.expires_in * 1000)
        setDeviceId(data.device_id)
      } catch {
        await lockMlsRuntime()
        publishVaultEvent('logout', deviceId)
        setToken(null)
        setLogin(null)
        setAccessExpiresAt(null)
        setDeviceId(null)
      }
    }, delay)
    return () => window.clearTimeout(timer)
  }, [accessExpiresAt, deviceId, token])

  const handleLogin = async (newToken, newLogin, data) => {
    setToken(newToken)
    setLogin(newLogin)
    setAccessExpiresAt(Date.now() + data.expires_in * 1000)
    setDeviceId(data.device_id)
  }

  const handleLogout = async () => {
    const currentToken = token
    if (currentToken) {
      try {
        await fetch(
          `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/api/v1/auth/logout`,
          {
            method: 'POST',
            credentials: 'include',
            headers: {
              Authorization: `Bearer ${currentToken}`,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              client_type: 'web',
              refresh_token: null,
            }),
          }
        )
      } catch {
        // Always clear local credentials, even when the API is unavailable.
      }
    }
    try {
      await lockMlsRuntime()
      publishVaultEvent('logout', deviceId)
      localStorage.removeItem('token')
      localStorage.removeItem('login')
    } finally {
      setToken(null)
      setLogin(null)
      setAccessExpiresAt(null)
      setDeviceId(null)
    }
  }

  const handleRemoteLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('login')
    setToken(null)
    setLogin(null)
    setAccessExpiresAt(null)
    setDeviceId(null)
  }

  if (!sessionReady) {
    return <div className="app" aria-busy="true" />
  }

  return (
    <div className="app">
      {!token ? (
        <LoginForm onLogin={handleLogin} />
      ) : (
        <VaultGate deviceId={deviceId} onRemoteLogout={handleRemoteLogout}>
          <ChatApp token={token} login={login} deviceId={deviceId} onLogout={handleLogout} />
        </VaultGate>
      )}
    </div>
  )
}

export default App
