import { useEffect, useMemo, useRef, useState } from 'react'
import { useTheme } from '../ThemeContext'
import './ChatApp.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const WS_URL = API_URL.replace(/^http/, 'ws')

const DEFAULT_CONTACTS = ['Alice', 'Bob', 'Charlie', 'Diana']

// Стабильный цвет аватарки на основе строки (Discord-style)
const AVATAR_COLORS = [
  '#5865f2', '#3ba55d', '#faa61a', '#ed4245',
  '#9b59b6', '#1abc9c', '#e67e22', '#e84393',
]

function avatarColor(login) {
  let hash = 0
  for (let i = 0; i < login.length; i++) {
    hash = login.charCodeAt(i) + ((hash << 5) - hash)
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]
}

function Avatar({ name, size = 40 }) {
  const initial = name.charAt(0).toUpperCase()
  return (
    <div
      className="avatar"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.45,
        backgroundColor: avatarColor(name),
      }}
      aria-hidden="true"
    >
      {initial}
    </div>
  )
}

function ChatApp({ token, login, onLogout }) {
  const { theme, toggle } = useTheme()
  const [contacts] = useState(DEFAULT_CONTACTS)
  const [selectedContact, setSelectedContact] = useState(DEFAULT_CONTACTS[0])
  const [messages, setMessages] = useState([])
  const [inputText, setInputText] = useState('')
  const [wsReady, setWsReady] = useState(false)
  const wsRef = useRef(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // WebSocket
  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}/ws/${token}`)
    wsRef.current = ws
    setWsReady(false)

    ws.onopen = () => setWsReady(true)
    ws.onclose = () => setWsReady(false)
    ws.onerror = () => { /* ошибка уже залогирована в консоль */ }
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        setMessages((prev) => [
          ...prev,
          {
            from: data.from,
            text: data.text,
            timestamp: new Date().toLocaleTimeString('ru-RU', {
              hour: '2-digit',
              minute: '2-digit',
            }),
          },
        ])
      } catch {
        /* невалидный payload — пропускаем */
      }
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [token])

  // История сообщений
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const response = await fetch(`${API_URL}/messages`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!response.ok || cancelled) return
        const data = await response.json()
        if (!cancelled) {
          setMessages(
            data.map((msg) => ({
              from: msg.sender,
              text: msg.content,
              timestamp: msg.timestamp,
            }))
          )
        }
      } catch {
        /* сеть недоступна — оставляем пустую ленту */
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [selectedContact, token])

  // Группировка сообщений по «дню» — для будущих разделителей
  const messageItems = useMemo(() => messages, [messages])

  const sendMessage = (e) => {
    e?.preventDefault()
    const ws = wsRef.current
    const text = inputText.trim()
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return

    ws.send(JSON.stringify({ to: selectedContact, text }))
    setMessages((prev) => [
      ...prev,
      {
        from: login,
        text,
        timestamp: new Date().toLocaleTimeString('ru-RU', {
          hour: '2-digit',
          minute: '2-digit',
        }),
      },
    ])
    setInputText('')
    inputRef.current?.focus()
  }

  const handleLogout = () => {
    wsRef.current?.close()
    onLogout()
  }

  return (
    <div className="chat-container">
      {/* Сервер-рейл (Discord-style) */}
      <aside className="server-rail" aria-label="Сервер">
        <div className="server-icon server-icon--active" title="Secure Messenger">
          🔐
        </div>
      </aside>

      {/* Каналы / чаты */}
      <aside className="channel-panel" aria-label="Чаты">
        <header className="channel-header">
          <h2>Secure Messenger</h2>
        </header>

        <div className="channel-section-title">Прямые сообщения</div>
        <nav className="channel-list">
          {contacts.map((contact) => (
            <button
              key={contact}
              className={`channel-item ${selectedContact === contact ? 'active' : ''}`}
              onClick={() => setSelectedContact(contact)}
            >
              <Avatar name={contact} size={32} />
              <span className="channel-name">{contact}</span>
            </button>
          ))}
        </nav>

        <div className="user-bar">
          <Avatar name={login} size={32} />
          <div className="user-bar__info">
            <div className="user-bar__name">{login}</div>
            <div className="user-bar__status">в сети</div>
          </div>
          <div className="user-bar__actions">
            <button
              className="icon-btn"
              onClick={toggle}
              title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
              aria-label="Переключить тему"
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            <button className="icon-btn" onClick={handleLogout} title="Выйти" aria-label="Выйти">
              ⎋
            </button>
          </div>
        </div>
      </aside>

      {/* Чат */}
      <main className="chat-panel">
        <header className="chat-header">
          <div className="chat-header__title">
            <span className="hash">#</span>
            <span>{selectedContact}</span>
          </div>
          <div className="chat-header__meta">
            <span className={`status-dot ${wsReady ? 'online' : 'offline'}`} />
            <span>{wsReady ? 'в сети' : 'подключение...'}</span>
          </div>
        </header>

        <div className="messages-list">
          {messageItems.length === 0 && (
            <div className="messages-empty">
              <div className="messages-empty__icon">💬</div>
              <p>Сообщений пока нет. Начните беседу!</p>
            </div>
          )}
          {messageItems.map((msg, idx) => {
            const own = msg.from === login
            return (
              <div
                key={`${msg.timestamp}-${idx}`}
                className={`message ${own ? 'own' : 'other'}`}
              >
                {!own && <Avatar name={msg.from} size={40} />}
                <div className="message__body">
                  <div className="message__bubble">
                    <span className="message__text">{msg.text}</span>
                  </div>
                  <span className="message__time">{msg.timestamp}</span>
                </div>
              </div>
            )
          })}
          <div ref={messagesEndRef} />
        </div>

        <form className="message-input-form" onSubmit={sendMessage}>
          <button
            type="button"
            className="icon-btn icon-btn--large"
            disabled
            title="Вложения (скоро)"
            aria-label="Вложения"
          >
            📎
          </button>
          <div className="message-input-wrapper">
            <input
              ref={inputRef}
              type="text"
              placeholder={`Сообщение для @${selectedContact}`}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              disabled={!wsReady}
            />
          </div>
          <button
            type="submit"
            className="icon-btn icon-btn--accent"
            disabled={!wsReady || !inputText.trim()}
            title="Отправить"
            aria-label="Отправить"
          >
            ➤
          </button>
        </form>
      </main>
    </div>
  )
}

export default ChatApp
