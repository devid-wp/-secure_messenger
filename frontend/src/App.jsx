import { useState, useEffect } from 'react'
import LoginForm from './components/LoginForm'
import ChatApp from './components/ChatApp'
import './App.css'

function App() {
  const [token, setToken] = useState(null)
  const [login, setLogin] = useState(null)

  useEffect(() => {
    const savedToken = localStorage.getItem('token')
    const savedLogin = localStorage.getItem('login')
    if (savedToken && savedLogin) {
      setToken(savedToken)
      setLogin(savedLogin)
    }
  }, [])

  const handleLogin = (newToken, newLogin) => {
    localStorage.setItem('token', newToken)
    localStorage.setItem('login', newLogin)
    setToken(newToken)
    setLogin(newLogin)
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('login')
    setToken(null)
    setLogin(null)
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
