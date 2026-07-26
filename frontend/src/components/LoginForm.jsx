import { useState } from 'react'
import './LoginForm.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function LoginForm({ onLogin }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e, isRegister = false) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    const endpoint = isRegister ? '/api/v1/auth/register' : '/api/v1/auth/login'

    try {
      const response = await fetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login, password }),
      })

      const data = await response.json()

      if (!response.ok) {
        setError(data.detail || 'Ошибка при выполнении запроса')
        return
      }

      if (isRegister) {
        setLogin('')
        setPassword('')
        alert('Регистрация успешна! Теперь войдите.')
      } else if (data.token) {
        onLogin(data.token, login)
      } else {
        setError('Неверные учётные данные')
      }
    } catch (err) {
      setError('Ошибка сети: ' + err.message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="login-container">
      <div className="login-box">
        <div className="login-header">
          <div className="login-logo" aria-hidden="true">🔐</div>
          <h1 className="login-title">Secure Messenger</h1>
          <p className="login-subtitle">Защищённый мессенджер end-to-end</p>
        </div>

        <form className="login-form" onSubmit={(e) => handleSubmit(e, false)}>
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
            <label htmlFor="login">Логин</label>
          </div>

          <div className="login-field">
            <input
              id="password"
              type="password"
              placeholder=" "
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
              autoComplete="current-password"
              required
              minLength={8}
            />
            <label htmlFor="password">Пароль (мин. 8 символов)</label>
          </div>

          {error && <p className="error-message">{error}</p>}

          <div className="button-group">
            <button type="submit" className="login-btn" disabled={isLoading}>
              {isLoading ? 'Загрузка...' : 'Войти'}
            </button>
            <button
              type="button"
              className="register-btn"
              onClick={(e) => handleSubmit(e, true)}
              disabled={isLoading}
            >
              Зарегистрироваться
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default LoginForm
