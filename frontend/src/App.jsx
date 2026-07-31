import { useState } from 'react'
import LoginForm from './components/LoginForm'
import ChatApp from './components/ChatApp'
import DeviceApproval from './components/DeviceApproval'
import './App.css'

function readPairingState() {
  try {
    return JSON.parse(localStorage.getItem('device_pairing') || 'null')
  } catch {
    return null
  }
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('token'))
  const [login, setLogin] = useState(() => localStorage.getItem('login'))
  const [deviceStatus, setDeviceStatus] = useState(() => localStorage.getItem('device_status') || 'active')
  const [pairing, setPairing] = useState(readPairingState)

  const handleLogin = (newToken, newLogin, loginData) => {
    localStorage.setItem('token', newToken)
    localStorage.setItem('login', newLogin)
    localStorage.setItem('device_status', loginData.device_status || 'active')
    if (loginData.pairing_code) localStorage.setItem('device_pairing', JSON.stringify(loginData))
    setToken(newToken)
    setLogin(newLogin)
    setDeviceStatus(loginData.device_status || 'active')
    setPairing(loginData.pairing_code ? loginData : null)
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
    localStorage.removeItem('token')
    localStorage.removeItem('login')
    localStorage.removeItem('device_status')
    localStorage.removeItem('device_pairing')
    setToken(null)
    setLogin(null)
    setDeviceStatus('active')
    setPairing(null)
  }

  return (
    <div className="app">
      {!token ? (
        <LoginForm onLogin={handleLogin} />
      ) : deviceStatus === 'pending' ? (
        <DeviceApproval
          token={token}
          pairing={pairing}
          onApproved={() => {
            localStorage.setItem('device_status', 'active')
            localStorage.removeItem('device_pairing')
            setDeviceStatus('active')
            setPairing(null)
          }}
          onLogout={handleLogout}
        />
      ) : (
        <ChatApp token={token} login={login} onLogout={handleLogout} />
      )}
    </div>
  )
}

export default App
