import { useEffect, useMemo, useRef, useState } from 'react'
import { useTheme } from '../ThemeContext'
import './ChatApp.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const WS_URL = API_URL
  ? API_URL.replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`

function readOutbox(login) {
  try {
    return JSON.parse(localStorage.getItem(`outbox:${login}`) || '[]')
  } catch {
    return []
  }
}

function writeOutbox(login, items) {
  localStorage.setItem(`outbox:${login}`, JSON.stringify(items))
}

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

function Avatar({ name, size = 40, src = null }) {
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
      {src ? <img src={src} alt="" /> : safeName.charAt(0).toUpperCase()}
    </div>
  )
}

function chatTitle(chat, currentLogin) {
  if (chat.type === 'group') {
    return chat.name || `Group #${chat.id}`
  }
  return chat.members.find((member) => member !== currentLogin) || `Chat #${chat.id}`
}

function messageTime(timestamp) {
  if (!timestamp) return ''
  const sqlTime = timestamp.match(/\d{4}-\d{2}-\d{2} (\d{2}:\d{2})/)
  if (sqlTime) return sqlTime[1]
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return timestamp
  return parsed.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

const STATUS_LABELS = {
  sending: 'sending…',
  sent: 'sent',
  delivered: 'delivered',
  read: 'read',
  failed: 'failed — retrying when connected',
}

function ChatApp({ token, login, onLogout }) {
  const { theme, toggle } = useTheme()
  const [chats, setChats] = useState([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [selectedChatId, setSelectedChatId] = useState(null)
  const [messages, setMessages] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [replyingTo, setReplyingTo] = useState(null)
  const [invitations, setInvitations] = useState([])
  const [inputText, setInputText] = useState('')
  const [error, setError] = useState('')
  const [wsReady, setWsReady] = useState(false)
  const [historyRefresh, setHistoryRefresh] = useState(0)
  const wsRef = useRef(null)
  const selectedChatIdRef = useRef(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const prependingHistoryRef = useRef(false)
  const outboxRef = useRef(readOutbox(login))
  const reconnectTimerRef = useRef(null)
  const readReceiptsRef = useRef(new Set())

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
        avatarUrl: chat.avatar_url,
        type: chat.type,
      }
    })
    const newDirectChats = searchResults
      .filter((user) => !existingDmUsers.has(user.login))
      .map((user) => ({
        key: `user-${user.login}`,
        chatId: null,
        label: user.login,
        userLogin: user.login,
        type: 'dm',
      }))
    return [...existingChats, ...newDirectChats]
  }, [chats, login, searchResults])

  const selectedConversation = conversations.find(
    (conversation) => conversation.chatId === selectedChatId
  )

  useEffect(() => {
    selectedChatIdRef.current = selectedChatId
  }, [selectedChatId])

  useEffect(() => {
    if (prependingHistoryRef.current) {
      prependingHistoryRef.current = false
      return
    }
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    let cancelled = false

    const loadWorkspace = async () => {
      try {
        const [dmResponse, groupsResponse, invitationsResponse] = await Promise.all([
          fetch(`${API_URL}/api/v1/chats/dm`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/chats/groups`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/chats/groups/invitations/pending`, {
            headers: authHeaders,
          }),
        ])
        if (dmResponse.status === 401) {
          onLogout()
          return
        }
        if (!dmResponse.ok || !groupsResponse.ok || !invitationsResponse.ok) {
          throw new Error('Could not load conversations')
        }

        const chatData = [
          ...await groupsResponse.json(),
          ...await dmResponse.json(),
        ]
        const invitationData = await invitationsResponse.json()
        if (cancelled) return
        setChats(chatData)
        setInvitations(invitationData)
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
    const query = searchQuery.trim()
    if (query.length < 2) {
      setSearchResults([])
      return undefined
    }
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(
          `${API_URL}/api/v1/users/search?q=${encodeURIComponent(query)}`,
          { headers: authHeaders, signal: controller.signal }
        )
        if (response.status === 401) {
          onLogout()
          return
        }
        if (!response.ok) throw new Error('Search failed')
        setSearchResults(await response.json())
      } catch (searchError) {
        if (searchError.name !== 'AbortError') setError(searchError.message)
      }
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [authHeaders, onLogout, searchQuery])

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
        if (!response.ok) throw new Error('Could not load messages')
        const data = await response.json()
        if (!cancelled) {
          const pending = outboxRef.current.filter(
            (message) => message.chat_id === selectedChatId
          )
          setMessages([...data.items, ...pending])
          setNextCursor(data.next_cursor)
          setError('')
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError.message)
      }
    }

    setMessages([])
    setNextCursor(null)
    loadMessages()
    return () => {
      cancelled = true
    }
  }, [authHeaders, historyRefresh, onLogout, selectedChatId])

  const loadOlderMessages = async () => {
    if (!nextCursor || selectedChatId === null || loadingOlder) return
    setLoadingOlder(true)
    try {
      const response = await fetch(
        `${API_URL}/api/v1/chats/${selectedChatId}/messages?cursor=${
          encodeURIComponent(nextCursor)
        }`,
        { headers: authHeaders }
      )
      if (!response.ok) throw new Error('Could not load message history')
      const data = await response.json()
      prependingHistoryRef.current = true
      setMessages((previous) => [...data.items, ...previous])
      setNextCursor(data.next_cursor)
    } catch (historyError) {
      setError(historyError.message)
    } finally {
      setLoadingOlder(false)
    }
  }

  useEffect(() => {
    let stopped = false
    let reconnectAttempt = 0

    const updateMessageStatus = (clientId, status, serverData = null) => {
      setMessages((previous) => previous.map((message) => (
        message.client_id === clientId
          ? { ...message, ...serverData, status }
          : message
      )))
    }

    const connect = () => {
      if (stopped) return
      const ws = new WebSocket(
        `${WS_URL}/api/v1/realtime/ws`,
        [`bearer.${token}`]
      )
      wsRef.current = ws
      setWsReady(false)

      ws.onopen = () => {
        reconnectAttempt = 0
        setWsReady(true)
        setError('')
        for (const pending of outboxRef.current) {
          updateMessageStatus(pending.client_id, 'sending')
          ws.send(JSON.stringify({
            type: 'send_message',
            chat_id: pending.chat_id,
            text: pending.content,
            client_id: pending.client_id,
            reply_to_server_seq: pending.reply_to_server_seq,
          }))
        }
        setHistoryRefresh((value) => value + 1)
      }

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
        setWsReady(false)
        for (const pending of outboxRef.current) {
          updateMessageStatus(pending.client_id, 'failed')
        }
        if (!stopped) {
          const delay = Math.min(1000 * (2 ** reconnectAttempt), 30000)
          reconnectAttempt += 1
          reconnectTimerRef.current = window.setTimeout(connect, delay)
        }
      }

      ws.onerror = () => {
        setError('Connection lost — messages will remain queued')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'error') {
            setError(data.detail || 'Message was not sent')
            return
          }
          if (data.type === 'message_ack') {
            outboxRef.current = outboxRef.current.filter(
              (item) => item.client_id !== data.client_id
            )
            writeOutbox(login, outboxRef.current)
            updateMessageStatus(data.client_id, 'sent', data)
            return
          }
          if (data.type === 'message_status') {
            updateMessageStatus(data.client_id, data.status)
            return
          }
          if (data.type === 'message_updated') {
            setMessages((previous) => previous.map((message) => (
              message.chat_id === data.chat_id
              && message.server_seq === data.server_seq
                ? { ...message, ...data }
                : message
            )))
            return
          }
          if (data.type === 'message_deleted') {
            setMessages((previous) => previous.map((message) => (
              message.chat_id === data.chat_id
              && message.server_seq === data.server_seq
                ? { ...message, content: '', deleted_at: data.deleted_at }
                : message
            )))
            return
          }
          if (data.type === 'message') {
            ws.send(JSON.stringify({
              type: 'delivered',
              chat_id: data.chat_id,
              server_seq: data.server_seq,
            }))
            if (data.chat_id === selectedChatIdRef.current) {
              ws.send(JSON.stringify({
                type: 'read',
                chat_id: data.chat_id,
                server_seq: data.server_seq,
              }))
              setMessages((previous) => (
                previous.some((message) => message.id === data.id)
                  ? previous
                  : [...previous, data]
              ))
            }
            setError('')
          }
        } catch {
          setError('The server returned an invalid response')
        }
      }
    }

    connect()
    return () => {
      stopped = true
      window.clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [token])

  useEffect(() => {
    const ws = wsRef.current
    if (!wsReady || !ws || selectedChatId === null) return
    for (const message of messages) {
      const key = `${message.chat_id}:${message.server_seq}`
      if (
        message.sender !== login
        && message.server_seq
        && !readReceiptsRef.current.has(key)
      ) {
        readReceiptsRef.current.add(key)
        ws.send(JSON.stringify({
          type: 'read',
          chat_id: message.chat_id,
          server_seq: message.server_seq,
        }))
      }
    }
  }, [login, messages, selectedChatId, wsReady])

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
      if (!response.ok) throw new Error('Could not create the conversation')
      const chat = await response.json()
      setChats((previous) => (
        previous.some((item) => item.id === chat.id)
          ? previous
          : [chat, ...previous]
      ))
      setSelectedChatId(chat.id)
      setSearchQuery('')
      setSearchResults([])
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
    ) {
      return
    }

    const clientId = crypto.randomUUID()
    const pendingMessage = {
      id: `pending:${clientId}`,
      chat_id: selectedChatId,
      sender: login,
      content: text,
      client_id: clientId,
      server_seq: null,
      timestamp: new Date().toISOString(),
      status: 'sending',
      reply_to_server_seq: replyingTo?.server_seq ?? null,
      reply_to_sender: replyingTo?.sender ?? null,
      reply_to_content: replyingTo?.content ?? null,
    }
    outboxRef.current = [...outboxRef.current, pendingMessage]
    writeOutbox(login, outboxRef.current)
    setMessages((previous) => [...previous, pendingMessage])
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'send_message',
        chat_id: selectedChatId,
        text,
        client_id: clientId,
        reply_to_server_seq: replyingTo?.server_seq ?? null,
      }))
    }
    window.setTimeout(() => {
      if (outboxRef.current.some((item) => item.client_id === clientId)) {
        setMessages((previous) => previous.map((message) => (
          message.client_id === clientId
            ? { ...message, status: 'failed' }
            : message
        )))
      }
    }, 10000)
    setInputText('')
    setReplyingTo(null)
    inputRef.current?.focus()
  }

  const editMessage = async (message) => {
    const content = window.prompt('Edit message', message.content)
    if (!content?.trim() || content.trim() === message.content) return
    const response = await fetch(
      `${API_URL}/api/v1/chats/${message.chat_id}/messages/${message.server_seq}`,
      {
        method: 'PATCH',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: content.trim() }),
      }
    )
    if (!response.ok) setError('Could not edit the message')
  }

  const deleteMessage = async (message) => {
    if (!window.confirm('Delete this message?')) return
    const response = await fetch(
      `${API_URL}/api/v1/chats/${message.chat_id}/messages/${message.server_seq}`,
      { method: 'DELETE', headers: authHeaders }
    )
    if (!response.ok) setError('Could not delete the message')
  }

  const blockSelectedUser = async () => {
    const otherLogin = selectedConversation?.label
    if (!otherLogin || !window.confirm(`Block ${otherLogin}?`)) return
    const response = await fetch(
      `${API_URL}/api/v1/users/${encodeURIComponent(otherLogin)}/block`,
      { method: 'POST', headers: authHeaders }
    )
    if (response.ok) {
      setError(`${otherLogin} has been blocked`)
    } else {
      setError('Could not block the user')
    }
  }

  const createGroup = async () => {
    const name = window.prompt('Group name')
    if (!name?.trim()) return
    const avatarUrl = window.prompt('Avatar URL (optional)') || null
    const response = await fetch(`${API_URL}/api/v1/chats/groups`, {
      method: 'POST',
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), avatar_url: avatarUrl }),
    })
    if (!response.ok) {
      setError('Could not create the group')
      return
    }
    const group = await response.json()
    setChats((previous) => [group, ...previous])
    setSelectedChatId(group.id)
  }

  const groupMemberAction = async (action) => {
    const loginValue = window.prompt('Username')
    if (!loginValue || !selectedChatId) return
    const paths = {
      invite: `invitations`,
      add: `members`,
      remove: `members/${encodeURIComponent(loginValue)}`,
    }
    const response = await fetch(
      `${API_URL}/api/v1/chats/groups/${selectedChatId}/${paths[action]}`,
      {
        method: action === 'remove' ? 'DELETE' : 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: action === 'remove' ? undefined : JSON.stringify({ login: loginValue }),
      }
    )
    setError(response.ok ? 'Group updated' : 'Member operation failed')
    if (response.ok && action === 'add') {
      const group = await response.json()
      setChats((previous) => previous.map((item) => (
        item.id === group.id ? group : item
      )))
    }
  }

  const acceptInvitation = async (invitation) => {
    const response = await fetch(
      `${API_URL}/api/v1/chats/groups/invitations/${invitation.id}/accept`,
      { method: 'POST', headers: authHeaders }
    )
    if (!response.ok) {
      setError('Could not accept the invitation')
      return
    }
    const group = await response.json()
    setInvitations((previous) => previous.filter(
      (item) => item.id !== invitation.id
    ))
    setChats((previous) => [group, ...previous])
  }

  const handleLogout = () => {
    wsRef.current?.close()
    onLogout()
  }

  return (
    <div className="chat-container">
      <aside className="server-rail" aria-label="Server">
        <div className="server-icon server-icon--active" title="Secure Messenger">
          🔐
        </div>
      </aside>

      <aside className="channel-panel" aria-label="Conversations">
        <header className="channel-header">
          <h2>Secure Messenger</h2>
          <button type="button" onClick={createGroup}>＋ group</button>
        </header>

        <div className="channel-section-title">Direct messages</div>
        <div className="user-search">
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Find a user"
            aria-label="Search users"
          />
        </div>
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
              <Avatar
                name={conversation.label}
                size={32}
                src={conversation.avatarUrl}
              />
              <span className="channel-name">{conversation.label}</span>
            </button>
          ))}
        </nav>

        {invitations.map((invitation) => (
          <button
            type="button"
            className="invitation-item"
            key={invitation.id}
            onClick={() => acceptInvitation(invitation)}
          >
            Accept: {invitation.group_name}
          </button>
        ))}

        <div className="user-bar">
          <Avatar name={login} size={32} />
          <div className="user-bar__info">
            <div className="user-bar__name">{login}</div>
            <div className="user-bar__status">online</div>
          </div>
          <div className="user-bar__actions">
            <button
              className="icon-btn"
              onClick={toggle}
              title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
              aria-label="Switch theme"
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            <button
              className="icon-btn"
              onClick={handleLogout}
              title="Sign out"
              aria-label="Sign out"
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
            <span>{selectedConversation?.label || 'Select a conversation'}</span>
          </div>
          <div className="chat-header__meta">
            <span className={`status-dot ${wsReady ? 'online' : 'offline'}`} />
            <span>{wsReady ? 'online' : 'connecting...'}</span>
            {selectedConversation?.type === 'dm' && (
              <button
                type="button"
                className="header-action"
                onClick={blockSelectedUser}
              >
                Block
              </button>
            )}
            {selectedConversation?.type === 'group' && (
              <>
                <button type="button" className="header-action" onClick={() => groupMemberAction('invite')}>
                  Invite
                </button>
                <button type="button" className="header-action" onClick={() => groupMemberAction('add')}>
                  Add
                </button>
                <button type="button" className="header-action" onClick={() => groupMemberAction('remove')}>
                  Remove
                </button>
              </>
            )}
          </div>
        </header>

        <div className="messages-list">
          {error && <p className="error-message">{error}</p>}
          {nextCursor && (
            <button
              type="button"
              className="load-older"
              onClick={loadOlderMessages}
              disabled={loadingOlder}
            >
              {loadingOlder ? 'Loading…' : 'Load earlier messages'}
            </button>
          )}
          {messages.length === 0 && (
            <div className="messages-empty">
              <div className="messages-empty__icon">💬</div>
              <p>
                {selectedChatId === null
                  ? 'Select a conversation on the left.'
                  : 'No messages yet. Start the conversation!'}
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
                  {message.reply_to_server_seq && (
                    <div className="message__reply">
                      <strong>{message.reply_to_sender}</strong>
                      <span>
                        {message.reply_to_content || 'Message deleted'}
                      </span>
                    </div>
                  )}
                  <div className="message__bubble">
                    <span className="message__text">
                      {message.deleted_at ? 'Message deleted' : message.content}
                    </span>
                  </div>
                  {!message.deleted_at && message.server_seq && (
                    <div className="message__actions">
                      <button
                        type="button"
                        onClick={() => setReplyingTo(message)}
                      >
                        Reply
                      </button>
                      {own && (
                        <>
                          <button
                            type="button"
                            onClick={() => editMessage(message)}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteMessage(message)}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </div>
                  )}
                  <span className="message__time">
                    {messageTime(message.timestamp)}
                    {message.edited_at && !message.deleted_at && ' · edited'}
                    {own && message.status && (
                      <span className={`message__status message__status--${message.status}`}>
                        {' · '}
                        {STATUS_LABELS[message.status] || message.status}
                      </span>
                    )}
                  </span>
                </div>
              </div>
            )
          })}
          <div ref={messagesEndRef} />
        </div>

        {replyingTo && (
          <div className="reply-composer">
            <span>
              Replying to <strong>{replyingTo.sender}</strong>:{' '}
              {replyingTo.content}
            </span>
            <button type="button" onClick={() => setReplyingTo(null)}>×</button>
          </div>
        )}
        <form className="message-input-form" onSubmit={sendMessage}>
          <button
            type="button"
            className="icon-btn icon-btn--large"
            disabled
            title="Attachments (coming soon)"
            aria-label="Attachments"
          >
            📎
          </button>
          <div className="message-input-wrapper">
            <input
              ref={inputRef}
              type="text"
              placeholder={
                selectedConversation
                  ? `Message ${selectedConversation.label}`
                  : 'Select a conversation first'
              }
              value={inputText}
              onChange={(event) => setInputText(event.target.value)}
              disabled={selectedChatId === null}
            />
          </div>
          <button
            type="submit"
            className="icon-btn icon-btn--accent"
            disabled={selectedChatId === null || !inputText.trim()}
            title="Send"
            aria-label="Send"
          >
            ➤
          </button>
        </form>
      </main>
    </div>
  )
}

export default ChatApp
