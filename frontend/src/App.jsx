import { useEffect, useState } from 'react'
import LoginForm from './components/LoginForm'
import ChatApp from './components/ChatApp'
import {
  clearNativeSession,
  isDesktopRuntime,
  readNativeSession,
  saveNativeSession,
} from './crypto/desktopBridge'
import './App.css'

function App() {
  const desktop = isDesktopRuntime()
  const [token, setToken] = useState(() => desktop ? null : localStorage.getItem('token'))
  const [login, setLogin] = useState(() => desktop ? null : localStorage.getItem('login'))
  const [sessionReady, setSessionReady] = useState(!desktop)

  useEffect(() => {
    if (!desktop) return
    let cancelled = false
    localStorage.removeItem('token')
    localStorage.removeItem('login')
    readNativeSession()
      .then((session) => {
        if (!cancelled && session) {
          setToken(session.token)
          setLogin(session.login)
        }
      })
      .catch(() => {
        // Keep the desktop signed out when native storage cannot be read.
      })
      .finally(() => {
        if (!cancelled) setSessionReady(true)
      })
    return () => {
      cancelled = true
    }
  }, [desktop])

  const handleLogin = async (newToken, newLogin) => {
    if (desktop) {
      await saveNativeSession(newToken, newLogin)
    } else {
      localStorage.setItem('token', newToken)
      localStorage.setItem('login', newLogin)
    }
    setToken(newToken)
    setLogin(newLogin)
  }

  const handleLogout = async () => {
    const currentToken = token
    if (currentToken) {
      try {
        await fetch(
          `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/api/v1/auth/logout`,
          {
            method: 'POST',
            headers: { Authorization: `Bearer ${currentToken}` },
          }
        )
      } catch {
        // Always clear local credentials, even when the API is unavailable.
      }
    }
    try {
      if (desktop) {
        await clearNativeSession()
      } else {
        localStorage.removeItem('token')
        localStorage.removeItem('login')
      }
    } finally {
      setToken(null)
      setLogin(null)
    }
  }

  if (!sessionReady) {
    return <div className="app" aria-busy="true" />
  }

  return (
    <div className="app">
      {!token ? (
        <LoginForm onLogin={handleLogin} />
      ) : (
        <ChatApp token={token} login={login} onLogout={handleLogout} />
      )}
    </div>
  )
}

export default App
