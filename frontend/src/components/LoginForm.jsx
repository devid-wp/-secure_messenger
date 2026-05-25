import { useState } from 'react'
import './LoginForm.css'

function LoginForm({ onLogin }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e, isRegister = false) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    const endpoint = isRegister ? '/register' : '/login'

    try {
      const response = await fetch(`http://localhost:8000${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ login, password }),
      })

      const data = await response.json()

      if (!response.ok) {
        setError(data.error || 'Ошибка при выполнении запроса')
        return
      }

      if (isRegister) {
        setError('')
        setLogin('')
        setPassword('')
        alert('Регистрация успешна! Теперь войдите.')
      } else {
        if (data.token) {
          onLogin(data.token, login)
        } else {
          setError('Невер­ные учётные данные')
        }
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
        <h1>🔐 Secure Messenger</h1>
        <form>
          <input
            type="text"
            placeholder="Логин"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            disabled={isLoading}
            required
          />
          <input
            type="password"
            placeholder="Пароль"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={isLoading}
            required
          />
          {error && <p className="error-message">{error}</p>}
          <div className="button-group">
            <button
              type="submit"
              onClick={(e) => handleSubmit(e, false)}
              disabled={isLoading}
            >
              {isLoading ? 'Загрузка...' : 'Войти'}
            </button>
            <button
              type="button"
              onClick={(e) => handleSubmit(e, true)}
              disabled={isLoading}
              className="register-btn"
            >
              {isLoading ? 'Загрузка...' : 'Зарегистрироваться'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default LoginForm
