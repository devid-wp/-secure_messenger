import { useEffect, useState } from 'react'
import LoginForm from './components/LoginForm'
import ChatApp from './components/ChatApp'
import {
  clearNativeSession,
  isDesktopRuntime,
  readNativeSession,
  saveNativeSession,
} from './crypto/desktopBridge'
import { synchronizeDeviceMls } from './crypto/e2eeBootstrap'
import { lockMlsRuntime } from './crypto/mlsRuntimeBridge'
import './App.css'

function App() {
  const desktop = isDesktopRuntime()
  const [token, setToken] = useState(null)
  const [login, setLogin] = useState(null)
  const [refreshToken, setRefreshToken] = useState(null)
  const [accessExpiresAt, setAccessExpiresAt] = useState(null)
  const [deviceId, setDeviceId] = useState(null)
  const [sessionReady, setSessionReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    localStorage.removeItem('token')
    localStorage.removeItem('login')
    const restore = async () => {
      const nativeSession = desktop ? await readNativeSession() : null
      const response = await fetch(
        `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/api/v1/auth/refresh`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            client_type: desktop ? 'desktop' : 'web',
            refresh_token: nativeSession?.refreshToken ?? null,
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
        if (desktop && data.refresh_token) {
          setRefreshToken(data.refresh_token)
          await saveNativeSession(data.refresh_token, data.login)
        }
      }
    }
    restore()
      .catch(async () => {
        if (desktop) await clearNativeSession().catch(() => {})
      })
      .finally(() => {
        if (!cancelled) setSessionReady(true)
      })
    return () => {
      cancelled = true
    }
  }, [desktop])

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
              client_type: desktop ? 'desktop' : 'web',
              refresh_token: desktop ? refreshToken : null,
            }),
          }
        )
        if (!response.ok) throw new Error('Session expired')
        const data = await response.json()
        setToken(data.access_token)
        setAccessExpiresAt(Date.now() + data.expires_in * 1000)
        setDeviceId(data.device_id)
        if (desktop && data.refresh_token) {
          setRefreshToken(data.refresh_token)
          await saveNativeSession(data.refresh_token, data.login)
        }
      } catch {
        setToken(null)
        setLogin(null)
        setRefreshToken(null)
        setAccessExpiresAt(null)
        setDeviceId(null)
        if (desktop) await clearNativeSession().catch(() => {})
      }
    }, delay)
    return () => window.clearTimeout(timer)
  }, [accessExpiresAt, desktop, refreshToken, token])

  const handleLogin = async (newToken, newLogin, data) => {
    if (desktop) {
      await saveNativeSession(data.refresh_token, newLogin)
      setRefreshToken(data.refresh_token)
    }
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
              client_type: desktop ? 'desktop' : 'web',
              refresh_token: desktop ? refreshToken : null,
            }),
          }
        )
      } catch {
        // Always clear local credentials, even when the API is unavailable.
      }
    }
    try {
      await lockMlsRuntime()
      if (desktop) {
        await clearNativeSession()
      } else {
        localStorage.removeItem('token')
        localStorage.removeItem('login')
      }
    } finally {
      setToken(null)
      setLogin(null)
      setRefreshToken(null)
      setAccessExpiresAt(null)
      setDeviceId(null)
    }
  }

  useEffect(() => {
    if (!token || !deviceId) return
    synchronizeDeviceMls(token, deviceId).catch(() => {
      // ChatApp keeps sending disabled until its MLS runtime is ready.
    })
  }, [deviceId, token])

  if (!sessionReady) {
    return <div className="app" aria-busy="true" />
  }

  return (
    <div className="app">
      {!token ? (
        <LoginForm onLogin={handleLogin} />
      ) : (
        <ChatApp token={token} login={login} deviceId={deviceId} onLogout={handleLogout} />
      )}
    </div>
  )
}

export default App
