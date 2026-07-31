import { useState } from 'react'
import './LoginForm.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function localDeviceName() {
  const platform = navigator.platform || 'Unknown OS'
  const browser = navigator.userAgent.includes('Firefox') ? 'Firefox' : navigator.userAgent.includes('Edg/') ? 'Edge' : navigator.userAgent.includes('Chrome') ? 'Chrome' : 'Browser'
  return `${browser} on ${platform}`.slice(0, 128)
}

function LoginForm({ onLogin }) {
  const [mode, setMode] = useState('login')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const isRegister = mode === 'register'

  const switchMode = () => {
    setMode((current) => current === 'login' ? 'register' : 'login')
    setPassword('')
    setPasswordConfirmation('')
    setError('')
    setNotice('')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    if (isRegister && password !== passwordConfirmation) {
      setError('Passwords do not match')
      return
    }
    setIsLoading(true)

    const endpoint = isRegister ? '/api/v1/auth/register' : '/api/v1/auth/login'

    try {
      const response = await fetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login, password, device_name: localDeviceName() }),
      })

      const data = await response.json()

      if (!response.ok) {
        setError(data.detail || 'The request could not be completed')
        return
      }

      if (isRegister) {
        setPassword('')
        setPasswordConfirmation('')
        setMode('login')
        setNotice('Account created. Sign in with your new password.')
      } else if (data.token) {
        onLogin(data.token, login, data)
      } else {
        setError('Invalid credentials')
      }
    } catch (err) {
      setError('Network error: ' + err.message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="login-container">
      <div className="login-box">
        <div className="login-header">
          <div className="login-logo" aria-hidden="true">SM</div>
          <h1 className="login-title">
            {isRegister ? 'Create your account' : 'Secure Messenger'}
          </h1>
          <p className="login-subtitle">
            {isRegister
              ? 'Choose credentials for this development server'
              : 'End-to-end encryption is not enabled yet'}
          </p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-field">
            <input
              id="login"
              type="text"
              placeholder=" "
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              disabled={isLoading}
              autoComplete="username"
              required
            />
            <label htmlFor="login">Username</label>
          </div>

          <div className="login-field">
            <input
              id="password"
              type="password"
              placeholder=" "
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required
              minLength={8}
            />
            <label htmlFor="password">Password (8 characters minimum)</label>
          </div>

          {isRegister && (
            <div className="login-field">
              <input
                id="password-confirmation"
                type="password"
                placeholder=" "
                value={passwordConfirmation}
                onChange={(event) => setPasswordConfirmation(event.target.value)}
                disabled={isLoading}
                autoComplete="new-password"
                required
                minLength={8}
              />
              <label htmlFor="password-confirmation">Confirm password</label>
            </div>
          )}

          {error && <p className="error-message">{error}</p>}
          {notice && <p className="auth-notice" role="status">{notice}</p>}

          <div className="button-group">
            <button type="submit" className="login-btn" disabled={isLoading}>
              {isLoading ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
            </button>
            <button
              type="button"
              className="register-btn"
              onClick={switchMode}
              disabled={isLoading}
            >
              {isRegister ? 'Back to sign in' : 'Create account'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default LoginForm
