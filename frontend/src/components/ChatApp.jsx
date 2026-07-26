import { useEffect, useMemo, useRef, useState } from 'react'
import { useTheme } from '../ThemeContext'
import './ChatApp.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const WS_URL = API_URL.replace(/^http/, 'ws')

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
  const safeName = name || '?'
  return (
    <div
      className="avatar"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.45,
        backgroundColor: avatarColor(safeName),
      }}
      aria-hidden="true"
    >
      {safeName.charAt(0).toUpperCase()}
    </div>
  )
}

function chatTitle(chat, currentLogin) {
  if (chat.type === 'group') {
    return chat.name || `Группа #${chat.id}`
  }
  return chat.members.find((member) => member !== currentLogin) || `Чат #${chat.id}`
}

function messageTime(timestamp) {
  if (!timestamp) return ''
  const sqlTime = timestamp.match(/\d{4}-\d{2}-\d{2} (\d{2}:\d{2})/)
  if (sqlTime) return sqlTime[1]
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return timestamp
  return parsed.toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function ChatApp({ token, login, onLogout }) {
  const { theme, toggle } = useTheme()
  const [chats, setChats] = useState([])
  const [users, setUsers] = useState([])
  const [selectedChatId, setSelectedChatId] = useState(null)
  const [messages, setMessages] = useState([])
  const [inputText, setInputText] = useState('')
  const [error, setError] = useState('')
  const [wsReady, setWsReady] = useState(false)
  const wsRef = useRef(null)
  const selectedChatIdRef = useRef(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  const authHeaders = useMemo(
    () => ({ Authorization: `Bearer ${token}` }),
    [token]
  )

  const conversations = useMemo(() => {
    const existingDmUsers = new Set()
    const existingChats = chats.map((chat) => {
      if (chat.type === 'dm') {
        const otherLogin = chat.members.find((member) => member !== login)
        if (otherLogin) existingDmUsers.add(otherLogin)
      }
      return {
        key: `chat-${chat.id}`,
        chatId: chat.id,
        label: chatTitle(chat, login),
        userLogin: null,
      }
    })
    const newDirectChats = users
      .filter((user) => !existingDmUsers.has(user.login))
      .map((user) => ({
        key: `user-${user.login}`,
        chatId: null,
        label: user.login,
        userLogin: user.login,
      }))
    return [...existingChats, ...newDirectChats]
  }, [chats, login, users])

  const selectedConversation = conversations.find(
    (conversation) => conversation.chatId === selectedChatId
  )

  useEffect(() => {
    selectedChatIdRef.current = selectedChatId
  }, [selectedChatId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    let cancelled = false

    const loadWorkspace = async () => {
      try {
        const [chatsResponse, usersResponse] = await Promise.all([
          fetch(`${API_URL}/api/v1/chats`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/users`, { headers: authHeaders }),
        ])
        if (chatsResponse.status === 401 || usersResponse.status === 401) {
          onLogout()
          return
        }
        if (!chatsResponse.ok || !usersResponse.ok) {
          throw new Error('Не удалось загрузить список чатов')
        }

        const [chatData, userData] = await Promise.all([
          chatsResponse.json(),
          usersResponse.json(),
        ])
        if (cancelled) return
        setChats(chatData)
        setUsers(userData)
        setSelectedChatId((currentId) => {
          if (chatData.some((chat) => chat.id === currentId)) return currentId
          return chatData[0]?.id ?? null
        })
      } catch (loadError) {
        if (!cancelled) setError(loadError.message)
      }
    }

    loadWorkspace()
    return () => {
      cancelled = true
    }
  }, [authHeaders, onLogout])

  useEffect(() => {
    if (selectedChatId === null) {
      setMessages([])
      return undefined
    }

    let cancelled = false
    const loadMessages = async () => {
      try {
        const response = await fetch(
          `${API_URL}/api/v1/chats/${selectedChatId}/messages`,
          { headers: authHeaders }
        )
        if (response.status === 401) {
          onLogout()
          return
        }
        if (!response.ok) throw new Error('Не удалось загрузить сообщения')
        const data = await response.json()
        if (!cancelled) {
          setMessages(data)
          setError('')
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError.message)
      }
    }

    setMessages([])
    loadMessages()
    return () => {
      cancelled = true
    }
  }, [authHeaders, onLogout, selectedChatId])

  useEffect(() => {
    const ws = new WebSocket(
      `${WS_URL}/api/v1/realtime/ws`,
      [`bearer.${token}`]
    )
    wsRef.current = ws
    setWsReady(false)

    ws.onopen = () => setWsReady(true)
    ws.onclose = () => setWsReady(false)
    ws.onerror = () => setError('WebSocket-соединение недоступно')
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'error') {
          setError(data.detail || 'Сообщение не отправлено')
          return
        }
        if (
          data.type === 'message'
          && data.chat_id === selectedChatIdRef.current
        ) {
          setMessages((previous) => {
            if (previous.some((message) => message.id === data.id)) return previous
            return [...previous, data]
          })
          setError('')
        }
      } catch {
        setError('Сервер прислал некорректный ответ')
      }
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [token])

  const selectConversation = async (conversation) => {
    setError('')
    if (conversation.chatId !== null) {
      setSelectedChatId(conversation.chatId)
      return
    }

    try {
      const response = await fetch(`${API_URL}/api/v1/chats/dm`, {
        method: 'POST',
        headers: {
          ...authHeaders,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ login: conversation.userLogin }),
      })
      if (response.status === 401) {
        onLogout()
        return
      }
      if (!response.ok) throw new Error('Не удалось создать чат')
      const chat = await response.json()
      setChats((previous) => (
        previous.some((item) => item.id === chat.id)
          ? previous
          : [chat, ...previous]
      ))
      setSelectedChatId(chat.id)
    } catch (createError) {
      setError(createError.message)
    }
  }

  const sendMessage = (event) => {
    event?.preventDefault()
    const ws = wsRef.current
    const text = inputText.trim()
    if (
      !text
      || selectedChatId === null
      || !ws
      || ws.readyState !== WebSocket.OPEN
    ) {
      return
    }

    ws.send(JSON.stringify({ chat_id: selectedChatId, text }))
    setInputText('')
    inputRef.current?.focus()
  }

  const handleLogout = () => {
    wsRef.current?.close()
    onLogout()
  }

  return (
    <div className="chat-container">
      <aside className="server-rail" aria-label="Сервер">
        <div className="server-icon server-icon--active" title="Secure Messenger">
          🔐
        </div>
      </aside>

      <aside className="channel-panel" aria-label="Чаты">
        <header className="channel-header">
          <h2>Secure Messenger</h2>
        </header>

        <div className="channel-section-title">Прямые сообщения</div>
        <nav className="channel-list">
          {conversations.map((conversation) => (
            <button
              key={conversation.key}
              className={`channel-item ${
                selectedChatId === conversation.chatId
                && conversation.chatId !== null
                  ? 'active'
                  : ''
              }`}
              onClick={() => selectConversation(conversation)}
            >
              <Avatar name={conversation.label} size={32} />
              <span className="channel-name">{conversation.label}</span>
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
            <button
              className="icon-btn"
              onClick={handleLogout}
              title="Выйти"
              aria-label="Выйти"
            >
              ⎋
            </button>
          </div>
        </div>
      </aside>

      <main className="chat-panel">
        <header className="chat-header">
          <div className="chat-header__title">
            <span className="hash">#</span>
            <span>{selectedConversation?.label || 'Выберите чат'}</span>
          </div>
          <div className="chat-header__meta">
            <span className={`status-dot ${wsReady ? 'online' : 'offline'}`} />
            <span>{wsReady ? 'в сети' : 'подключение...'}</span>
          </div>
        </header>

        <div className="messages-list">
          {error && <p className="error-message">{error}</p>}
          {messages.length === 0 && (
            <div className="messages-empty">
              <div className="messages-empty__icon">💬</div>
              <p>
                {selectedChatId === null
                  ? 'Выберите собеседника слева.'
                  : 'Сообщений пока нет. Начните беседу!'}
              </p>
            </div>
          )}
          {messages.map((message) => {
            const own = message.sender === login
            return (
              <div
                key={message.id}
                className={`message ${own ? 'own' : 'other'}`}
              >
                {!own && <Avatar name={message.sender} size={40} />}
                <div className="message__body">
                  <div className="message__bubble">
                    <span className="message__text">{message.content}</span>
                  </div>
                  <span className="message__time">
                    {messageTime(message.timestamp)}
                  </span>
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
              placeholder={
                selectedConversation
                  ? `Сообщение для ${selectedConversation.label}`
                  : 'Сначала выберите чат'
              }
              value={inputText}
              onChange={(event) => setInputText(event.target.value)}
              disabled={!wsReady || selectedChatId === null}
            />
          </div>
          <button
            type="submit"
            className="icon-btn icon-btn--accent"
            disabled={!wsReady || selectedChatId === null || !inputText.trim()}
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
